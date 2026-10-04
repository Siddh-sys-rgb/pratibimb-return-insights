"""Reproducible learned text clustering, with separate evaluation comments."""
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np
THEMES={
"Fit / size":["Shirt size is too small and tight at the shoulder", "The footwear size runs large and fit is loose", "Trousers waist size does not fit the size chart", "Wrong size delivered; requested medium but received small"],
"Transit damage":["Parcel arrived crushed with broken glass and damaged packaging", "Item cracked during delivery and packaging was torn", "Transit damage left the box crushed and product broken", "Delivery packaging damaged; fragile item arrived cracked"],
"Wrong item":["Received the wrong colour and a different product model", "Ordered blue but received the wrong red item", "Different product delivered; wrong model in the parcel", "Wrong colour item sent and product differs from the order"],
"Product defect":["Device stopped working and battery will not charge", "Product faulty; power switch does not work", "Device failed after one day and battery charging is faulty", "Broken power button and defective device will not turn on"]}
MONTHS=["2026-07","2026-08","2026-09"]
CUSTOMERS=["Aarav Shah","Diya Mehta","Kavya Patel","Rohan Desai","Neha Joshi","Ishaan Trivedi"]
def demo_records():
    rows=[];seq=0
    weights=[[12,6,5,7],[10,8,5,7],[7,14,4,5]]
    for month,counts in zip(MONTHS,weights):
        for (label,comments),count in zip(THEMES.items(),counts):
            for i in range(count):
                seq+=1
                rows.append(dict(id=seq,month=month,comment=comments[i%len(comments)]+[".","; please arrange pickup.","; requesting a return."][i%3],customer=CUSTOMERS[seq%len(CUSTOMERS)],fixture_theme=label))
    return rows

def fit_model(records):
    if len(records)<4: raise ValueError("At least four return comments are needed")
    vectorizer=TfidfVectorizer(stop_words="english",ngram_range=(1,2),min_df=1,max_features=2500)
    matrix=vectorizer.fit_transform([r["comment"] for r in records])
    model=KMeans(n_clusters=4,random_state=42,n_init=10).fit(matrix)
    terms=vectorizer.get_feature_names_out();clusters=[]
    for cluster in range(4):
        order=model.cluster_centers_[cluster].argsort()[::-1]
        clusters.append(dict(id=cluster,label=" / ".join(terms[order[:3]]),terms=terms[order[:6]].tolist()))
    return vectorizer,model,model.labels_.tolist(),clusters

EVALUATION=[
("The shirt fit is tight and size too small","Footwear size too small and tight",True),
("Parcel packaging crushed and glass broken","Box packaging damaged in transit",True),
("Wrong colour and different model received","Received different product colour and wrong item",True),
("Faulty battery device will not charge","Defective power switch stopped working",True),
("Shirt size too small and fit tight","Parcel crushed with damaged packaging",False),
("Different colour wrong model sent","Battery faulty and device stopped working",False)]

def evaluate_model(vectorizer,model):
    results=[]
    for left,right,expected in EVALUATION:
        labels=model.predict(vectorizer.transform([left,right])).tolist()
        results.append(dict(left=left,right=right,expected_same_cluster=expected,observed_same_cluster=labels[0]==labels[1],passed=(labels[0]==labels[1])==expected))
    return dict(correct_pairs=sum(r["passed"] for r in results),total_pairs=len(results),pairs=results,warning="Six authored pairs are a smoke check, not a production accuracy estimate.")
