"""初始化并写入演示数据。

用法：python -m app.seed_data [--reset]
--reset 会删除已有数据库与照片，重新生成。
"""
import struct
import sys
import zlib
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from .config import DATA_DIR, DB_PATH, PHOTOS_DIR
from .database import Base, SessionLocal, engine
from .models import (
    Customer,
    Material,
    Order,
    STATUS_RECEIVED,
    User,
)
from .security import hash_password
from .services import (
    add_handover,
    assign_courier,
    embassy_return,
    sign_materials,
    submit_to_embassy,
)
from .models import EVENT_RECEIVE


def _png_bytes(rgb=(120, 160, 220), w=160, h=110) -> bytes:
    """生成一张纯色 PNG（无需 Pillow）。"""
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b""
    row = b"\x00" + bytes(rgb) * w
    for _ in range(h):
        raw += row
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _write_photo(name: str, rgb) -> str:
    p = PHOTOS_DIR / name
    p.write_bytes(_png_bytes(rgb))
    return name


def reset_all():
    Base.metadata.drop_all(bind=engine)
    for f in PHOTOS_DIR.glob("*"):
        if f.is_file():
            f.unlink()
    Base.metadata.create_all(bind=engine)


def seed():
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == "admin")):
            print("已存在种子数据，跳过。使用 --reset 可重建。")
            return

        admin = User(username="admin", password_hash=hash_password("admin123"),
                     role="admin", name="系统管理员")
        zhang = User(username="zhang", password_hash=hash_password("zhang123"),
                     role="staff", name="张明（前台·经手人）")
        li = User(username="li", password_hash=hash_password("li123"),
                  role="staff", name="李华（前台·经手人）")
        courier = User(username="wang", password_hash=hash_password("wang123"),
                       role="courier", name="王勇（配送员）")
        db.add_all([admin, zhang, li, courier])
        db.flush()

        c1 = Customer(name="王芳", phone="13800000001", id_doc_no="110101199001011234",
                      owner_staff_id=zhang.id)
        c2 = Customer(name="陈强", phone="13800000002", id_doc_no="310101199203034567",
                      owner_staff_id=li.id)
        db.add_all([c1, c2])
        db.flush()

        # 订单一：法国签，演示部分退件 + 已签收 + 仍在使馆
        o1 = Order(order_no="V20261005-0001", customer_id=c1.id, embassy="法国驻华使馆",
                   status="active")
        db.add(o1)
        db.flush()
        types1 = [("护照", (180, 60, 60)), ("户口本", (60, 140, 90)),
                  ("在职证明", (70, 90, 180))]
        mats1 = []
        for i, (t, color) in enumerate(types1, start=1):
            m = Material(
                order_id=o1.id,
                material_no=f"{o1.order_no}-P{i:02d}",
                material_type=t, description=f"{t}原件",
                photo_path=_write_photo(f"seed_o1_p{i}.png", color),
                status=STATUS_RECEIVED,
            )
            db.add(m)
            db.flush()
            add_handover(db, o1, m, event_type=EVENT_RECEIVE,
                         from_party="客户本人", to_party="旅行社", actor=zhang,
                         counterparty_name=c1.name, location="旅行社前台",
                         note="收件拍照入库")
            mats1.append(m)
        db.flush()

        # 三件一起递交，使馆只退回两件，其中一件配送签收；护照仍在使馆
        submit_to_embassy(db, o1, mats1, zhang, "整批递交")
        embassy_return(db, o1, [mats1[1], mats1[2]], zhang, "使馆首批退件（部分）")
        assign_courier(db, o1, [mats1[2]], zhang, "王勇", "在职证明先行寄回")
        sign_materials(db, o1, [mats1[2]], zhang, "customer", c1.name, "",
                       "SIGN-20261005-001", "客户本人签收")

        # 订单二：日本签，刚收件，尚未递交；挂一份有效代领授权
        o2 = Order(order_no="V20261005-0002", customer_id=c2.id, embassy="日本驻华使馆",
                   status="active")
        db.add(o2)
        db.flush()
        types2 = [("护照", (150, 70, 160)), ("身份证", (170, 130, 60))]
        for i, (t, color) in enumerate(types2, start=1):
            m = Material(
                order_id=o2.id,
                material_no=f"{o2.order_no}-P{i:02d}",
                material_type=t, description=f"{t}原件",
                photo_path=_write_photo(f"seed_o2_p{i}.png", color),
                status=STATUS_RECEIVED,
            )
            db.add(m)
            db.flush()
            add_handover(db, o2, m, event_type=EVENT_RECEIVE,
                         from_party="客户本人", to_party="旅行社", actor=li,
                         counterparty_name=c2.name, location="旅行社前台",
                         note="收件拍照入库")

        from .models import Authorization
        now = datetime.utcnow()
        db.add(Authorization(
            order_id=o2.id, agent_name="赵敏", agent_id_no="440301198807077890",
            id_doc_photo_path=_write_photo("seed_agent.png", (110, 110, 110)),
            status="active",
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=30),
            created_by=li.id,
        ))

        db.commit()
        print("种子数据完成：")
        print("  管理员   admin / admin123")
        print("  经手人   zhang / zhang123  （负责客户：王芳）")
        print("  经手人   li / li123       （负责客户：陈强，用于跨客户隔离验证）")
        print("  配送员   wang / wang123  （不可查看证件照片）")
        print("  订单 V20261005-0001：护照仍在使馆 / 户口本已退件待领 / 在职证明已签收")
        print("  订单 V20261005-0002：两件已收件；代领授权人 赵敏 440301198807077890")
    finally:
        db.close()


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    if "--reset" in sys.argv:
        reset_all()
    seed()
