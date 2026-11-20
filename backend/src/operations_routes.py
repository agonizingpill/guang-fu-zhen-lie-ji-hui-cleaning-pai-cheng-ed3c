from fastapi import APIRouter,Depends
from sqlalchemy import select,func
from .database import session
from .auth import current,editor,admin
from .field_service import require,audit
from .operations_models import WashCrew,WorkPermit,WasteManifest,WeighTrip,TripLoad,WasteReturn,WashSettlement
from .operations_schemas import CrewInput,CrewState,PermitInput,ManifestInput,ManifestVerify,TripInput,LoadInput,WeighInput,HandoverInput,RejectInput,ReturnInput,SettlementInput
from . import permit_service,waste_service,settlement_service
router=APIRouter()

@router.get('/crews')
def crews(u=Depends(current),db=Depends(session)):return db.scalars(select(WashCrew).order_by(WashCrew.id)).all()
@router.post('/crews')
def crew(b:CrewInput,u=Depends(admin),db=Depends(session)):
    row=WashCrew(**b.model_dump());db.add(row);audit(db,u,'登记清洗班组');db.commit();return row
@router.put('/crews/{key}')
def crew_state(key:int,b:CrewState,u=Depends(admin),db=Depends(session)):
    row=require(db,WashCrew,key,True);row.active=b.active;audit(db,u,'变更班组启用');db.commit();return row
@router.get('/permits')
def permits(u=Depends(current),db=Depends(session)):return db.scalars(select(WorkPermit).order_by(WorkPermit.id.desc())).all()
@router.post('/permits')
def permit(b:PermitInput,u=Depends(editor),db=Depends(session)):return permit_service.plan(db,b,u)
@router.post('/permits/{key}/sign')
def permit_sign(key:int,u=Depends(admin),db=Depends(session)):return permit_service.sign(db,key,u)
@router.post('/permits/{key}/void')
def permit_void(key:int,u=Depends(admin),db=Depends(session)):return permit_service.void(db,key,u)
@router.put('/permits/{key}')
def revise_permit(key:int,b:PermitInput,u=Depends(editor),db=Depends(session)):return permit_service.revise(db,key,b,u)

def return_view(row):
    return {'id':row.id,'trip_id':row.trip_id,'liters':row.liters,'destination':row.destination,'received_by':row.received_by,'receipt':row.receipt,'reason':row.reason,'created_by':row.created_by,'created_at':row.created_at}
def manifest_view(db,row):
    loads=db.scalars(select(TripLoad).where(TripLoad.manifest_id==row.id).order_by(TripLoad.id)).all()
    returns=db.scalars(select(WasteReturn).where(WasteReturn.manifest_id==row.id).order_by(WasteReturn.id)).all()
    return {'id':row.id,'mission_id':row.mission_id,'manifest_no':row.manifest_no,'station':row.station,'declared_liters':row.declared_liters,
            'verified_liters':row.verified_liters,'received_liters':row.received_liters,'state':row.state,'verified_by':row.verified_by,
            'received_by':row.received_by,'receipt':row.receipt,'received_at':row.received_at,'created_by':row.created_by,
            'loaded_liters':round(sum(load.loaded_liters for load in loads),3),
            'returned_liters':round(float(db.scalar(select(func.coalesce(func.sum(WasteReturn.liters),0)).where(WasteReturn.manifest_id==row.id)) or 0),3),
            'loss_liters':round(sum(load.loaded_liters-load.allocated_liters for load in loads if load.state=='received'),3),
            'trip_ids':sorted({load.trip_id for load in loads}),'room_liters':waste_service._room(db,row),'manifest_units':waste_service._manifest_consumed(db,row),
            'returns':[return_view(item) for item in returns]}
@router.get('/waste-manifests')
def manifests(u=Depends(current),db=Depends(session)):
    return [manifest_view(db,row) for row in db.scalars(select(WasteManifest).order_by(WasteManifest.id.desc())).all()]
@router.post('/waste-manifests')
def manifest(b:ManifestInput,u=Depends(editor),db=Depends(session)):return waste_service.create(db,b,u)
@router.post('/waste-manifests/{key}/verify')
def manifest_verify(key:int,b:ManifestVerify,u=Depends(admin),db=Depends(session)):return waste_service.verify(db,key,b,u)

def trip_view(db,row):
    loads=[]
    for load in db.scalars(select(TripLoad).where(TripLoad.trip_id==row.id).order_by(TripLoad.id)).all():
        manifest=db.get(WasteManifest,load.manifest_id)
        returned=float(db.scalar(select(func.coalesce(func.sum(WasteReturn.liters),0)).where(WasteReturn.trip_id==row.id,WasteReturn.manifest_id==load.manifest_id)) or 0)
        loads.append({'id':load.id,'manifest_id':load.manifest_id,'manifest_no':manifest.manifest_no,'loaded_liters':load.loaded_liters,
                      'allocated_liters':load.allocated_liters,'returned_liters':round(returned,3),'state':load.state,
                      'returns':[return_view(item) for item in db.scalars(select(WasteReturn).where(WasteReturn.trip_id==row.id,WasteReturn.manifest_id==load.manifest_id).order_by(WasteReturn.id)).all()]})
    data={c.name:getattr(row,c.name) for c in row.__table__.columns}
    data['loads']=loads
    return data
@router.get('/waste-trips')
def trips(u=Depends(current),db=Depends(session)):
    return [trip_view(db,row) for row in db.scalars(select(WeighTrip).order_by(WeighTrip.id.desc())).all()]
@router.post('/waste-trips')
def trip(b:TripInput,u=Depends(editor),db=Depends(session)):return waste_service.create_trip(db,b,u)
@router.post('/waste-trips/{key}/loads')
def load(key:int,b:LoadInput,u=Depends(editor),db=Depends(session)):return waste_service.load(db,key,b,u)
@router.post('/waste-trips/{key}/weigh')
def weigh(key:int,b:WeighInput,u=Depends(editor),db=Depends(session)):return waste_service.weigh(db,key,b,u)
@router.post('/waste-trips/{key}/receive')
def receive(key:int,b:HandoverInput,u=Depends(editor),db=Depends(session)):return waste_service.receive(db,key,b,u)
@router.post('/waste-trips/{key}/reject')
def reject(key:int,b:RejectInput,u=Depends(editor),db=Depends(session)):return waste_service.reject(db,key,b,u)
@router.post('/waste-trips/{key}/returns')
def return_water(key:int,b:ReturnInput,u=Depends(editor),db=Depends(session)):return waste_service.return_water(db,key,b,u)

@router.get('/waste-loads')
def loads(u=Depends(current),db=Depends(session)):return db.scalars(select(TripLoad).order_by(TripLoad.id.desc())).all()
@router.get('/waste-returns')
def returns(u=Depends(current),db=Depends(session)):return db.scalars(select(WasteReturn).order_by(WasteReturn.id.desc())).all()

@router.get('/settlements')
def settlements(u=Depends(current),db=Depends(session)):return db.scalars(select(WashSettlement).order_by(WashSettlement.id.desc())).all()
@router.post('/settlements')
def prepare(b:SettlementInput,u=Depends(editor),db=Depends(session)):return settlement_service.prepare(db,b,u)
@router.post('/settlements/{key}/sign')
def sign(key:int,u=Depends(admin),db=Depends(session)):return settlement_service.sign(db,key,u)
