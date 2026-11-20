from datetime import datetime
from sqlalchemy import select,func
from fastapi import HTTPException
from .models import WashMission
from .operations_models import WasteManifest,WeighTrip,TripLoad,WasteReturn
from .field_service import require,audit
from .waste_model import estimate

EPS=0.05

def _mission(db,key):
    m=require(db,WashMission,key,True)
    if m.status!='accepted':raise HTTPException(409,'仅增益验收任务可登记废水联单')
    return m

def _sum(db,column,*where):
    return float(db.scalar(select(func.coalesce(func.sum(column),0)).where(*where)) or 0)

def _load_returned(db,load):
    return _sum(db,WasteReturn.liters,WasteReturn.trip_id==load.trip_id,WasteReturn.manifest_id==load.manifest_id)

def _trip_returns(db,trip_id):
    return _sum(db,WasteReturn.liters,WasteReturn.trip_id==trip_id)

def _trip_loaded(db,trip_id):
    return _sum(db,TripLoad.loaded_liters,TripLoad.trip_id==trip_id)

def _trip_settled(db,trip):
    """A trip is closed out when the station has received it, or when it was
    rejected and every litre it carried has been returned to the water point."""
    if trip.state=='received':return True
    if trip.state not in ['rejected','returned']:return False
    return _trip_returns(db,trip.id)+EPS>=_trip_loaded(db,trip.id)

def _load_consumed(db,load):
    """Verified capacity this load still occupies. Received loads consume their
    loaded quantity; a rejected load frees capacity only after full return."""
    if load.state=='received':return load.loaded_liters
    trip=db.get(WeighTrip,load.trip_id)
    if trip.state in ['rejected','returned'] and _load_returned(db,load)+EPS>=load.loaded_liters:return 0.0
    return load.loaded_liters

def _manifest_consumed(db,manifest):
    return round(sum(_load_consumed(db,load) for load in db.scalars(select(TripLoad).where(TripLoad.manifest_id==manifest.id)).all()),3)

def _room(db,manifest):
    """Capacity still available to load. Trucks in transit hold their full load,
    so concurrent trips can never jointly exceed the verified quantity."""
    return round(manifest.verified_liters-_manifest_consumed(db,manifest),3)

def _manifest_closed(db,manifest):
    """The manifest is collected only when every litre of its verified quantity
    has been loaded and every carrying trip has been received, or rejected and
    returned; partial loading stays open for another trip."""
    if manifest.verified_liters<=0:return False
    loads=db.scalars(select(TripLoad).where(TripLoad.manifest_id==manifest.id)).all()
    if not loads:return False
    if not all(_trip_settled(db,db.get(WeighTrip,load.trip_id)) for load in loads):return False
    return _manifest_consumed(db,manifest)+EPS>=manifest.verified_liters

def manifest_gaps(db,manifest):
    """What keeps a manifest from being collected: water still to be loaded
    (including returned rejections that must be reloaded) and rejected water
    not yet returned to the water point."""
    outstanding=0.0
    for load in db.scalars(select(TripLoad).where(TripLoad.manifest_id==manifest.id)).all():
        trip=db.get(WeighTrip,load.trip_id)
        if trip.state in ['rejected','returned'] and not _trip_settled(db,trip):
            outstanding+=max(0.0,load.loaded_liters-_load_returned(db,load))
    remaining=max(0.0,manifest.verified_liters-_manifest_consumed(db,manifest))
    return {'outstanding_return_liters':round(outstanding,3),'remaining_load_liters':round(remaining,3)}

def _refresh_manifest_state(db,manifest):
    if manifest.state=='declared':return
    if _manifest_closed(db,manifest):manifest.state='closed'
    elif manifest.received_liters>0:manifest.state='receiving'
    elif manifest.state=='receiving':manifest.state='verified'

def create(db,b,u):
    m=_mission(db,b.mission_id)
    if db.scalar(select(WasteManifest).where(WasteManifest.manifest_no==b.manifest_no)):raise HTTPException(409,'联单编号已存在')
    declared=b.declared_liters if b.declared_liters is not None else m.water_liters
    if _sum(db,WasteManifest.declared_liters,WasteManifest.mission_id==m.id)+declared>m.water_liters+1e-6:raise HTTPException(409,'该任务各联单申报水量合计不得超过任务用水')
    row=WasteManifest(mission_id=m.id,manifest_no=b.manifest_no,station=b.station,declared_liters=declared,created_by=u.email)
    db.add(row);audit(db,u,f'登记废水联单 {b.manifest_no} 申报{declared}L 去向{b.station}');db.commit();return row

def verify(db,key,b,u):
    d=require(db,WasteManifest,key,True)
    if d.state!='declared':raise HTTPException(409,'仅待核验联单可核定，核定后数量冻结')
    if db.scalar(select(TripLoad).where(TripLoad.manifest_id==d.id)):raise HTTPException(409,'已有装车记录，联单核验量不得再变更')
    if b.verified_liters>d.declared_liters+1e-6:raise HTTPException(409,'核验量不得超过联单申报水量')
    m=require(db,WashMission,d.mission_id,True)
    if _sum(db,WasteManifest.verified_liters,WasteManifest.mission_id==m.id)+b.verified_liters>m.water_liters+1e-6:raise HTTPException(409,'该任务各联单核验量合计不得超过任务用水')
    d.verified_liters=b.verified_liters;d.verified_by=u.email;d.state='verified'
    audit(db,u,f'核验废水联单{key} 核定{b.verified_liters}L');db.commit();return d

def create_trip(db,b,u):
    if db.scalar(select(WeighTrip).where(WeighTrip.trip_code==b.trip_code)):raise HTTPException(409,'车次编号已存在')
    row=WeighTrip(**b.model_dump(),created_by=u.email)
    db.add(row);audit(db,u,f'建立废水车次 {b.trip_code} 车辆{b.vehicle_code}');db.commit();return row

def _guard_vehicle(db,vehicle_code):
    """A truck cannot start a new load while earlier rejected water is still
    held off the water point."""
    prior=db.scalars(select(WeighTrip).where(WeighTrip.vehicle_code==vehicle_code,WeighTrip.state.in_(['rejected','returned']))).all()
    for old in prior:
        if not _trip_settled(db,old):raise HTTPException(409,f'该车上一趟（{old.trip_code}）拒收水未清退回水点，暂不可重装')

def load(db,key,b,u):
    trip=require(db,WeighTrip,key,True)
    if trip.state!='loading':raise HTTPException(409,'车次已过磅或拒收，不可再装车')
    _guard_vehicle(db,trip.vehicle_code)
    manifest=require(db,WasteManifest,b.manifest_id,True)
    if manifest.state=='declared':raise HTTPException(409,'联单尚未核验，不可装车')
    if manifest.state=='closed':raise HTTPException(409,'联单核验量已全部收齐，不可再装车')
    m=db.get(WashMission,manifest.mission_id)
    if not m or m.status!='accepted':raise HTTPException(409,'联单对应任务未验收')
    if db.scalar(select(TripLoad).where(TripLoad.trip_id==trip.id,TripLoad.manifest_id==manifest.id)):raise HTTPException(409,'同车次同一联单已装车，请合并为一次')
    room=_room(db,manifest)
    if b.loaded_liters>room+1e-6:raise HTTPException(409,f'装车量超出联单核验余量{round(max(0.0,room),1)}L')
    row=TripLoad(trip_id=trip.id,manifest_id=manifest.id,loaded_liters=b.loaded_liters)
    db.add(row);audit(db,u,f'车次{trip.trip_code}装车 联单{manifest.manifest_no} {b.loaded_liters}L');db.commit();return row

def weigh(db,key,b,u):
    trip=require(db,WeighTrip,key,True)
    existing=db.scalar(select(WeighTrip).where(WeighTrip.weigh_ticket==b.weigh_ticket))
    if existing:
        # A retry of the same weigh ticket never records a second receipt.
        if existing.id==trip.id and trip.state in ['weighed','received','rejected','returned']:return existing
        raise HTTPException(409,'磅单号已登记在其他车次，不能重复记收')
    if trip.state!='loading':raise HTTPException(409,'仅待过磅车次可登记磅单')
    loads=db.scalars(select(TripLoad).where(TripLoad.trip_id==trip.id)).all()
    if not loads:raise HTTPException(409,'车次尚未装车，不能过磅')
    if b.gross_kg<=b.tare_kg:raise HTTPException(409,'整车毛重必须大于皮重')
    loaded=round(sum(load.loaded_liters for load in loads),1)
    fields={'vehicle_code':trip.vehicle_code,**b.model_dump(exclude={'weigh_ticket','measured_net_liters'})}
    predicted,evidence=estimate(fields)
    evidence['gross_minus_tare_l']=round(b.gross_kg-b.tare_kg,1);evidence['loaded_liters']=loaded
    if predicted>loaded+EPS:
        evidence['measured_required']=True
        evidence['reason']='；'.join(filter(None,[evidence['reason'] if evidence['measured_required'] else '',f'估算净收{predicted}L超过整车装车{loaded}L，运输途中不可能增加水量']))
    if b.measured_net_liters is not None:
        net=b.measured_net_liters
        if net>loaded+EPS:raise HTTPException(409,f'实测净收{net}L超过该车装车总量{loaded}L，请核对磅单')
        evidence['measured']=True;evidence['measured_reason']=evidence['reason']
    elif evidence['measured_required']:
        raise HTTPException(409,'该车净收水量估算误差过大或历史不足，须补实测净收水量：'+evidence['reason'])
    else:
        net=predicted;evidence['measured']=False
    trip.weigh_ticket=b.weigh_ticket;trip.gross_kg=b.gross_kg;trip.tare_kg=b.tare_kg
    trip.ambient_temp_c=b.ambient_temp_c;trip.haul_km=b.haul_km;trip.tank_capacity_l=b.tank_capacity_l
    trip.estimated_net_liters=predicted;trip.measured_net_liters=b.measured_net_liters;trip.net_liters=net
    trip.estimate_evidence=evidence;trip.weighed_by=u.email;trip.weighed_at=datetime.utcnow();trip.state='weighed'
    audit(db,u,f"车次{trip.trip_code}过磅 净收{net}L（{'实测' if b.measured_net_liters is not None else '估算'}）")
    db.commit();return trip

def _allocate(net,loads,weights,caps):
    """Split the whole-truck net received litres by each manifest's remaining
    verified balance, never allocating more than that manifest put on board."""
    total_cap=sum(caps[load.id] for load in loads)
    if net>total_cap+EPS:raise HTTPException(409,f'整车净收{net}L超过车上实装水量合计{round(total_cap,1)}L，请复核磅单或改实测')
    total_weight=sum(weights[load.id] for load in loads) or 1.0
    alloc={load.id:min(caps[load.id],net*weights[load.id]/total_weight) for load in loads}
    for _ in range(len(loads)+2):
        shortfall=round(net-sum(alloc.values()),4)
        if shortfall<=0.01:break
        open_loads=[load for load in loads if alloc[load.id]<caps[load.id]-0.01]
        if not open_loads:break
        open_weight=sum(weights[load.id] for load in open_loads) or 1.0
        for load in open_loads:
            alloc[load.id]=min(caps[load.id],alloc[load.id]+shortfall*weights[load.id]/open_weight)
    alloc={key:round(value,1) for key,value in alloc.items()}
    drift=round(net-sum(alloc.values()),1)
    if abs(drift)>=0.05:
        key=max(alloc,key=lambda k:alloc[k]);alloc[key]=round(alloc[key]+drift,1)
    return alloc

def receive(db,key,b,u):
    trip=require(db,WeighTrip,key,True)
    if trip.state!='weighed':raise HTTPException(409,'须先登记整车磅单；拒收或已签收车次不可重复记收')
    # Lock manifests in id order so concurrent trucks never deadlock on receipt.
    loads=db.scalars(select(TripLoad).where(TripLoad.trip_id==trip.id).order_by(TripLoad.manifest_id)).all()
    if not loads:raise HTTPException(409,'车次无装车联单')
    manifests={}
    for load in loads:
        if load.manifest_id not in manifests:manifests[load.manifest_id]=require(db,WasteManifest,load.manifest_id,True)
    weights={load.id:max(0.0,manifests[load.manifest_id].verified_liters-manifests[load.manifest_id].received_liters) for load in loads}
    caps={load.id:load.loaded_liters for load in loads}
    net=float(trip.net_liters)
    alloc=_allocate(net,loads,weights,caps)
    for load in loads:
        share=alloc[load.id]
        load.allocated_liters=share;load.state='received'
        man=manifests[load.manifest_id]
        man.received_liters=round(man.received_liters+share,3)
        man.received_by=b.received_by;man.receipt=b.receipt;man.received_at=datetime.utcnow()
        audit(db,u,f"车次{trip.trip_code}签收 联单{man.manifest_no}按余量分摊{share}L")
    trip.state='received';trip.received_by=b.received_by;trip.receipt=b.receipt
    for man in manifests.values():_refresh_manifest_state(db,man)
    audit(db,u,f'废水车次{trip.trip_code}接收站签收 净收{net}L');db.commit();return trip

def reject(db,key,b,u):
    trip=require(db,WeighTrip,key,True)
    if trip.state not in ['loading','weighed']:raise HTTPException(409,'仅未签收车次可拒收')
    trip.state='rejected';trip.reject_reason=b.reason
    audit(db,u,f'废水车次{trip.trip_code}整车站拒收：{b.reason}');db.commit();return trip

def return_water(db,key,b,u):
    trip=require(db,WeighTrip,key,True)
    if trip.state not in ['rejected','returned']:raise HTTPException(409,'仅拒收车次的水点清退回')
    load=db.scalar(select(TripLoad).where(TripLoad.trip_id==trip.id,TripLoad.manifest_id==b.manifest_id))
    if not load:raise HTTPException(404,'该联单不在本车次装车记录中')
    manifest=require(db,WasteManifest,b.manifest_id,True)
    outstanding=load.loaded_liters-_load_returned(db,load)
    if b.liters>outstanding+EPS:raise HTTPException(409,f'清退量超出该车次该联单待清退{round(max(0.0,outstanding),1)}L')
    if db.scalar(select(WasteReturn).where(WasteReturn.trip_id==trip.id,WasteReturn.manifest_id==manifest.id,WasteReturn.receipt==b.receipt)):raise HTTPException(409,'该清退凭证已登记，不可重复')
    row=WasteReturn(manifest_id=manifest.id,trip_id=trip.id,liters=b.liters,destination=b.destination,received_by=b.received_by,receipt=b.receipt,reason=b.reason,created_by=u.email)
    db.add(row);db.flush()
    if _trip_returns(db,trip.id)+EPS>=_trip_loaded(db,trip.id):trip.state='returned'
    _refresh_manifest_state(db,manifest)
    audit(db,u,f'车次{trip.trip_code}拒收水清退 {b.liters}L 至{b.destination}');db.commit();return row
