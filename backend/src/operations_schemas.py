from datetime import date
from pydantic import Field,field_validator
from .revisit_schemas import Inputs

class CrewInput(Inputs):
    code:str=Field(min_length=2,max_length=40)
    max_daily_minutes:int=Field(ge=1,le=1440)
class CrewState(Inputs):
    active:bool
class PermitInput(Inputs):
    mission_id:int
    crew_id:int
    work_date:date
    minutes:int=Field(ge=1,le=1440)
    wind_mps:float=Field(ge=0,le=60)
    isolation:bool

class ManifestInput(Inputs):
    mission_id:int
    manifest_no:str=Field(min_length=3,max_length=80)
    station:str=Field(min_length=2,max_length=80)
    declared_liters:float|None=Field(default=None,gt=0,le=100000)
    @field_validator('manifest_no','station')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('不能为空')
        return v.strip()
class ManifestVerify(Inputs):
    verified_liters:float=Field(gt=0,le=100000)
class TripInput(Inputs):
    trip_code:str=Field(min_length=3,max_length=50)
    vehicle_code:str=Field(min_length=3,max_length=40)
    station:str=Field(min_length=2,max_length=80)
    @field_validator('trip_code','vehicle_code','station')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('不能为空')
        return v.strip()
class LoadInput(Inputs):
    manifest_id:int
    loaded_liters:float=Field(gt=0,le=100000)
class WeighInput(Inputs):
    weigh_ticket:str=Field(min_length=3,max_length=60)
    gross_kg:float=Field(gt=0,le=60000)
    tare_kg:float=Field(gt=0,le=60000)
    ambient_temp_c:float=Field(ge=-50,le=70)
    haul_km:float=Field(ge=0,le=2000)
    tank_capacity_l:float=Field(gt=0,le=60000)
    measured_net_liters:float|None=Field(default=None,gt=0,le=60000)
    @field_validator('weigh_ticket')
    @classmethod
    def ticket(cls,v):
        if not v.strip():raise ValueError('不能为空')
        return v.strip()
class HandoverInput(Inputs):
    received_by:str=Field(min_length=2,max_length=120)
    receipt:str=Field(min_length=5,max_length=200)
    @field_validator('received_by','receipt')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('不能为空')
        return v.strip()
class RejectInput(Inputs):
    reason:str=Field(min_length=5,max_length=400)
    @field_validator('reason')
    @classmethod
    def reason_text(cls,v):
        if len(v.strip())<5:raise ValueError('拒收原因至少5字')
        return v.strip()
class ReturnInput(Inputs):
    manifest_id:int
    liters:float=Field(gt=0,le=100000)
    destination:str=Field(min_length=2,max_length=160)
    received_by:str=Field(min_length=2,max_length=120)
    receipt:str=Field(min_length=5,max_length=200)
    reason:str=Field(min_length=5,max_length=400)
    @field_validator('destination','received_by','receipt','reason')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('不能为空')
        return v.strip()
class SettlementInput(Inputs):
    mission_id:int
    price_per_kw:float=Field(gt=0,le=100000)
    cost_per_liter:float=Field(ge=0,le=10000)
    negative_reason:str=Field(default='',max_length=400)
