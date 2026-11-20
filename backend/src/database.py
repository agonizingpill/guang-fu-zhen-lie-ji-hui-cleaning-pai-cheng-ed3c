import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,DeclarativeBase
DATABASE_URL=os.getenv('DATABASE_URL','mysql+pymysql://solar:solar@db:3306/solar')
# MySQL needs READ COMMITTED for the lock-then-count checks; SQLite (tests) rejects it.
engine=create_engine(DATABASE_URL,pool_pre_ping=True,**({'isolation_level':'READ COMMITTED'} if not DATABASE_URL.startswith('sqlite') else {}))
Session=sessionmaker(engine,expire_on_commit=False)
class Base(DeclarativeBase):pass
def session():
    with Session() as db:yield db
