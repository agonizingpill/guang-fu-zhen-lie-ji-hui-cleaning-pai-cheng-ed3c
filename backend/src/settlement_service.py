from datetime import datetime
from sqlalchemy import select
from fastapi import HTTPException
from .models import WashMission,SoilingSurvey,ArrayBlock
from .operations_models import WasteManifest,TripLoad,WashSettlement
from .waste_service import _manifest_closed,manifest_gaps
from .field_service import require,audit

EPS=0.05

def manifest_loss(db,manifest):
    """Loaded litres that did not arrive at the station: whole-truck net receipt
    can be below what was loaded, and that difference is transit loss."""
    total=0.0
    for load in db.scalars(select(TripLoad).where(TripLoad.manifest_id==manifest.id)).all():
        if load.state=='received':total+=max(0.0,load.loaded_liters-load.allocated_liters)
    return round(total,3)

def manifest_complete(db,manifest):
    """A manifest is settled only when every truck carrying it has been received,
    or rejected and its water cleared back to the source water point."""
    if manifest.verified_liters<=0:return False
    return _manifest_closed(db,manifest)

def reconcile(db,mission):
    """All manifests must be verified and closed out before settlement."""
    manifests=db.scalars(select(WasteManifest).where(WasteManifest.mission_id==mission.id).order_by(WasteManifest.id)).all()
    if not manifests:raise HTTPException(409,'任务须先登记并收齐废水联单')
    pending=[m.manifest_no for m in manifests if m.state=='declared']
    if pending:raise HTTPException(409,'联单未核验，不可结算：'+'、'.join(pending))
    unreturned=[];uncollected=[]
    for m in manifests:
        if manifest_complete(db,m):continue
        gaps=manifest_gaps(db,m)
        if gaps['outstanding_return_liters']>EPS:unreturned.append(f"{m.manifest_no}（{gaps['outstanding_return_liters']}L）")
        else:uncollected.append(f"{m.manifest_no}（待装{gaps['remaining_load_liters']}L）")
    if unreturned:raise HTTPException(409,'拒收水未清退回水点，不可结算：'+'、'.join(unreturned))
    if uncollected:raise HTTPException(409,'联单未收齐，不可结算：'+'、'.join(uncollected))
    return manifests

def prepare(db,b,u):
    m=require(db,WashMission,b.mission_id,True)
    if m.status!='accepted' or not m.verified_gain or m.verified_gain<=0:raise HTTPException(409,'须已验收的正收益清洗任务')
    manifests=reconcile(db,m)
    if db.scalar(select(WashSettlement).where(WashSettlement.mission_id==m.id)):raise HTTPException(409,'任务已有合同结算凭据')
    s=require(db,SoilingSurvey,m.survey_id);a=require(db,ArrayBlock,s.block_id)
    revenue=round(m.verified_gain*b.price_per_kw,2);cost=round(m.water_liters*b.cost_per_liter,2);margin=round(revenue-cost,2)
    if margin<0 and len(b.negative_reason.strip())<5:raise HTTPException(409,'负毛利须补充合同履约说明（至少5字）')
    snapshot={'mission_id':m.id,'block_code':a.code,'survey_code':s.code,'verified_gain_kw':m.verified_gain,'used_liters':m.water_liters,'accepted_at':m.accepted_at.isoformat() if m.accepted_at else None,
              'manifests':[{'id':d.id,'manifest_no':d.manifest_no,'station':d.station,'declared_liters':d.declared_liters,'verified_liters':d.verified_liters,'received_liters':d.received_liters,'loss_liters':manifest_loss(db,d),'receipt':d.receipt,'received_by':d.received_by} for d in manifests],
              'manifest_count':len(manifests),'verified_liters':round(sum(d.verified_liters for d in manifests),3),'received_liters':round(sum(d.received_liters for d in manifests),3),'loss_liters':round(sum(manifest_loss(db,d) for d in manifests),3)}
    row=WashSettlement(**b.model_dump(),revenue=revenue,water_cost=cost,margin=margin,snapshot=snapshot)
    db.add(row);audit(db,u,f'编制合同结算 任务{m.id} 毛利{margin} 联单{len(manifests)}张');db.commit();return row

def sign(db,key,u):
    row=require(db,WashSettlement,key,True)
    if row.state!='draft':raise HTTPException(409,'结算已签记，不可重复或覆盖')
    row.state='signed';row.signed_by=u.email;row.signed_at=datetime.utcnow();audit(db,u,f'合同结算{key}签结（本地凭据）');db.commit();return row
