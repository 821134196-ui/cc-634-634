# -*- coding: utf-8 -*-
"""数据库初始化与会话"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from . import config

os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs(config.PHOTO_DIR, exist_ok=True)
os.makedirs(config.RECEIPT_DIR, exist_ok=True)

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
