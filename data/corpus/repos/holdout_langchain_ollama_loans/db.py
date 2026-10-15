"""Ket noi co so du lieu MySQL cua he thong cho vay."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "LOANS_DB_URL", "mysql+pymysql://svc_vay@db.example.vn:3306/khoanvay"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_session():
    """Tra ve mot phien lam viec moi."""
    return SessionLocal()
