import pytest
from conftest import accepted_mission

def manifest(client,auth,mission,no,verified,declared=None):
    r=client.post('/waste-manifests',headers=auth['planner'],json={'mission_id':mission,'manifest_no':no,'station':'北岭接收站','declared_liters':declared or verified})
    assert r.status_code==200,r.text
    row=r.json()
    if verified is not None:
        r=client.post(f"/waste-manifests/{row['id']}/verify",headers=auth['admin'],json={'verified_liters':verified})
        assert r.status_code==200,r.text
        row=r.json()
    return row

def trip(client,auth,code='T-1',vehicle='甘A·W2316'):
    r=client.post('/waste-trips',headers=auth['planner'],json={'trip_code':code,'vehicle_code':vehicle,'station':'北岭接收站'})
    assert r.status_code==200,r.text
    return r.json()

def weigh(client,auth,t,**over):
    body={'weigh_ticket':over.pop('ticket',f"P-{t['trip_code']}"),'gross_kg':9500,'tare_kg':6500,'ambient_temp_c':22,'haul_km':20,'tank_capacity_l':4000}
    body.update(over)
    return client.post(f"/waste-trips/{t['id']}/weigh",headers=auth['planner'],json=body)

def receive(client,auth,t,who='接收站 赵工'):
    return client.post(f"/waste-trips/{t['id']}/receive",headers=auth['planner'],json={'received_by':who,'receipt':'接收站签收单 WW-001 实收核对'})

def test_manifest_verified_and_load_respects_verified_balance(client,auth,db):
    mission=accepted_mission(db,'A')
    m=manifest(client,auth,mission,'WW-A1',300)
    t=trip(client,auth,'TA-1','甘A·W2301')
    over=client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':301})
    assert over.status_code==409 and '余量' in over.text
    ok=client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':300})
    assert ok.status_code==200,ok.text

def test_concurrent_loads_cannot_exceed_verified_quantity(client,auth,db):
    mission=accepted_mission(db,'B')
    m=manifest(client,auth,mission,'WW-B1',400)
    t1=trip(client,auth,'TB-1','甘A·W2302');t2=trip(client,auth,'TB-2','甘A·W2303')
    assert client.post(f"/waste-trips/{t1['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':250}).status_code==200
    r=client.post(f"/waste-trips/{t2['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':200})
    assert r.status_code==409 and '余量' in r.text

def test_same_manifest_multiple_trips_and_proportional_split(client,auth,db):
    mission=accepted_mission(db,'C')
    m1=manifest(client,auth,mission,'WW-C1',400)
    m2=manifest(client,auth,mission,'WW-C2',100)
    t=trip(client,auth,'TC-1','甘A·W2304')
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m1['id'],'loaded_liters':300})
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m2['id'],'loaded_liters':100})
    r=weigh(client,auth,t,measured_net_liters=380)
    assert r.status_code==200,r.text
    assert r.json()['net_liters']==380
    r=receive(client,auth,t)
    assert r.status_code==200,r.text
    manifests={x['manifest_no']:x for x in client.get('/waste-manifests',headers=auth['viewer']).json()}
    # Split by each manifest's remaining balance (400 vs 100); C1 cannot receive
    # more than the 300 L it loaded, so the excess flows to C2.
    assert manifests['WW-C1']['received_liters']==300.0
    assert manifests['WW-C2']['received_liters']==80.0

def test_weigh_retry_is_idempotent(client,auth,db):
    mission=accepted_mission(db,'D')
    m=manifest(client,auth,mission,'WW-D1',200)
    t=trip(client,auth,'TD-1','甘A·W2305')
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':200})
    first=weigh(client,auth,t,ticket='P-777',measured_net_liters=190)
    assert first.status_code==200,first.text
    again=weigh(client,auth,t,ticket='P-777',measured_net_liters=190)
    assert again.status_code==200
    assert again.json()['id']==t['id'] and again.json()['net_liters']==190
    assert receive(client,auth,t).status_code==200
    replay=weigh(client,auth,t,ticket='P-777',measured_net_liters=190)
    assert replay.status_code==200 and replay.json()['state']=='received'
    got=client.get('/waste-manifests',headers=auth['viewer']).json()
    assert [x['received_liters'] for x in got if x['manifest_no']=='WW-D1']==[190.0]

def test_estimate_requires_measurement_for_short_history_vehicle(client,auth,db):
    mission=accepted_mission(db,'E')
    m=manifest(client,auth,mission,'WW-E1',200)
    t=trip(client,auth,'TE-1',vehicle='甘A·W2307')
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':200})
    r=weigh(client,auth,t)
    assert r.status_code==409 and '实测' in r.text
    ok=weigh(client,auth,t,measured_net_liters=195)
    assert ok.status_code==200 and ok.json()['net_liters']==195

def test_rejected_trip_must_be_returned_before_reload_and_settlement(client,auth,db):
    mission=accepted_mission(db,'F')
    m=manifest(client,auth,mission,'WW-F1',200)
    t=trip(client,auth,'TF-1','甘A·W2308')
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':200})
    assert weigh(client,auth,t,measured_net_liters=190).status_code==200
    r=client.post(f"/waste-trips/{t['id']}/reject",headers=auth['planner'],json={'reason':'接收站检测悬浮物超标拒收'})
    assert r.status_code==200
    t_blocked=trip(client,auth,'TF-2','甘A·W2308')
    r=client.post(f"/waste-trips/{t_blocked['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':100})
    assert r.status_code==409 and '未清退' in r.text
    r=client.post('/settlements',headers=auth['planner'],json={'mission_id':mission,'price_per_kw':80,'cost_per_liter':0.3})
    assert r.status_code==409 and '未清退' in r.text
    ret=client.post(f"/waste-trips/{t['id']}/returns",headers=auth['planner'],json={'manifest_id':m['id'],'liters':200,'destination':'西坡蓄水池','received_by':'水点 李工','receipt':'水点回执 WP-01，清退核对','reason':'接收站拒收，整趟退回原水点'})
    assert ret.status_code==200,ret.text
    ret_again=client.post(f"/waste-trips/{t['id']}/returns",headers=auth['planner'],json={'manifest_id':m['id'],'liters':200,'destination':'西坡蓄水池','received_by':'水点 李工','receipt':'水点回执 WP-01，清退核对','reason':'接收站拒收，整趟退回原水点'})
    assert ret_again.status_code==409
    # Cleared back to the water point, so the 200 L may be reloaded; until it is,
    # the manifest is not collected and settlement is blocked.
    r=client.post('/settlements',headers=auth['planner'],json={'mission_id':mission,'price_per_kw':80,'cost_per_liter':0.3})
    assert r.status_code==409 and '未收齐' in r.text
    t2=trip(client,auth,'TF-3','甘A·W2308')
    assert client.post(f"/waste-trips/{t2['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':200}).status_code==200
    assert weigh(client,auth,t2,measured_net_liters=190).status_code==200
    assert receive(client,auth,t2).status_code==200
    r=client.post('/settlements',headers=auth['planner'],json={'mission_id':mission,'price_per_kw':80,'cost_per_liter':0.3})
    assert r.status_code==200,r.text
    assert r.json()['snapshot']['manifest_count']==1

def test_settlement_blocked_until_all_manifests_collected(client,auth,db):
    mission=accepted_mission(db,'G')
    m1=manifest(client,auth,mission,'WW-G1',300)
    m2=manifest(client,auth,mission,'WW-G2',150)
    t=trip(client,auth,'TG-1','甘A·W2309')
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m1['id'],'loaded_liters':300})
    weigh(client,auth,t,measured_net_liters=290);receive(client,auth,t)
    r=client.post('/settlements',headers=auth['planner'],json={'mission_id':mission,'price_per_kw':80,'cost_per_liter':0.3})
    assert r.status_code==409 and 'WW-G2' in r.text
    t2=trip(client,auth,'TG-2','甘A·W2310')
    client.post(f"/waste-trips/{t2['id']}/loads",headers=auth['planner'],json={'manifest_id':m2['id'],'loaded_liters':150})
    weigh(client,auth,t2,measured_net_liters=150);receive(client,auth,t2)
    r=client.post('/settlements',headers=auth['planner'],json={'mission_id':mission,'price_per_kw':80,'cost_per_liter':0.3})
    assert r.status_code==200,r.text

def test_manifest_declared_cannot_load(client,auth,db):
    mission=accepted_mission(db,'H')
    m=manifest(client,auth,mission,'WW-H1',None)
    t=trip(client,auth,'TH-1','甘A·W2311')
    r=client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':100})
    assert r.status_code==409 and '核验' in r.text

def test_viewer_cannot_record(client,auth,db):
    mission=accepted_mission(db,'I')
    r=client.post('/waste-manifests',headers=auth['viewer'],json={'mission_id':mission,'manifest_no':'WW-I1','station':'北岭接收站'})
    assert r.status_code==403

def test_same_trip_cannot_load_same_manifest_twice(client,auth,db):
    mission=accepted_mission(db,'J')
    m=manifest(client,auth,mission,'WW-J1',500)
    t=trip(client,auth,'TJ-1','甘A·W2312')
    assert client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':200}).status_code==200
    again=client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':100})
    assert again.status_code==409 and '已装车' in again.text
    # Remaining verified balance is still loadable by another trip.
    t2=trip(client,auth,'TJ-2','甘A·W2313')
    assert client.post(f"/waste-trips/{t2['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':300}).status_code==200
    blocked=client.post(f"/waste-trips/{t2['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':10})
    assert blocked.status_code==409

def test_measured_net_cannot_exceed_loaded_and_partial_manifest_stays_open(client,auth,db):
    mission=accepted_mission(db,'K')
    m=manifest(client,auth,mission,'WW-K1',300)
    t=trip(client,auth,'TK-1','甘A·W2314')
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':100})
    r=weigh(client,auth,t,measured_net_liters=150)
    assert r.status_code==409 and '装车总量' in r.text
    assert weigh(client,auth,t,measured_net_liters=95).status_code==200
    assert receive(client,auth,t).status_code==200
    got={x['manifest_no']:x for x in client.get('/waste-manifests',headers=auth['viewer']).json()}
    assert got['WW-K1']['state']=='receiving'
    assert got['WW-K1']['room_liters']==200
    r=client.post('/settlements',headers=auth['planner'],json={'mission_id':mission,'price_per_kw':80,'cost_per_liter':0.3})
    assert r.status_code==409 and '待装200.0L' in r.text

def test_estimate_within_history_and_threshold_used_without_measurement(client,auth,db):
    mission=accepted_mission(db,'L',water=4000)
    m=manifest(client,auth,mission,'WW-L1',4000)
    t=trip(client,auth,'TL-1','甘A·W2302')
    client.post(f"/waste-trips/{t['id']}/loads",headers=auth['planner'],json={'manifest_id':m['id'],'loaded_liters':4000})
    r=weigh(client,auth,t)
    assert r.status_code==200,r.text
    body=r.json()
    assert body['measured_net_liters'] is None
    assert body['estimate_evidence']['measured'] is False
    assert body['net_liters']==body['estimated_net_liters']>0
    assert body['estimate_evidence']['holdout_mape_pct']<8
