# -*- coding: utf-8 -*-
"""验证 4：交接记录只追加——分批送达/改自取只新增记录，不改写历史与最初收件单。"""


def test_handover_events_are_append_only(client):
    recv = client.login("reception")
    order = client.create_order(recv, docs=("护照|P1", "身份证|ID1"))
    oid = order["id"]
    ids = [m["id"] for m in order["materials"]]

    def snapshot():
        d = client.get(f"/api/orders/{oid}").json()
        return [(e["id"], e["event_type"], e["material_id"], e["batch_no"],
                 e["from_party"], e["to_party"], e["note"]) for e in d["events"]]

    before = snapshot()
    assert all(e[1] == "receive" for e in before)
    receive_ids = [e[0] for e in before]

    client.login("handler")
    # 先递交、退第一件，客户选择"分批送达"
    client.post(f"/api/orders/{oid}/submit",
                json={"material_ids": ids, "counterparty_name": "窗口"})
    client.post(f"/api/orders/{oid}/embassy-return",
                json={"material_ids": [ids[0]], "counterparty_name": "退件窗"})
    r = client.post(f"/api/orders/{oid}/pickup", json={
        "material_ids": [ids[0]], "sign_mode": "self", "signer_name": "测试客户",
        "delivery_mode": "courier",
    })
    assert r.status_code == 200

    after_first = snapshot()
    # 最初的收件记录原封不动
    assert [e for e in after_first if e[0] in receive_ids] == before
    # 只新增，不修改：历史条数单调增长
    assert len(after_first) == len(before) + len(ids) + 1 + 1
    assert any("分批送达" in (e[6] or "") for e in after_first if e[1] == "pickup")

    # 第二件后来改"到社自取"——再追加一条 pickup，第一件的送达记录不变
    client.post(f"/api/orders/{oid}/embassy-return",
                json={"material_ids": [ids[1]], "counterparty_name": "退件窗"})
    r = client.post(f"/api/orders/{oid}/pickup", json={
        "material_ids": [ids[1]], "sign_mode": "self", "signer_name": "测试客户",
        "delivery_mode": "office",
    })
    assert r.status_code == 200
    final = snapshot()
    assert [e for e in final if e[0] in {x[0] for x in after_first}] == after_first
    assert len(final) == len(after_first) + 2

    # 系统不存在任何修改/删除交接记录的 HTTP 接口
    openapi = client.get("/openapi.json").json()
    paths = openapi["paths"]
    mutating = [
        p for p, methods in paths.items()
        if "event" in p for m in methods if m in ("put", "patch", "delete")
    ]
    assert mutating == [], f"不应存在交接记录的修改/删除接口: {mutating}"


def test_no_order_level_complete_endpoint(client):
    """不允许存在"整单标记完成"的口子：完结只能由逐件签收推导。"""
    openapi = client.get("/openapi.json").json()
    for p in openapi["paths"]:
        assert "complete" not in p and "finish" not in p
