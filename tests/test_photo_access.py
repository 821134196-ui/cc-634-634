# -*- coding: utf-8 -*-
"""验证 3：证件照片仅经手岗位可访问，且不能跨客户读取。"""


def _material_ids(order):
    return [m["id"] for m in order["materials"]]


def test_viewer_role_cannot_read_id_photo(client):
    """无权限岗位（只读统计）即使拿到 material_id 也无法读取证件照片。"""
    recv = client.login("reception")
    order = client.create_order(recv)
    mid = _material_ids(order)[0]

    client.login("viewer")
    r = client.get(f"/api/materials/{mid}/photo")
    assert r.status_code == 403, "只读岗位不得访问证件照片"
    assert r.headers["content-type"].startswith("application/json")


def test_non_handling_handler_cannot_read_other_customers_photo(client):
    """同是经办岗，但从未经手该订单（=另一个客户的件），禁止跨客户读取。"""
    recv = client.login("reception")
    order_a = client.create_order(recv)
    mid_a = _material_ids(order_a)[0]

    # handler2 没有参与该订单的任何交接
    client.login("handler2")
    r = client.get(f"/api/materials/{mid_a}/photo")
    assert r.status_code == 403, "未经手的经办岗不得读取其他客户证件资料"


def test_other_customer_reception_cannot_read(client):
    """前台 B 收件的客户，前台 A 未经手 → 不能看 A 客户的照片；经手后可以。"""
    client.login("reception2")
    order_b = client.create_order(client.headers["Authorization"].split()[1])
    mid_b = _material_ids(order_b)[0]

    client.login("reception")  # reception 未经手 order_b
    r = client.get(f"/api/materials/{mid_b}/photo")
    assert r.status_code == 403

    # reception 自己收件的件可以看
    order_a = client.create_order(client.headers["Authorization"].split()[1])
    mid_a = _material_ids(order_a)[0]
    r = client.get(f"/api/materials/{mid_a}/photo")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_handling_roles_get_photo_after_touching_order(client):
    """收件岗与实际递交的经办岗可以看经手件；接手前的经办岗不行。"""
    recv = client.login("reception")
    order = client.create_order(recv)
    ids = _material_ids(order)

    # handler 尚未经手 → 403
    client.login("handler")
    r = client.get(f"/api/materials/{ids[0]}/photo")
    assert r.status_code == 403

    # handler 完成一次递交后成为经手人 → 200
    r = client.post(f"/api/orders/{order['id']}/submit",
                    json={"material_ids": [ids[0]], "counterparty_name": "窗口"})
    assert r.status_code == 200
    r = client.get(f"/api/materials/{ids[0]}/photo")
    assert r.status_code == 200 and len(r.content) > 0


def test_admin_can_access_all_photos(client):
    recv = client.login("reception")
    order = client.create_order(recv)
    mid = _material_ids(order)[0]
    client.login("admin")
    r = client.get(f"/api/materials/{mid}/photo")
    assert r.status_code == 200


def test_photo_access_denied_without_token(client):
    recv = client.login("reception")
    order = client.create_order(recv)
    mid = _material_ids(order)[0]
    client.raw_token("invalid-token-xxxx")
    r = client.get(f"/api/materials/{mid}/photo")
    assert r.status_code == 401


def test_photo_path_traversal_blocked_at_storage_layer():
    """存储层的路径拼接必须阻止穿越（防御纵深）。"""
    import os
    from backend import services
    assert services.photo_abspath("../../etc/passwd") is None
    assert services.photo_abspath("/etc/passwd") is None


def test_denied_access_is_audited(client):
    """被拒绝的证件照片访问必须留下审计记录。"""
    from backend.database import SessionLocal
    from backend import models

    recv = client.login("reception")
    order = client.create_order(recv)
    mid = _material_ids(order)[0]

    client.login("viewer")
    assert client.get(f"/api/materials/{mid}/photo").status_code == 403
    client.login("handler2")
    assert client.get(f"/api/materials/{mid}/photo").status_code == 403

    db = SessionLocal()
    try:
        denied = db.query(models.PhotoAccessLog).filter_by(allowed=False).count()
        assert denied >= 2
    finally:
        db.close()


def test_public_receipt_never_exposes_photos(client):
    """客户公开凭证视图不包含照片字段，照片 URL 也不接受 token 外的猜测访问。"""
    recv = client.login("reception")
    order = client.create_order(recv)
    token = order["receipt_token"]
    r = client.get(f"/api/public/orders/{token}")
    assert r.status_code == 200
    data = r.json()
    assert "receipt_token" not in data
    for m in data["materials"]:
        assert "has_photo" not in m
    # 公开接口拿不到照片：照片端点仍要求登录+经手权限
    mid = data["materials"][0]["id"]
    client.raw_token("not-a-real-token")
    assert client.get(f"/api/materials/{mid}/photo").status_code == 401
