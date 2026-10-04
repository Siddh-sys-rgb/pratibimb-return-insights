from domain import demo_records,fit_model,evaluate_model,EVALUATION
import pytest

def test_original_fixture_denominators():
    rows=demo_records();assert len(rows)==90
    assert {m:sum(r['month']==m for r in rows) for m in ['2026-07','2026-08','2026-09']}=={'2026-07':30,'2026-08':30,'2026-09':30}
def test_reproducible_fit():
    rows=demo_records();v,m,labels,clusters=fit_model(rows);v2,m2,labels2,clusters2=fit_model(rows)
    assert labels==labels2 and clusters==clusters2 and len(set(labels))==4
    assert v.get_feature_names_out().tolist()==v2.get_feature_names_out().tolist()
def test_fixture_labels_not_features():
    records=demo_records();v,m,labels,_=fit_model(records)
    for row in records: row['fixture_theme']='entirely different';row['customer']='different person'
    assert fit_model(records)[2]==labels
def test_evaluation_comments_not_training():
    training={r['comment'] for r in demo_records()}
    assert all(left not in training and right not in training for left,right,_ in EVALUATION)
    v,m,_,_=fit_model(demo_records());result=evaluate_model(v,m)
    assert result['total_pairs']==6 and result['correct_pairs']==6
    assert 'not a production' in result['warning']
def test_too_few_comments():
    with pytest.raises(ValueError): fit_model(demo_records()[:3])
