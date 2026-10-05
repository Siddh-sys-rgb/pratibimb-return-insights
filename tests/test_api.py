import io,json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import create_app,connect

def records(client): return client.get('/api/workspace').json

def test_workspace_model_and_headers(client,app):
    r=client.get('/api/workspace');assert len(r.json['returns'])==90 and len(r.json['clusters'])==4
    assert client.get('/api/health').json['status']=='ok' and client.get('/').status_code==200
    assert app.config['SESSION_COOKIE_NAME']=='pratibimb_session'
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==400
    assert 'nosniff' in r.headers['X-Content-Type-Options']
@pytest.mark.parametrize('path',['/api/import','/api/recluster','/api/comparisons'])
def test_csrf_required(client,path): assert client.post(path,json={}).status_code==403
def test_cross_origin(client,headers): assert client.post('/api/import',json={},headers=dict(headers,Origin='https://evil.example')).status_code==403
@pytest.mark.parametrize('payload',[{}, {'revision':True,'cluster_id':1,'note':'reason'}, {'revision':1,'cluster_id':[],'note':'reason'}, {'revision':1,'cluster_id':9,'note':'reason'}, {'revision':1,'cluster_id':1,'note':{}}, {'revision':1,'cluster_id':1,'note':'x'}])
def test_invalid_correction(client,headers,payload): assert client.patch('/api/returns/1',json=payload,headers=headers).status_code==400
def test_correction_audit_and_stale(client,headers):
    row=records(client)['returns'][0];target=(row['assigned']+1)%4
    payload={'revision':row['revision'],'cluster_id':target,'note':'Manual review of comment'}
    assert client.patch('/api/returns/1',json=payload,headers=headers).json['record']['assigned']==target
    assert client.patch('/api/returns/1',json=payload,headers=headers).status_code==409
    state=records(client);assert len(state['audit'])==1 and state['returns'][0]['predicted']==row['predicted']
def test_unknown_record(client,headers): assert client.patch('/api/returns/999',json={'revision':1,'cluster_id':1,'note':'reason'},headers=headers).status_code==404
@pytest.mark.parametrize('label',[None,{},'x','x'*81])
def test_bad_label(client,headers,label): assert client.patch('/api/clusters/0',json={'revision':1,'label':label},headers=headers).status_code==400
def test_rename_revision(client,headers):
    payload={'revision':1,'label':'Transit damage'}
    assert client.patch('/api/clusters/0',json=payload,headers=headers).status_code==200
    assert client.patch('/api/clusters/0',json=payload,headers=headers).status_code==409
    assert client.patch('/api/clusters/9',json=payload,headers=headers).status_code==404
@pytest.mark.parametrize('payload',[{}, {'baseline':[], 'current':'2026-09'}, {'baseline':'2026-07','current':'2026-07'}, {'baseline':'2026-01','current':'2026-09'}])
def test_bad_months(client,headers,payload): assert client.post('/api/comparisons',json=payload,headers=headers).status_code==400
def test_denominators_and_snapshots(client,headers):
    response=client.post('/api/comparisons',json={'baseline':'2026-07','current':'2026-09'},headers=headers);report=response.json['comparison']
    assert report['denominators']=={'2026-07':30,'2026-09':30}
    assert sum(c['baseline_count'] for c in report['clusters'])==30
    assert sum(c['current_count'] for c in report['clusters'])==30
    assert 'not a product return rate' in report['warning']
    row=records(client)['returns'][0]
    client.patch('/api/returns/1',json={'revision':1,'cluster_id':(row['assigned']+1)%4,'note':'Correction for snapshot test'},headers=headers)
    stored=client.get('/api/comparisons').json['comparisons'][0]['report']
    assert stored['clusters']==report['clusters'] and stored['revisions']['1']==1
def test_evaluation(client): assert client.get('/api/evaluation').json['evaluation']['total_pairs']==6
@pytest.mark.parametrize('value',[None,[],{},[{}],[{'month':'2026-13','comment':'test comment'}],[{'month':'2026-09','comment':[]}],[{'month':'2026-09','comment':'test comment','customer':{}}]])
def test_invalid_import(client,headers,value): assert client.post('/api/import',json={'records':value},headers=headers).status_code==400
@pytest.mark.parametrize('raw',[b'\xffbad',b'x'*200001,b'month,comment\n2026-13,test comment'])
def test_invalid_csv(client,headers,raw): assert client.post('/api/import',data={'file':(io.BytesIO(raw),'x.csv')},headers=headers).status_code==400
def test_import_fit_and_preserve_correction(client,headers):
    state=records(client);row=state['returns'][0];target=(row['assigned']+1)%4
    client.patch('/api/returns/1',json={'revision':row['revision'],'cluster_id':target,'note':'Keep this human correction'},headers=headers)
    raw=b'month,comment,customer\n2026-10,Parcel crushed with broken glass,Diya Patel\n2026-10,Shirt size too small and tight,Rohan Shah\n'
    assert client.post('/api/import',data={'file':(io.BytesIO(raw),'returns.csv')},headers=headers).json['imported']==2
    state=records(client);assert state['pending_count']==2
    assert client.post('/api/recluster',json={'workspace_revision':1},headers=headers).status_code==409
    result=client.post('/api/recluster',json={'workspace_revision':state['workspace_revision']},headers=headers)
    assert result.status_code==200 and result.json['fitted_comments']==92
    state=records(client);assert state['pending_count']==0 and state['returns'][0]['assigned']==target
    assert client.post('/api/recluster',json={'workspace_revision':2},headers=headers).status_code==409
    assert client.get('/api/evaluation').status_code==200
def test_empty_can_import_fit(tmp_path):
    client=create_app(tmp_path,no_demo=True).test_client();headers={'X-CSRF-Token':client.get('/api/session').json['csrf_token']}
    assert records(client)['returns']==[] and client.get('/api/evaluation').status_code==409
    comments=['Small shirt size too tight','Box packaging broken glass','Received wrong red colour','Device battery stopped working']
    assert client.post('/api/import',json={'records':[{'month':'2026-09','comment':c} for c in comments]},headers=headers).status_code==201
    assert client.post('/api/recluster',json={'workspace_revision':2},headers=headers).status_code==200
    assert len(records(client)['clusters'])==4
    assert client.patch('/api/returns/1',json={'revision':1,'cluster_id':1,'note':'stale import revision'},headers=headers).status_code==409
def test_not_enough_distinct_for_fit(tmp_path):
    client=create_app(tmp_path,no_demo=True).test_client();headers={'X-CSRF-Token':client.get('/api/session').json['csrf_token']}
    client.post('/api/import',json={'records':[{'month':'2026-09','comment':'same comment'}]*4},headers=headers)
    assert client.post('/api/recluster',json={'workspace_revision':2},headers=headers).status_code==400
def test_import_transaction_rolls_back(client,headers):
    before=len(records(client)['returns'])
    response=client.post('/api/import',json={'records':[{'month':'2026-09','comment':'valid comment'},{'month':'bad','comment':'invalid comment'}]},headers=headers)
    assert response.status_code==400 and len(records(client)['returns'])==before
def test_concurrent_corrections(app):
    original=app.test_client().get('/api/workspace').json['returns'][0]
    def save(target):
        client=app.test_client();headers={'X-CSRF-Token':client.get('/api/session').json['csrf_token']}
        return client.patch('/api/returns/1',json={'revision':1,'cluster_id':target,'note':'Concurrent manual correction'},headers=headers).status_code
    targets=[(original['assigned']+1)%4,(original['assigned']+2)%4]
    with ThreadPoolExecutor(max_workers=2) as pool: codes=list(pool.map(save,targets))
    assert sorted(codes)==[200,409]
    with connect(app) as conn: assert conn.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==1

def test_import_provenance_and_duplicate(client,headers):
    data={'records':[{'month':'2026-10','comment':'Received a damaged parcel','customer':'Diya'}]}
    assert client.post('/api/import',json=data,headers=headers).status_code==201
    assert client.post('/api/import',json=data,headers=headers).status_code==409
    state=records(client)
    assert state['returns'][-1]['source']=='user-import'
    assert state['returns'][0]['source']=='synthetic-demo'
    assert state['model']['training_count']==90 and state['pending_count']==1

def test_explicit_override_survives_model_agreement_then_divergence(client,headers,monkeypatch):
    """Control one model output across two fits; real fitting supplies all other outputs."""
    import app as module
    state=records(client);original=state['returns'][0]['predicted'];target=(original+1)%4
    correction=client.patch('/api/returns/1',json={'revision':1,'cluster_id':target,'note':'This is an explicit human decision'},headers=headers)
    assert correction.json['record']['manual_override']==1
    real_fit=module.fit_model;fit_number=0
    def changing_prediction(rows):
        nonlocal fit_number
        vectorizer,model,labels,clusters=real_fit(rows)
        # Cluster alignment remains supported by the other 89 unchanged predictions.
        labels[0]=target if fit_number==0 else original
        fit_number+=1
        return vectorizer,model,labels,clusters
    monkeypatch.setattr(module,'fit_model',changing_prediction)
    for expected_prediction in (target,original):
        state=records(client)
        response=client.post('/api/recluster',json={'workspace_revision':state['workspace_revision']},headers=headers)
        assert response.status_code==200
        row=records(client)['returns'][0]
        assert row['predicted']==expected_prediction
        assert row['assigned']==target and row['manual_override']==1
    assert fit_number==2
    assert len(records(client)['audit'])==1

def test_legacy_migration_recovers_explicit_choice_without_reset(tmp_path):
    app=create_app(tmp_path);client=app.test_client();headers={'X-CSRF-Token':client.get('/api/session').json['csrf_token']}
    state=records(client);original=state['returns'][0]['predicted'];target=(original+1)%4
    client.patch('/api/returns/1',json={'revision':1,'cluster_id':target,'note':'Legacy explicit human choice'},headers=headers)
    report=client.post('/api/comparisons',json={'baseline':'2026-07','current':'2026-09'},headers=headers).json['comparison']
    with connect(app) as conn:
        # Reproduce a legacy database where a refit previously lost the human choice.
        conn.execute('UPDATE returns SET assigned=predicted WHERE id=1')
        conn.execute('ALTER TABLE returns DROP COLUMN manual_override')
        previous_revision=conn.execute('SELECT revision FROM returns WHERE id=1').fetchone()[0]
    key=(tmp_path/'.session-key').read_text()
    migrated=create_app(tmp_path);state=records(migrated.test_client());row=state['returns'][0]
    assert len(state['returns'])==90 and len(state['audit'])==1
    assert row['manual_override']==1 and row['assigned']==target and row['predicted']==original
    assert row['revision']==previous_revision+1
    assert state['returns'][1]['manual_override']==0
    assert (tmp_path/'.session-key').read_text()==key
    saved=migrated.test_client().get('/api/comparisons').json['comparisons'][0]['report']
    assert saved['clusters']==report['clusters']
    restarted=records(create_app(tmp_path).test_client())
    assert restarted['returns'][0]['manual_override']==1
    assert restarted['returns'][0]['revision']==row['revision']

def test_override_migration_marks_choice_even_when_model_already_agrees(tmp_path):
    app=create_app(tmp_path);client=app.test_client();headers={'X-CSRF-Token':client.get('/api/session').json['csrf_token']}
    row=records(client)['returns'][0];target=(row['predicted']+1)%4
    client.patch('/api/returns/1',json={'revision':1,'cluster_id':target,'note':'Model later agrees with this choice'},headers=headers)
    with connect(app) as conn:
        conn.execute('UPDATE returns SET predicted=assigned WHERE id=1')
        conn.execute('ALTER TABLE returns DROP COLUMN manual_override')
    migrated=records(create_app(tmp_path).test_client())['returns'][0]
    assert migrated['assigned']==migrated['predicted']==target
    assert migrated['manual_override']==1 and migrated['revision']==2
