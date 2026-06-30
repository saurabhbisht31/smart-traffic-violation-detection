# test.py
from sqlalchemy import create_engine, text
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

engine = create_engine(f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}")
try:
    with engine.connect() as conn:
        rows = conn.execute(text("SHOW TABLES;"))
        print("Connected. Tables:")
        for r in rows:
            print(r)
except Exception as e:
    print("DB connection error:", e)
