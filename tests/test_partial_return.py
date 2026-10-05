# -*- coding: utf-8 -*-
"""验证 1：使馆只退回部分材料时，缺件保持未归还状态，整单不能提前完结。"""
from datetime import date, timedelta


def test_partial_embassy_return_keeps_missing_items_open(client):
    recv = client.login("reception")
    order = client.create_order(recv)
    oid = order["id"]
    ids = [m["id"] for m in order["materials"]]
    assert len(ids) == 3
    assert order["completed"] is False
    assert order["missing_count"] == 3

    # 经办岗接手：全部 3 件递交使馆
    h = client.login("handler")
    r = client.post(f"/api/orders/{oid}/submit", json={
        "material_ids": ids, "counterparty_name": "签证中心3号窗",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["submitted_count"] == 3
    assert all(m["status"] == "submitted" for m in d["materials"])
    assert d["completed"] is False

    # 使馆只退回其中 2 件 —— 另 1 件必须仍标明在外部办理
    returned_ids = ids[:2]
    r = client.post(f"/api/orders/{oid}/embassy-return", json={
        "material_ids": returned_ids, "counterparty_name": "签证中心退件窗",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    by_id = {m["id"]: m for m in d["materials"]}
    assert by_id[ids[0]]["status"] == "returned"
    assert by_id[ids[1]]["status"] == "returned"
    assert by_id[ids[2]]["status"] == "submitted", "未退回的件必须仍为外部办理中"
    assert "使馆/签证中心" in by_id[ids[2]]["location_text"]
    assert d["returned_count"] == 2
    assert d["submitted_count"] == 1
    assert d["missing_count"] == 3          # 还没有任何一件被客户领回
    assert d["completed"] is False, "部分退件时整单不得完结"

    # 客户领回已退的 2 件：仍缺 1 件，订单依旧不能完结
    r = client.post(f"/api/orders/{oid}/pickup", json={
        "material_ids": returned_ids, "sign_mode": "self",
        "signer_name": "测试客户", "delivery_mode": "office",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["held_count"] == 2
    assert d["missing_count"] == 1
    assert d["completed"] is False, "存在缺件时禁止整单提前完成"
    by_id = {m["id"]: m for m in d["materials"]}
    assert by_id[ids[2]]["status"] == "submitted"

    # 最后一件退回并领回后，整单才允许完结
    r = client.post(f"/api/orders/{oid}/embassy-return", json={
        "material_ids": [ids[2]], "counterparty_name": "签证中心退件窗",
    })
    assert r.status_code == 200
    r = client.post(f"/api/orders/{oid}/pickup", json={
        "material_ids": [ids[2]], "sign_mode": "self",
        "signer_name": "测试客户", "delivery_mode": "courier",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["held_count"] == 3
    assert d["missing_count"] == 0
    assert d["completed"] is True


def test_cannot_pickup_item_still_at_embassy(client):
    """尚在使馆的件不能被签收，防止借领回动作把缺件冲掉。"""
    recv = client.login("reception")
    order = client.create_order(recv)
    ids = [m["id"] for m in order["materials"]]
    client.login("handler")
    r = client.post(f"/api/orders/{order['id']}/submit",
                    json={"material_ids": [ids[2]], "counterparty_name": "窗口"})
    assert r.status_code == 200
    r = client.post(f"/api/orders/{order['id']}/pickup", json={
        "material_ids": ids, "sign_mode": "self", "signer_name": "测试客户",
    })
    assert r.status_code == 400
    order2 = client.get(f"/api/orders/{order['id']}").json()
    assert order2["completed"] is False
    assert order2["missing_count"] == 3
