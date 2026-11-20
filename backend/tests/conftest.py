import os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
DB_FILE=Path(tempfile.mkdtemp())/'test.db'
os.environ['DATABASE_URL']=f'sqlite+pysqlite:///{DB_FILE}'
os.environ['SEED_DEMO']='false'
os.environ['JWT_SECRET']='test-secret'
import pytest
from fastapi.testclient import TestClient
from src.app import app
from src.database import Base,engine,Session
from src.auth import hash_password
from src.models import User,ArrayBlock,SoilingSurvey,WashMission

@pytest.fixture(scope='session')
def client():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ['admin','planner','viewer']:
            db.add(User(email=role+'@t.test',password=hash_password('pw'),role=role))
        db.add(ArrayBlock(code='SL-T01',name='测试阵列',sector='南坡',capacity_kw=100,slope=20,area_m2=500,water_liters=1000))
        db.commit()
    with TestClient(app) as c:yield c

@pytest.fixture
def db():
    with Session() as s:yield s

def token(client,role):
    r=client.post('/auth/login',json={'email':f'{role}@t.test','password':'pw'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}

@pytest.fixture
def auth(client):
    return {role:token(client,role) for role in ['admin','planner','viewer']}

def accepted_mission(db,code='T',water=500):
    block=db.query(ArrayBlock).filter_by(code='SL-T01').one()
    survey=SoilingSurvey(code=f'SV-{code}',block_id=block.id,capacity_kw=100,slope=20,irradiance=800,module_temp=30,rain_days=10,dust=2,observed_kw=60,clean_kw=80,predicted_loss=20,recommended_water=300,state='closed')
    db.add(survey);db.flush()
    mission=WashMission(survey_id=survey.id,water_liters=water,available_liters=1000,status='accepted',post_kw=80,post_irradiance=800,normalized_kw=80,verified_gain=20)
    db.add(mission);db.commit();return mission.id
