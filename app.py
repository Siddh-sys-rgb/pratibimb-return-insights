import argparse, json, os, secrets, sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, render_template, session, send_from_directory

def connect(app):
    conn=sqlite3.connect(app.config["DATABASE"],timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn

def setup(app,data_dir):
    folder=Path(data_dir);folder.mkdir(parents=True,exist_ok=True)
    keyfile=folder/".session-key"
    try:
        descriptor=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,"w") as handle: handle.write(secrets.token_hex(32))
    except FileExistsError: pass
    app.secret_key=keyfile.read_text().strip()
    app.config.update(DATABASE=str(folder/"app.sqlite"),DATA_DIR=str(folder),MAX_CONTENT_LENGTH=5*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Strict")
    @app.before_request
    def protect():
        if request.method in {"POST","PUT","DELETE","PATCH"}:
            expected=session.get("csrf")
            if not expected or not secrets.compare_digest(str(request.headers.get("X-CSRF-Token","")),expected): return jsonify(error="CSRF token missing or invalid"),403
            origin=request.headers.get("Origin")
            if origin and origin!=request.host_url.rstrip("/"): return jsonify(error="Cross-origin writes are blocked"),403
    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Content-Security-Policy"]="default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers["Cache-Control"]="no-store"
        return response
    @app.errorhandler(413)
    def too_large(error): return jsonify(error="Request exceeds 5 MB"),413
    @app.errorhandler(ValueError)
    def invalid(error): return jsonify(error=str(error)),400
    @app.errorhandler(sqlite3.OperationalError)
    def database_busy(error): return jsonify(error="Database unavailable; retry the action"),503
    @app.get("/api/session")
    def token():
        session.setdefault("csrf",secrets.token_hex(24))
        return jsonify(csrf_token=session["csrf"])
    @app.get("/")
    def index(): return render_template("index.html")

def json_object():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise ValueError("Expected a JSON object")
    return payload

def revision(value):
    if isinstance(value,bool) or not isinstance(value,int) or value<1: raise ValueError("Revision must be a positive integer")
    return value

from domain import demo_records,fit_model,evaluate_model
import re

def create_app(data_dir=None,no_demo=False):
    app=Flask(__name__);setup(app,data_dir or Path(__file__).parent/"data-local");app.config["SESSION_COOKIE_NAME"]="pratibimb_session"
    with connect(app) as conn:
        conn.executescript("CREATE TABLE IF NOT EXISTS returns(id INTEGER PRIMARY KEY,month TEXT NOT NULL,comment TEXT NOT NULL,customer TEXT NOT NULL,predicted INTEGER,assigned INTEGER,revision INTEGER NOT NULL DEFAULT 1); CREATE TABLE IF NOT EXISTS clusters(id INTEGER PRIMARY KEY,label TEXT NOT NULL,terms TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1); CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,return_id INTEGER NOT NULL,previous INTEGER,next INTEGER,note TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);")
        if not no_demo and conn.execute("SELECT COUNT(*) FROM returns").fetchone()[0]==0:
            records=demo_records();vectorizer,model,labels,clusters=fit_model(records)
            for row,label in zip(records,labels): conn.execute("INSERT INTO returns(id,month,comment,customer,predicted,assigned) VALUES(?,?,?,?,?,?)",(row["id"],row["month"],row["comment"],row["customer"],label,label))
            for cluster in clusters: conn.execute("INSERT INTO clusters(id,label,terms) VALUES(?,?,?)",(cluster["id"],cluster["label"],json.dumps(cluster["terms"])))
        records=[dict(r) for r in conn.execute("SELECT * FROM returns ORDER BY id")]
    if records:
        vectorizer,model,_,_=fit_model(records)
        app.config["MODEL"]=(vectorizer,model)
    else: app.config["MODEL"]=None
    @app.get("/api/health")
    def health(): return jsonify(status="ok",app="Pratibimb",model="TF-IDF + seeded KMeans",demo="synthetic")
    @app.get("/api/workspace")
    def workspace():
        with connect(app) as conn:
            rows=[dict(r) for r in conn.execute("SELECT * FROM returns ORDER BY id")]
            clusters=[dict(dict(r),terms=json.loads(r["terms"])) for r in conn.execute("SELECT * FROM clusters ORDER BY id")]
            audit=[dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 20")]
        return jsonify(returns=rows,clusters=clusters,months=sorted(set(r["month"] for r in rows)),audit=audit,model=dict(algorithm="TF-IDF (unigrams/bigrams) + KMeans, k=4, seed=42",training_count=len(rows),source="Original synthetic return comments"))
    @app.get("/api/evaluation")
    def evaluation():
        pair=app.config["MODEL"]
        if pair is None: return jsonify(error="No model available; start with the demo dataset"),409
        return jsonify(evaluation=evaluate_model(*pair))
    @app.patch("/api/returns/<int:record_id>")
    def correct(record_id):
        payload=json_object();rev=revision(payload.get("revision"));target=payload.get("cluster_id");note=payload.get("note","")
        if isinstance(target,bool) or not isinstance(target,int): raise ValueError("Cluster must be an integer")
        if not isinstance(note,str) or not 3<=len(note.strip())<=300: raise ValueError("Correction note needs 3–300 characters")
        with connect(app) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM returns WHERE id=?",(record_id,)).fetchone()
            if row is None: return jsonify(error="Return not found"),404
            if row["revision"]!=rev: return jsonify(error="Return changed; refresh before correcting"),409
            if conn.execute("SELECT id FROM clusters WHERE id=?",(target,)).fetchone() is None: raise ValueError("Unknown cluster")
            if target==row["assigned"]: raise ValueError("Choose a different cluster")
            conn.execute("UPDATE returns SET assigned=?,revision=revision+1 WHERE id=?",(target,record_id))
            conn.execute("INSERT INTO audit(return_id,previous,next,note) VALUES(?,?,?,?)",(record_id,row["assigned"],target,note.strip()))
            updated=dict(conn.execute("SELECT * FROM returns WHERE id=?",(record_id,)).fetchone())
        return jsonify(record=updated)
    @app.patch("/api/clusters/<int:cluster_id>")
    def rename(cluster_id):
        payload=json_object();rev=revision(payload.get("revision"));label=payload.get("label")
        if not isinstance(label,str) or not 2<=len(label.strip())<=80: raise ValueError("Cluster label needs 2–80 characters")
        with connect(app) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM clusters WHERE id=?",(cluster_id,)).fetchone()
            if row is None: return jsonify(error="Cluster not found"),404
            if row["revision"]!=rev: return jsonify(error="Label changed; refresh before renaming"),409
            conn.execute("UPDATE clusters SET label=?,revision=revision+1 WHERE id=?",(label.strip(),cluster_id))
        return jsonify(updated=True)
    @app.post("/api/comparisons")
    def compare():
        payload=json_object();baseline=payload.get("baseline");current=payload.get("current")
        if not isinstance(baseline,str) or not isinstance(current,str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}",baseline) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}",current) or baseline==current: raise ValueError("Choose two distinct YYYY-MM months")
        with connect(app) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows=[dict(r) for r in conn.execute("SELECT * FROM returns WHERE month IN (?,?)",(baseline,current))]
            denominators={month:sum(r["month"]==month for r in rows) for month in (baseline,current)}
            if not all(denominators.values()): raise ValueError("Both months require return records")
            clusters=[dict(r) for r in conn.execute("SELECT * FROM clusters ORDER BY id")]
            comparison=[]
            for cluster in clusters:
                counts={month:sum(r["month"]==month and r["assigned"]==cluster["id"] for r in rows) for month in (baseline,current)}
                rates={month:round(counts[month]/denominators[month]*100,2) for month in (baseline,current)}
                comparison.append(dict(id=cluster["id"],label=cluster["label"],baseline_count=counts[baseline],current_count=counts[current],baseline_percent=rates[baseline],current_percent=rates[current],change_percentage_points=round(rates[current]-rates[baseline],2)))
            report=dict(baseline=baseline,current=current,denominators=denominators,clusters=comparison,warning="Shares use return-comment denominators, not sales or orders. This is not a product return rate.",revisions={str(r["id"]):r["revision"] for r in rows})
            inserted=conn.execute("INSERT INTO snapshots(payload) VALUES(?)",(json.dumps(report),));report["id"]=inserted.lastrowid
        return jsonify(comparison=report),201
    @app.get("/api/comparisons")
    def history():
        with connect(app) as conn: rows=[dict(id=r["id"],created_at=r["created_at"],report=json.loads(r["payload"])) for r in conn.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 20")]
        return jsonify(comparisons=rows)
    return app

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=8111);parser.add_argument("--data-dir");parser.add_argument("--no-demo",action="store_true");args=parser.parse_args()
    create_app(args.data_dir,args.no_demo).run(host="127.0.0.1",port=args.port,debug=False)
