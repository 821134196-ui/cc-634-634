# -*- coding: utf-8 -*-
"""FastAPI 主应用：签证材料原件托管与领回系统"""
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import crud, models, schemas, services
from .database import Base, engine, get_db
from .security import (
    get_current_user, hash_password, hash_token, new_token,
    require_roles, verify_password,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="签证材料原件托管与领回系统", version="1.0")


def _log_photo_access(db: Session, user: models.User, material: Optional[models.Material],
                      customer: Optional[models.Customer], allowed: bool, reason: str) -> None:
    db.add(models.PhotoAccessLog(
        user_id=user.id,
        material_id=material.id if material else None,
        customer_id=customer.id if customer else None,
        allowed=allowed,
        reason=reason,
    ))


def _get_order_or_404(db: Session, order_id: int) -> models.Order:
    o = db.get(models.Order, order_id)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    return o


def _materials_or_400(db: Session, order: models.Order, ids: list[int]) -> list[models.Material]:
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未选择任何材料")
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "材料清单存在重复")
    mats = (
        db.query(models.Material)
        .filter(models.Material.order_id == order.id, models.Material.id.in_(ids))
        .all()
    )
    if len(mats) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "存在不属于本订单的材料编号")
    by_id = {m.id: m for m in mats}
    return [by_id[i] for i in ids]


# ===================== 认证 =====================
@app.post("/api/auth/login", response_model=schemas.LoginOut)
def login(body: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash) or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或口令错误")
    token = new_token()
    db.add(models.ApiToken(token_hash=hash_token(token), user_id=user.id))
    db.commit()
    return {"token": token, "user": user}


@app.get("/api/auth/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


# ===================== 员工端：订单 =====================
@app.get("/api/orders", response_model=list[schemas.OrderSummary])
def list_orders(status_filter: Optional[str] = None, q: Optional[str] = None,
                db: Session = Depends(get_db),
                user: models.User = Depends(require_roles(*models.ALL_ROLES))):
    query = db.query(models.Order)
    if q:
        like = f"%{q}%"
        query = query.join(models.Customer).filter(
            (models.Order.order_no.like(like)) | (models.Customer.name.like(like))
        )
    orders = query.order_by(models.Order.id.desc()).all()
    result = [crud.order_summary(o) for o in orders]
    if status_filter == "active":
        result = [r for r in result if not r["completed"]]
    elif status_filter == "completed":
        result = [r for r in result if r["completed"]]
    return result


@app.get("/api/orders/{order_id}", response_model=schemas.OrderDetail)
def get_order(order_id: int, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*models.ALL_ROLES))):
    return crud.order_detail(_get_order_or_404(db, order_id))


# ===================== 收件（逐件编号 + 拍照 + 收件凭证） =====================
@app.post("/api/orders", response_model=schemas.OrderDetail)
async def create_order(
    destination: str = Form(...),
    visa_type: str = Form(...),
    customer_name: str = Form(...),
    customer_phone: str = Form(...),
    customer_id_no: str = Form(...),
    doc_types: list[str] = Form(...),
    doc_names: list[str] = Form(...),
    photos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.ROLE_ADMIN, models.ROLE_RECEPTION)),
):
    """一次性收件：每件原件分别编号并拍照。照片数量必须与材料明细一一对应。"""
    if not (len(doc_types) == len(doc_names) == len(photos)) or not doc_types:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "材料类型、材料名称、照片三者数量必须一致且至少 1 件",
        )

    customer = models.Customer(
        name=customer_name.strip(), phone=customer_phone.strip(),
        id_number=customer_id_no.strip(),
    )
    db.add(customer)
    db.flush()

    order_no = f"V{datetime.now().strftime('%Y%m%d')}-{customer.id:04d}"
    order = models.Order(
        order_no=order_no,
        customer=customer,
        destination=destination.strip(),
        visa_type=visa_type.strip(),
        receipt_token=secrets.token_urlsafe(18),
        created_by=user.id,
    )
    db.add(order)
    db.flush()

    batch_no = f"RCV-{order.id}-{secrets.token_hex(3)}"
    for seq, (dtype, dname, photo) in enumerate(zip(doc_types, doc_names, photos), start=1):
        raw = await photo.read()
        if not raw:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"第 {seq} 件照片为空")
        mat = models.Material(
            order=order, seq_no=seq,
            doc_type=dtype.strip(), doc_name=dname.strip(),
            photo_path="", photo_sha256="",
            status=models.MAT_RECEIVED,
        )
        db.add(mat)
        db.flush()  # 取得 material.id 用于命名与目录
        rel_path, digest = services.save_photo(raw, photo.filename or "", customer.id, order.id, mat.id)
        mat.photo_path = rel_path
        mat.photo_sha256 = digest
        db.add(models.HandoverEvent(
            order=order, material=mat, event_type=models.EV_RECEIVE,
            batch_no=batch_no, actor_user_id=user.id,
            from_party=f"客户 {customer.name}", to_party="旅行社",
            counterparty_name=customer.name, counterparty_id=customer.id_number,
            note=f"收件拍照建档，件号 {order_no}-{seq:02d}",
        ))

    services.send_sms(
        db, customer, order, "received",
        f"【寰宇签证(模拟)】{customer.name}您好，您的 {len(doc_types)} 件签证原件已由旅行社收件，"
        f"订单号 {order_no}，可凭收件凭证查询去向。",
    )
    db.commit()
    db.refresh(order)
    return crud.order_detail(order)


# ===================== 递交使馆（可分批） =====================
@app.post("/api/orders/{order_id}/submit", response_model=schemas.OrderDetail)
def submit_to_embassy(order_id: int, body: schemas.SubmitIn,
                      db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles(
                          models.ROLE_ADMIN, models.ROLE_HANDLER))):
    order = _get_order_or_404(db, order_id)
    mats = _materials_or_400(db, order, body.material_ids)
    bad = [m.item_no for m in mats if m.status not in models.SUBMIT_FROM]
    if bad:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"以下材料当前状态不可递交（须为在库保管或退件补递）：{', '.join(bad)}",
        )
    batch_no = f"SUB-{order.id}-{secrets.token_hex(3)}"
    receipt_rel = services.generate_embassy_receipt(
        order.order_no, batch_no, [m.item_no for m in mats], body.counterparty_name,
    )
    for m in mats:
        m.status = models.MAT_SUBMITTED
        db.add(models.HandoverEvent(
            order=order, material=m, event_type=models.EV_SUBMIT, batch_no=batch_no,
            actor_user_id=user.id, from_party="旅行社", to_party=order.destination,
            counterparty_name=body.counterparty_name, note=body.note,
            embassy_receipt_path=receipt_rel,
        ))
    db.commit()
    db.refresh(order)
    return crud.order_detail(order)


# ===================== 使馆退件（只退选中的件，其余仍在外部） =====================
@app.post("/api/orders/{order_id}/embassy-return", response_model=schemas.OrderDetail)
def embassy_return(order_id: int, body: schemas.EmbassyReturnIn,
                   db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(
                       models.ROLE_ADMIN, models.ROLE_HANDLER))):
    order = _get_order_or_404(db, order_id)
    mats = _materials_or_400(db, order, body.material_ids)
    bad = [m.item_no for m in mats if m.status not in models.EMBASSY_RETURN_FROM]
    if bad:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"以下材料不在使馆/签证中心，不能登记退件：{', '.join(bad)}",
        )
    batch_no = f"RET-{order.id}-{secrets.token_hex(3)}"
    for m in mats:
        m.status = models.MAT_RETURNED
        db.add(models.HandoverEvent(
            order=order, material=m, event_type=models.EV_EMBASSY_RETURN,
            batch_no=batch_no, actor_user_id=user.id,
            from_party=order.destination, to_party="旅行社",
            counterparty_name=body.counterparty_name, note=body.note,
        ))
    services.send_sms(
        db, order.customer, order, "returned",
        f"【寰宇签证(模拟)】{order.customer.name}您好，订单 {order.order_no} 本批退回原件 "
        f"{len(mats)} 件（{', '.join(m.item_no for m in mats)}），请到社领回或等待分批送达；"
        f"其余材料仍在外部办理。",
    )
    db.commit()
    db.refresh(order)
    return crud.order_detail(order)


# ===================== 代领授权 =====================
@app.post("/api/orders/{order_id}/proxy-auths", response_model=schemas.ProxyAuthOut)
def create_proxy_auth(order_id: int, body: schemas.ProxyAuthIn,
                      db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles(
                          models.ROLE_ADMIN, models.ROLE_RECEPTION, models.ROLE_HANDLER))):
    order = _get_order_or_404(db, order_id)
    if body.valid_until < body.valid_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "授权截止日期不能早于起始日期")
    if body.scope_material_ids:
        valid_ids = {m.id for m in order.materials}
        if set(body.scope_material_ids) - valid_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "授权范围包含不属于本订单的材料")
    auth = models.ProxyAuthorization(
        order=order,
        proxy_name=body.proxy_name.strip(),
        proxy_id_no=body.proxy_id_no.strip(),
        scope_material_ids=",".join(str(i) for i in body.scope_material_ids),
        valid_from=body.valid_from, valid_until=body.valid_until,
        note=body.note, created_by=user.id,
    )
    db.add(auth)
    db.commit()
    db.refresh(auth)
    return crud.proxy_auth_out(auth)


@app.post("/api/proxy-auths/{auth_id}/revoke", response_model=schemas.ProxyAuthOut)
def revoke_proxy_auth(auth_id: int, db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles(
                          models.ROLE_ADMIN, models.ROLE_RECEPTION, models.ROLE_HANDLER))):
    auth = db.get(models.ProxyAuthorization, auth_id)
    if auth is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "授权不存在")
    if auth.revoked_at is None:
        auth.revoked_at = datetime.utcnow()
        auth.revoked_by = user.id
        db.commit()
        db.refresh(auth)
    return crud.proxy_auth_out(auth)


# ===================== 客户领回（按件签收；本人/代领） =====================
@app.post("/api/orders/{order_id}/pickup", response_model=schemas.OrderDetail)
def pickup(order_id: int, body: schemas.PickupIn,
           db: Session = Depends(get_db),
           user: models.User = Depends(require_roles(
               models.ROLE_ADMIN, models.ROLE_HANDLER))):
    order = _get_order_or_404(db, order_id)
    mats = _materials_or_400(db, order, body.material_ids)
    bad = [m.item_no for m in mats if m.status not in models.PICKUP_FROM]
    if bad:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"以下材料不在可领回状态（尚在使馆/签证中心的件不能签收）：{', '.join(bad)}",
        )
    if body.sign_mode not in ("self", "proxy"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "签收方式必须为本人或代领")

    auth: Optional[models.ProxyAuthorization] = None
    if body.sign_mode == "self":
        # 本人签收：姓名须与客户一致
        if body.signer_name.strip() != order.customer.name:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "本人签收姓名与订单客户不一致")
        signer_id = body.signer_id_no or order.customer.id_number
    else:
        # ---- 代领：必须有有效授权（存在/未撤销/在有效期/本人证件匹配/范围覆盖） ----
        if body.proxy_auth_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "代领必须登记有效授权")
        auth = (
            db.query(models.ProxyAuthorization)
            .filter(
                models.ProxyAuthorization.id == body.proxy_auth_id,
                models.ProxyAuthorization.order_id == order.id,
            )
            .one_or_none()
        )
        if auth is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "代领授权不存在或不属于本订单")
        if auth.revoked_at is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "该代领授权已撤销")
        today = date.today()
        if not (auth.valid_from <= today <= auth.valid_until):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "代领授权不在有效期内")
        if body.signer_name.strip() != auth.proxy_name:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "代领人姓名与授权书不符")
        if not body.signer_id_no or body.signer_id_no.strip() != auth.proxy_id_no:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "代领人证件号与授权书不符")
        if auth.scope_material_ids:
            allowed_ids = {int(x) for x in auth.scope_material_ids.split(",") if x.strip()}
            denied = [m.item_no for m in mats if m.id not in allowed_ids]
            if denied:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"授权范围不包含以下材料：{', '.join(denied)}",
                )
        signer_id = body.signer_id_no.strip()

    batch_no = f"PICK-{order.id}-{secrets.token_hex(3)}"
    for m in mats:
        m.status = models.MAT_HELD
        db.add(models.HandoverEvent(
            order=order, material=m, event_type=models.EV_PICKUP, batch_no=batch_no,
            actor_user_id=user.id, from_party="旅行社",
            to_party=f"{'代领人' if body.sign_mode == 'proxy' else '客户本人'} {body.signer_name}",
            counterparty_name=body.signer_name, counterparty_id=signer_id,
            sign_mode=body.sign_mode, proxy_auth_id=auth.id if auth else None,
            note=(body.note or "") + ("【分批送达】" if body.delivery_mode == "courier" else "【到社自取】"),
        ))

    db.flush()
    # ---- 缺件保护：只有全部单件都已签收领回，订单才允许完结 ----
    remaining = (
        db.query(models.Material)
        .filter(
            models.Material.order_id == order.id,
            models.Material.status != models.MAT_HELD,
        )
        .count()
    )
    if remaining == 0:
        order.completed_at = datetime.utcnow()
        services.send_sms(
            db, order.customer, order, "completed",
            f"【寰宇签证(模拟)】{order.customer.name}您好，订单 {order.order_no} 的全部原件均已签收领回，流程完结。",
        )
    else:
        services.send_sms(
            db, order.customer, order, "partial_pickup",
            f"【寰宇签证(模拟)】{order.customer.name}您好，订单 {order.order_no} 已签收 {len(mats)} 件，"
            f"尚有 {remaining} 件未领回/在外部办理，订单不会提前完结。",
        )
    db.commit()
    db.refresh(order)
    return crud.order_detail(order)


# ===================== 证件照片（仅经手岗位 + 仅本人经手的客户） =====================
@app.get("/api/materials/{material_id}/photo")
def get_material_photo(material_id: int, db: Session = Depends(get_db),
                       user: models.User = Depends(get_current_user)):
    mat = db.get(models.Material, material_id)
    if mat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "材料不存在")
    order = mat.order
    customer = order.customer

    # 1) 岗位门槛：只读/非经手岗位一律不可看证件照片
    if user.role not in models.HANDLING_ROLES:
        _log_photo_access(db, user, mat, customer, False, f"岗位 {user.role} 无权查看证件照片")
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "当前岗位无权访问证件照片")

    # 2) 跨客户隔离：仅管理员或实际经手本订单的员工可看
    if not crud.staff_handles_order(db, user, order):
        _log_photo_access(db, user, mat, customer, False, "非本订单经手人员，跨客户访问被拒")
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问其他客户的证件资料")

    abs_path = services.photo_abspath(mat.photo_path)
    if not abs_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片文件缺失")
    _log_photo_access(db, user, mat, customer, True, "经手岗位查看")
    db.commit()
    return FileResponse(abs_path, media_type="image/jpeg")


@app.get("/api/orders/{order_id}/receipt")
def get_embassy_receipt_file(order_id: int, batch_no: str,
                             db: Session = Depends(get_db),
                             user: models.User = Depends(require_roles(*models.ALL_ROLES))):
    order = _get_order_or_404(db, order_id)
    ev = (
        db.query(models.HandoverEvent)
        .filter(
            models.HandoverEvent.order_id == order.id,
            models.HandoverEvent.batch_no == batch_no,
            models.HandoverEvent.embassy_receipt_path.isnot(None),
        )
        .first()
    )
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该批次无使馆回执")
    path = services.receipt_abspath(ev.embassy_receipt_path)
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "回执文件缺失")
    return FileResponse(path, media_type="text/plain; charset=utf-8",
                        filename=f"{order.order_no}_{batch_no}_回执.txt")


# ===================== 短信模拟记录 =====================
@app.get("/api/sms", response_model=list[schemas.SmsOut])
def list_sms(db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(
                 models.ROLE_ADMIN, models.ROLE_RECEPTION, models.ROLE_HANDLER))):
    return db.query(models.SmsOutbox).order_by(models.SmsOutbox.id.desc()).limit(100).all()


# ===================== 客户凭证视图（凭收件凭证 token，不含证件照片） =====================
@app.get("/api/public/orders/{token}")
def public_order(token: str, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.receipt_token == token).one_or_none()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "收件凭证无效")
    d = crud.order_detail(order)
    # 客户凭证视图不返回证件影像，也不暴露完整证件号
    d["customer"]["id_number"] = d["customer"]["id_number"][:1] + "****" + d["customer"]["id_number"][-1:]
    for m in d["materials"]:
        m.pop("has_photo", None)
    d.pop("receipt_token", None)
    return d


# 前端静态资源（由 run.sh 构建/拷贝到 frontend_dist）
import os
from .config import BASE_DIR
_DIST = os.path.join(BASE_DIR, "frontend_dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
