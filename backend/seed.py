# -*- coding: utf-8 -*-
"""初始化数据库并写入演示账号 / 演示订单。

用法：python -m backend.seed
重复执行会跳过已存在的账号；加 --reset 可清空 data/ 重建。
"""
import argparse
import os
import shutil
import sys
from datetime import date, timedelta

# 允许直接 python backend/seed.py 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, models, services  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.security import hash_password  # noqa: E402

# 1x1 PNG，用作演示照片占位
_DUMMY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f5f0000000049454e44ae42"
    "6082"
)

USERS = [
    ("admin", "admin123", "系统管理员", models.ROLE_ADMIN),
    ("reception", "recep123", "前台·王收件", models.ROLE_RECEPTION),
    ("handler", "handle123", "经办·李递交", models.ROLE_HANDLER),
    ("handler2", "handle123", "经办·赵外事", models.ROLE_HANDLER),
    ("viewer", "view123", "统计员·只读", models.ROLE_VIEWER),
]


def reset_data():
    if os.path.isdir(config.DATA_DIR):
        shutil.rmtree(config.DATA_DIR)
    os.makedirs(config.PHOTO_DIR, exist_ok=True)
    os.makedirs(config.RECEIPT_DIR, exist_ok=True)


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            for username, pwd, name, role in USERS:
                db.add(models.User(
                    username=username, password_hash=hash_password(pwd),
                    display_name=name, role=role,
                ))
            db.commit()
            print("已创建演示账号")
        else:
            print("演示账号已存在，跳过")

        if db.query(models.Order).count() > 0:
            print("演示订单已存在，跳过")
            return

        import secrets
        reception = db.query(models.User).filter_by(username="reception").one()
        handler = db.query(models.User).filter_by(username="handler").one()

        customer = models.Customer(name="张出国", phone="13800001111", id_number="110101199001011234")
        db.add(customer)
        db.flush()
        order = models.Order(
            order_no=f"V{date.today().strftime('%Y%m%d')}-{customer.id:04d}",
            customer=customer, destination="某国驻华使馆签证中心",
            visa_type="旅游签", receipt_token=secrets.token_urlsafe(18),
            created_by=reception.id,
        )
        db.add(order)
        db.flush()
        docs = [("护照", "普通护照 E12345678"), ("身份证", "二代居民身份证"),
                ("户口本", "全本复印件原件"), ("在职证明", "公司抬头纸原件")]
        batch = f"RCV-{order.id}-seed"
        for seq, (dtype, dname) in enumerate(docs, start=1):
            mat = models.Material(order=order, seq_no=seq, doc_type=dtype, doc_name=dname,
                                  photo_path="", photo_sha256="")
            db.add(mat)
            db.flush()
            rel, digest = services.save_photo(_DUMMY_PNG, "demo.png", customer.id, order.id, mat.id)
            mat.photo_path, mat.photo_sha256 = rel, digest
            db.add(models.HandoverEvent(
                order=order, material=mat, event_type=models.EV_RECEIVE, batch_no=batch,
                actor_user_id=reception.id, from_party=f"客户 {customer.name}", to_party="旅行社",
                counterparty_name=customer.name, counterparty_id=customer.id_number,
                note=f"演示收件 件号 {mat.item_no}",
            ))
        db.add(models.ProxyAuthorization(
            order=order, proxy_name="王代领", proxy_id_no="110101198505056789",
            scope_material_ids="", valid_from=date.today(),
            valid_until=date.today() + timedelta(days=30),
            note="演示：有效代领授权（全部材料）", created_by=reception.id,
        ))
        db.add(models.ProxyAuthorization(
            order=order, proxy_name="孙过期", proxy_id_no="110101198001010000",
            scope_material_ids="", valid_from=date.today() - timedelta(days=60),
            valid_until=date.today() - timedelta(days=1),
            note="演示：已过期授权", created_by=reception.id,
        ))
        services.send_sms(
            db, customer, order, "received",
            f"【寰宇签证(模拟)】{customer.name}您好，您的 {len(docs)} 件签证原件已收件，"
            f"订单号 {order.order_no}。",
        )
        db.commit()
        print("已创建演示订单（4 件材料，含 1 个有效代领授权与 1 个过期授权）")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="清空 data/ 后重建")
    args = parser.parse_args()
    if args.reset:
        reset_data()
        print("已清空 data/")
    seed()


if __name__ == "__main__":
    main()
