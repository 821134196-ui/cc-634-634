"""端到端验证脚本：自起服务（临时数据库），校验关键业务与安全规则。

运行：PYTHONPATH=./.pydeps python3 verify.py
覆盖：
  1. 缺件不会被整单归还覆盖 / 禁止整单提前完成
  2. 部分退件时其余材料仍标注在外部办理
  3. 代领必须有有效授权（无/身份不符/过期/撤销拒绝，有效放行）
  4. 交接记录 append-only，最初收件单不被修改
  5. 证件照片：跨客户 403、无权限岗位 403、未登录 401，归属人/管理员 200
  6. 客户公开查询不泄露证件资料，手机号不符查不到
"""
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import zlib
from datetime import datetime, timedelta

# ---- 使用独立临时数据目录，必须在导入 app 之前设置 ----
TMP = tempfile.mkdtemp(prefix="vcd_verify_")
os.environ["VCD_DATA_DIR"] = TMP
os.environ["VCD_SECRET"] = "verify-secret"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed_data import reset_all, seed  # noqa: E402

BASE = "http://127.0.0.1"
PASS, FAIL = "✅ PASS", "❌ FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{PASS if cond else FAIL}  {name}" + (f"  —— {detail}" if detail and not cond else ""))


def http(method, path, token=None, body=None, raw=None, ctype="application/json"):
    url = BASE + path
    headers = {}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            ct = r.headers.get("content-type", "")
            if "json" in ct:
                return r.status, json.loads(raw.decode()), dict(r.headers)
            return r.status, raw, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode()), dict(e.headers)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return e.code, raw, dict(e.headers)


def login(u, p):
    st, data, _ = http("POST", "/api/auth/login", body={"username": u, "password": p})
    assert st == 200, f"登录失败 {u}: {st} {data}"
    return data["token"]


def png_bytes():
    def chunk(tag, d):
        return struct.pack(">I", len(d)) + tag + d + struct.pack(">I", zlib.crc32(tag + d) & 0xFFFFFFFF)
    row = b"\x00" + bytes((100, 140, 200)) * 8
    raw = row * 8
    ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def multipart(fields, files):
    b = uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for k, (filename, content) in files.items():
        buf.write(
            (f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; "
             f"filename=\"{filename}\"\r\nContent-Type: image/png\r\n\r\n").encode()
        )
        buf.write(content)
        buf.write(b"\r\n")
    buf.write(f"--{b}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={b}"


def receive_material(token, order_id, mtype):
    raw, ct = multipart(
        {"material_type": mtype, "description": mtype + "原件"},
        {"photo": ("p.png", png_bytes())},
    )
    st, data, _ = http("POST", f"/api/orders/{order_id}/materials", token, raw=raw, ctype=ct)
    assert st == 201, f"收件失败: {st} {data}"
    return data


def make_order_with(token, customer_id, embassy, n):
    st, o, _ = http("POST", "/api/orders", token,
                    body={"customer_id": customer_id, "embassy": embassy})
    assert st == 201, f"建单失败 {st} {o}"
    mats = [receive_material(token, o["id"], t) for t in
            (["护照", "户口本", "在职证明"][:n] if n <= 3 else [f"材料{i}" for i in range(n)])]
    return o, mats


# ---- 启动服务 ----
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(port):
    import uvicorn
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    uvicorn.Server(cfg).run()


def main():
    reset_all()
    seed()

    port = free_port()
    global BASE
    BASE = f"http://127.0.0.1:{port}"
    t = threading.Thread(target=serve, args=(port,), daemon=True)
    t.start()
    for _ in range(50):
        try:
            http("GET", "/api/health")
            break
        except Exception:
            time.sleep(0.1)

    admin = login("admin", "admin123")
    zhang = login("zhang", "zhang123")   # 负责客户：王芳(c1, 订单1)
    li = login("li", "li123")           # 负责客户：陈强(c2, 订单2)
    wang = login("wang", "wang123")     # 配送员

    print("\n========== 一、缺件 / 部分退件 / 禁止整单完成 ==========")
    # 新订单：2 件；全部递交，只退回 1 件
    o, mats = make_order_with(admin, 1, "测试使馆A", 2)
    ids = [m["id"] for m in mats]
    st, r, _ = http("POST", f"/api/orders/{o['id']}/submit", admin,
                    body={"material_ids": ids})
    check("两件均可递交使馆", st == 200, f"{st} {r}")
    st, r, _ = http("POST", f"/api/orders/{o['id']}/return", admin,
                    body={"material_ids": [ids[0]]})
    check("使馆只退回其中 1 件（部分退件）成功", st == 200, f"{st} {r}")
    st, detail, _ = http("GET", f"/api/orders/{o['id']}", admin)
    by_id = {m["id"]: m for m in detail["materials"]}
    check("已退件材料状态=returned（待领回）", by_id[ids[0]]["status"] == "returned")
    check("未退件材料仍=submitted（在使馆·外部办理中），未被整单覆盖",
          by_id[ids[1]]["status"] == "submitted",
          f"实际={by_id[ids[1]]['status']}")

    # 缺件时尝试整单完成 -> 必须拒绝
    st, r, _ = http("POST", f"/api/orders/{o['id']}/complete", admin)
    check("存在缺件时禁止整单提前完成", st == 409, f"实际状态码={st} 响应={r}")

    # 退回的 1 件本人签收；另 1 件仍在使馆，仍不可完成
    st, r, _ = http("POST", f"/api/orders/{o['id']}/sign", admin, body={
        "material_ids": [ids[0]], "receiver_kind": "customer",
        "receiver_name": "王芳", "sign": "SIGN-A1"})
    check("退回件可本人按件签收", st == 200 and r.get("signed") == 1, f"{st} {r}")
    check("部分签收后订单未被标记完成（order_completed=false）",
          st == 200 and r.get("order_completed") is False)
    st, r, _ = http("POST", f"/api/orders/{o['id']}/complete", admin)
    check("仍有 1 件在使馆时整单完成依旧被拒绝", st == 409, f"{st}")
    st, od, _ = http("GET", f"/api/orders/{o['id']}", admin)
    check("订单整体状态仍为 active（办理中）", od["order"]["status"] == "active")

    # 剩余件退回到店并签收 -> 全部到齐才允许自动完成
    st, r, _ = http("POST", f"/api/orders/{o['id']}/return", admin,
                    body={"material_ids": [ids[1]]})
    assert st == 200, r
    st, r, _ = http("POST", f"/api/orders/{o['id']}/sign", admin, body={
        "material_ids": [ids[1]], "receiver_kind": "customer",
        "receiver_name": "王芳", "sign": "SIGN-A2"})
    check("最后一件签收后订单自动完成（缺件清零）",
          st == 200 and r.get("order_completed") is True, f"{st} {r}")
    st, r, _ = http("POST", f"/api/orders/{o['id']}/complete", admin)
    check("全部签收后整单完成允许", st == 200, f"{st} {r}")

    print("\n========== 二、代领授权强制校验 ==========")
    o2, mats2 = make_order_with(admin, 1, "测试使馆B", 1)
    mid2 = mats2[0]["id"]
    http("POST", f"/api/orders/{o2['id']}/submit", admin, body={"material_ids": [mid2]})
    http("POST", f"/api/orders/{o2['id']}/return", admin, body={"material_ids": [mid2]})

    def agent_sign(name, idno, sign="AG-SIGN"):
        return http("POST", f"/api/orders/{o2['id']}/sign", admin, body={
            "material_ids": [mid2], "receiver_kind": "agent",
            "receiver_name": name, "receiver_id_no": idno, "sign": sign})

    st, r, _ = agent_sign("陌生人", "999")
    check("无任何授权时代领被拒绝", st == 403, f"{st} {r}")

    now = datetime.utcnow()
    st, r, _ = http("POST", f"/api/orders/{o2['id']}/authorizations", admin, body={
        "agent_name": "赵敏", "agent_id_no": "11010519880101001X",
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat()})
    assert st == 201, r
    st, r, _ = agent_sign("赵敏", "000000000000000000")  # 证件号不符
    check("授权存在但代领人证件号不符被拒绝", st == 403, f"{st} {r}")
    st, r, _ = agent_sign("钱七", "11010519880101001X")  # 姓名不符
    check("授权存在但代领人姓名不符被拒绝", st == 403, f"{st} {r}")

    # 过期授权（另一位代领人，避免与有效授权冲突）
    http("POST", f"/api/orders/{o2['id']}/authorizations", admin, body={
        "agent_name": "过期人", "agent_id_no": "EXPIRED-1",
        "valid_from": (now - timedelta(days=30)).isoformat(),
        "valid_until": (now - timedelta(days=1)).isoformat()})
    st, r, _ = agent_sign("过期人", "EXPIRED-1")
    check("授权已过期时代领被拒绝", st == 403, f"{st} {r}")

    # 未生效授权
    http("POST", f"/api/orders/{o2['id']}/authorizations", admin, body={
        "agent_name": "未来人", "agent_id_no": "FUTURE-1",
        "valid_from": (now + timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat()})
    st, r, _ = agent_sign("未来人", "FUTURE-1")
    check("授权尚未生效时代领被拒绝", st == 403, f"{st} {r}")

    # 撤销授权
    st, auths, _ = http("GET", f"/api/orders/{o2['id']}", admin)
    zhao = next(a for a in auths["authorizations"] if a["agent_name"] == "赵敏")
    st, r, _ = http("POST", f"/api/orders/{o2['id']}/authorizations/{zhao['id']}/revoke",
                    admin, body={"reason": "客户电话撤销"})
    check("撤销授权成功", st == 200, f"{st} {r}")
    st, r, _ = agent_sign("赵敏", "11010519880101001X")
    check("授权被撤销后代领被拒绝", st == 403, f"{st} {r}")

    # 有效授权 -> 放行（用新订单的新材料，上一材料仍 returned）
    o3, mats3 = make_order_with(admin, 1, "测试使馆C", 1)
    mid3 = mats3[0]["id"]
    http("POST", f"/api/orders/{o3['id']}/submit", admin, body={"material_ids": [mid3]})
    http("POST", f"/api/orders/{o3['id']}/return", admin, body={"material_ids": [mid3]})
    st, valid_auth, _ = http("POST", f"/api/orders/{o3['id']}/authorizations", admin, body={
        "agent_name": "孙九", "agent_id_no": "33010619900202002Y",
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat()})
    st, r, _ = http("POST", f"/api/orders/{o3['id']}/sign", admin, body={
        "material_ids": [mid3], "receiver_kind": "agent",
        "receiver_name": "孙九", "receiver_id_no": "33010619900202002Y",
        "sign": "AGENT-OK"})
    check("有效授权且身份一致时代领放行，并记录授权ID",
          st == 200 and r.get("authorization_id") == valid_auth["id"], f"{st} {r}")

    print("\n========== 三、交接记录 append-only，收件单不被改写 ==========")
    st, d2, _ = http("GET", f"/api/orders/{o2['id']}", admin)
    ho = d2["handovers"]
    first = ho[0]
    check("最早一条始终是收件(receive)记录", first["event_type"] == "receive")
    check("收件记录的对方仍为客户本人、地点为前台（未被后续操作改写）",
          first["from_party"] == "客户本人" and first["location"] == "旅行社前台")
    check("经过递交/退件后交接记录只增不减（>1 条）", len(ho) > 1, f"条数={len(ho)}")
    # 不存在修改/删除交接记录的接口
    st, _, _ = http("DELETE", f"/api/orders/{o2['id']}", admin)
    check("系统不提供删除订单/交接记录的写接口", st in (404, 405), f"状态码={st}")

    print("\n========== 四、证件照片访问隔离（岗位 + 客户归属） ==========")
    # 种子订单1属于客户“王芳”，经手人 zhang；取其一材料照片
    st, d1, _ = http("GET", "/api/orders/1", admin)
    wangfang_mat = d1["materials"][0]["id"]
    # 种子订单2属于客户“陈强”，经手人 li
    st, d_chen, _ = http("GET", "/api/orders/2", li)
    chen_mat = d_chen["materials"][0]["id"]

    st, _, hdrs = http("GET", f"/api/photos/material/{wangfang_mat}", zhang)
    check("经手人 zhang 可读取名下客户(王芳)证件照片", st == 200 and "image" in hdrs.get("content-type", ""), f"{st}")
    st, _, _ = http("GET", f"/api/photos/material/{wangfang_mat}", li)
    check("另一经手人 li 跨客户读取王芳照片被拒绝(403)", st == 403, f"实际={st}")
    st, _, _ = http("GET", f"/api/photos/material/{chen_mat}", li)
    check("li 读取本人名下客户(陈强)照片放行（证明是按客户隔离而非一律禁止）", st == 200, f"实际={st}")
    st, _, _ = http("GET", f"/api/photos/material/{wangfang_mat}", wang)
    check("配送员岗位读取证件照片被拒绝(403)", st == 403, f"实际={st}")
    st, _, _ = http("GET", f"/api/photos/material/{wangfang_mat}", admin)
    check("管理员可读取全部证件照片", st == 200, f"实际={st}")
    st, _, _ = http("GET", f"/api/photos/material/{wangfang_mat}", None)
    check("未登录读取证件照片被拒绝(401)", st == 401, f"实际={st}")

    # 代领人证件照片同样隔离
    st, da, _ = http("GET", "/api/orders/2", li)
    agent_auth = da["authorizations"][0]["id"]
    st, _, _ = http("GET", f"/api/photos/authorization/{agent_auth}", li)
    check("经手人 li 可读取本客户的代领人证件照", st == 200, f"实际={st}")
    st, _, _ = http("GET", f"/api/photos/authorization/{agent_auth}", zhang)
    check("经手人 zhang 跨客户读取代领人证件照被拒绝(403)", st == 403, f"实际={st}")
    st, _, _ = http("GET", f"/api/photos/authorization/{agent_auth}", wang)
    check("配送员读取代领人证件照被拒绝(403)", st == 403, f"实际={st}")

    print("\n========== 五、客户公开查询：可用且不泄露证件资料 ==========")
    st, r, _ = http("POST", "/api/public/track", body={"order_no": "V20261005-0001", "phone": "13800000001"})
    check("订单号+预留手机号可查询进度", st == 200 and len(r["materials"]) == 3, f"{st}")
    no_photo_leak = all("photo" not in json.dumps(m) for m in r["materials"])
    check("公开查询结果不含任何照片地址/字段", no_photo_leak)
    st, r, _ = http("POST", "/api/public/track", body={"order_no": "V20261005-0001", "phone": "13900000000"})
    check("手机号不符查询不到(404)，防止枚举订单", st == 404, f"实际={st}")

    # 配送员可执行签收但看不到照片（岗位最小权限）
    st, r, _ = http("POST", f"/api/orders/{o['id']}/sign", wang, body={
        "material_ids": [], "receiver_kind": "customer", "receiver_name": "x", "sign": "y"})
    check("配送员属于可签收岗位（空清单被业务拦截而非403）", st == 400, f"实际={st}")

    print("\n========================================")
    failed = [n for n, ok, _ in results if not ok]
    print(f"共 {len(results)} 项，通过 {len(results)-len(failed)}，失败 {len(failed)}")
    if failed:
        print("失败项：")
        for n, ok, detail in results:
            if not ok:
                print(" -", n, detail)
        sys.exit(1)
    print("🎉 全部关键规则验证通过")


if __name__ == "__main__":
    main()
