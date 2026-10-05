# -*- coding: utf-8 -*-
"""pytest 夹具：每个测试使用独立临时数据库与图片目录"""
import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63600002000154a24f5f0000000049454e44ae42"
    "6082"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 1) 在导入应用前重定向数据目录
    data_dir = tmp_path / "data"
    photo_dir = data_dir / "photos"
    receipt_dir = data_dir / "receipts"
    for d in (data_dir, photo_dir, receipt_dir):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VCD_DATA_DIR", str(data_dir))
    monkeypatch.setenv("VCD_DB", str(data_dir / "test.db"))
    monkeypatch.setenv("VCD_PHOTO_DIR", str(photo_dir))
    monkeypatch.setenv("VCD_RECEIPT_DIR", str(receipt_dir))

    # 清理已导入模块缓存，确保配置生效
    for name in list(sys.modules):
        if name == "backend" or name.startswith("backend."):
            del sys.modules[name]

    from fastapi.testclient import TestClient
    from backend import models
    from backend.database import Base, SessionLocal, engine
    from backend.security import hash_password
    from backend.main import app

    Base.metadata.create_all(bind=engine)

    # 建账号
    db = SessionLocal()
    users = {
        "reception": ("前台小王", models.ROLE_RECEPTION),
        "reception2": ("前台小张", models.ROLE_RECEPTION),
        "handler": ("经办小李", models.ROLE_HANDLER),
        "handler2": ("经办小赵", models.ROLE_HANDLER),
        "viewer": ("只读统计", models.ROLE_VIEWER),
        "admin": ("管理员", models.ROLE_ADMIN),
    }
    for uname, (dname, role) in users.items():
        db.add(models.User(username=uname, password_hash=hash_password("pw123456"),
                           display_name=dname, role=role))
    db.commit()
    db.close()

    c = TestClient(app)

    def login(username):
        r = c.post("/api/auth/login", json={"username": username, "password": "pw123456"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = "Bearer " + r.json()["token"]
        return r.json()["token"]

    c.login = login

    def raw_token(token):
        c.headers["Authorization"] = "Bearer " + token

    c.raw_token = raw_token

    def create_order(token, docs=("护照|普通护照E1", "身份证|二代证", "户口本|全本")):
        raw_token(token)
        data = {
            "destination": "A国签证中心", "visa_type": "旅游签",
            "customer_name": "测试客户", "customer_phone": "13900000000",
            "customer_id_no": "110101199001011234",
        }
        files = []
        types, names = [], []
        buf = io.BytesIO(_PNG)
        for i, d in enumerate(docs):
            t, n = d.split("|", 1)
            types.append(t); names.append(n)
            files.append(("photos", (f"p{i}.png", buf.getvalue(), "image/png")))
        data["doc_types"] = types
        data["doc_names"] = names
        r = c.post("/api/orders", data=data, files=files)
        assert r.status_code == 200, r.text
        return r.json()

    c.create_order = create_order
    c.png = _PNG
    yield c
