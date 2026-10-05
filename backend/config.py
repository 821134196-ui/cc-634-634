# -*- coding: utf-8 -*-
"""签证材料原件托管与领回系统 —— 应用配置"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据库与图片目录都放在 data/ 下，方便一条命令初始化与重置
DATA_DIR = os.environ.get("VCD_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.environ.get("VCD_DB", os.path.join(DATA_DIR, "app.db"))
PHOTO_DIR = os.environ.get("VCD_PHOTO_DIR", os.path.join(DATA_DIR, "data", "photos"))
RECEIPT_DIR = os.environ.get("VCD_RECEIPT_DIR", os.path.join(DATA_DIR, "data", "receipts"))

DATABASE_URL = f"sqlite:///{DB_PATH}"
