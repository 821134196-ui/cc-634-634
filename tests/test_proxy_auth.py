# -*- coding: utf-8 -*-
"""验证 2：代领必须持有有效授权（存在/未撤销/在有效期/人证一致/范围覆盖）。"""
from datetime import date, timedelta


def _auth(client, oid, name="王代领", id_no="110101198505056789",
          valid_from=None, valid_until=None, scope=None):
    today = date.today()
    body = {
        "proxy_name": name, "proxy_id_no": id_no,
        "valid_from": str(valid_from or today),
        "valid_until": str(valid_until or (today + timedelta(days=30))),
        "scope_material_ids": scope or [],
    }
    r = client.post(f"/api/orders/{oid}/proxy-auths", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_proxy_pickup_requires_authorization(client):
    client.login("reception")
    order = client.create_order(client.headers["Authorization"].split()[1])
    ids = [m["id"] for m in order["materials"]]
    client.login("handler")

    # 无授权直接代领 → 403
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "proxy",
        "signer_name": "王代领", "signer_id_no": "110101198505056789",
        "proxy_auth_id": None,
    })
    assert r.status_code == 403
    assert "授权" in r.json()["detail"]


def test_proxy_pickup_with_valid_auth_succeeds(client):
    recv = client.login("reception")
    order = client.create_order(recv)
    ids = [m["id"] for m in order["materials"]]
    auth = _auth(client, order["id"])
    client.login("handler")
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "proxy",
        "signer_name": "王代领", "signer_id_no": "110101198505056789",
        "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["held_count"] == 3 and d["completed"] is True
    # 交接记录须标明代领签收
    ev = [e for e in d["events"] if e["event_type"] == "pickup"]
    assert all(e["sign_mode"] == "proxy" for e in ev)


def test_expired_authorization_rejected(client):
    client.login("reception")
    order = client.create_order(client.headers["Authorization"].split()[1])
    ids = [m["id"] for m in order["materials"]]
    today = date.today()
    auth = _auth(client, order["id"],
                 valid_from=today - timedelta(days=60),
                 valid_until=today - timedelta(days=1))
    client.login("handler")
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "proxy",
        "signer_name": "王代领", "signer_id_no": "110101198505056789",
        "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 403 and "有效期" in r.json()["detail"]


def test_revoked_authorization_rejected(client):
    client.login("reception")
    order = client.create_order(client.headers["Authorization"].split()[1])
    ids = [m["id"] for m in order["materials"]]
    auth = _auth(client, order["id"])
    r = client.post(f"/api/proxy-auths/{auth['id']}/revoke", json={})
    assert r.status_code == 200 and r.json()["revoked"] is True
    client.login("handler")
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "proxy",
        "signer_name": "王代领", "signer_id_no": "110101198505056789",
        "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 403 and "撤销" in r.json()["detail"]


def test_proxy_identity_must_match_authorization(client):
    client.login("reception")
    order = client.create_order(client.headers["Authorization"].split()[1])
    ids = [m["id"] for m in order["materials"]]
    auth = _auth(client, order["id"])
    client.login("handler")

    # 姓名不符
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "proxy",
        "signer_name": "李冒领", "signer_id_no": "110101198505056789",
        "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 403 and "姓名" in r.json()["detail"]

    # 证件号不符
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "proxy",
        "signer_name": "王代领", "signer_id_no": "999999999999999999",
        "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 403 and "证件号" in r.json()["detail"]


def test_authorization_scope_limits_materials(client):
    client.login("reception")
    order = client.create_order(client.headers["Authorization"].split()[1])
    ids = [m["id"] for m in order["materials"]]
    # 授权只覆盖第一件
    auth = _auth(client, order["id"], scope=[ids[0]])
    client.login("handler")
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "proxy",
        "signer_name": "王代领", "signer_id_no": "110101198505056789",
        "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 403 and "范围" in r.json()["detail"]

    # 只领授权范围内的那件 → 成功，其余仍缺件
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": [ids[0]], "sign_mode": "proxy",
        "signer_name": "王代领", "signer_id_no": "110101198505056789",
        "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 200
    d = r.json()
    assert d["held_count"] == 1 and d["missing_count"] == 2 and d["completed"] is False


def test_authorization_cannot_cross_orders(client):
    client.login("reception")
    o1 = client.create_order(client.headers["Authorization"].split()[1])
    o2 = client.create_order(client.headers["Authorization"].split()[1],
                             docs=("护照|另一本护照",))
    auth = _auth(client, o1["id"])
    client.login("handler")
    r = client.post(f"/api/orders/{o2['id']}/pickup", json={
        "material_ids": [m["id"] for m in o2["materials"]],
        "sign_mode": "proxy", "signer_name": "王代领",
        "signer_id_no": "110101198505056789", "proxy_auth_id": auth["id"],
    })
    assert r.status_code == 403
