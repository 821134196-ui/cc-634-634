# -*- coding: utf-8 -*-
"""模拟外部服务与文件存储

- 证件照片：本地磁盘，按 客户/订单/材料 隔离存放
- 使馆回执：生成简单文本回执文件（模拟使馆/签证中心盖章回执）
- 短信：只写入 sms_outbox 表，不真正发送
"""
import hashlib
import os
from datetime import datetime

from sqlalchemy.orm import Session

from . import config, models

_ALLOWED_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def save_photo(raw: bytes, filename: str, customer_id: int, order_id: int, material_id: int) -> tuple[str, str]:
    """保存证件照片。返回 (相对路径, sha256)。按客户隔离目录。"""
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    if ext not in _ALLOWED_EXT:
        ext = ".jpg"
    rel_dir = os.path.join(f"customer_{customer_id}", f"order_{order_id}")
    abs_dir = os.path.join(config.PHOTO_DIR, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    fname = f"mat_{material_id}{ext}"
    abs_path = os.path.join(abs_dir, fname)
    with open(abs_path, "wb") as f:
        f.write(raw)
    rel_path = os.path.join(rel_dir, fname)
    return rel_path, hashlib.sha256(raw).hexdigest()


def photo_abspath(rel_path: str) -> str | None:
    """安全拼接照片绝对路径，阻止路径穿越。"""
    if not rel_path:
        return None
    photo_root = os.path.realpath(config.PHOTO_DIR)
    abs_path = os.path.realpath(os.path.join(photo_root, rel_path))
    if not abs_path.startswith(photo_root + os.sep):
        return None
    return abs_path


def generate_embassy_receipt(order_no: str, batch_no: str, item_labels: list[str], counterparty: str) -> str:
    """模拟使馆/签证中心回执：本地文本文件，带批次与件号清单。"""
    os.makedirs(config.RECEIPT_DIR, exist_ok=True)
    fname = f"{order_no}_{batch_no}.txt"
    path = os.path.join(config.RECEIPT_DIR, fname)
    lines = [
        "===== 使/领馆（签证中心）材料接收回执（模拟） =====",
        f"订单编号：{order_no}",
        f"批次编号：{batch_no}",
        f"经办窗口：{counterparty}",
        f"出具时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "本次交接原件：",
    ]
    lines += [f"  - {label}" for label in item_labels]
    lines += ["", "（本回执为系统模拟文件，仅作交接凭证演示）"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return os.path.join("embassy", fname)


def receipt_abspath(rel_path: str) -> str | None:
    if not rel_path:
        return None
    root = os.path.realpath(config.RECEIPT_DIR)
    abs_path = os.path.realpath(os.path.join(root, rel_path))
    if not abs_path.startswith(root + os.sep):
        return None
    return abs_path


def send_sms(
    db: Session,
    customer: models.Customer,
    order: models.Order,
    kind: str,
    content: str,
    material: models.Material | None = None,
) -> models.SmsOutbox:
    """模拟短信发送：落库一条出站短信。"""
    msg = models.SmsOutbox(
        customer_id=customer.id,
        order_id=order.id,
        material_id=material.id if material else None,
        kind=kind,
        phone=customer.phone,
        content=content,
    )
    db.add(msg)
    return msg
