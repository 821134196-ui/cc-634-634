# 旅游签证材料原件托管与领回系统

旅行社收取护照等**原件**后，需要让客户随时知道**每件材料当前在哪里**；使馆分批
退件时，也**不能把整个订单标成已归还**。本系统围绕“**逐件编号、双方交接、按件
签收、只追加不改写**”来管理原件流转。

- 后端：Python + FastAPI + SQLAlchemy + SQLite
- 前端：Vue 3（本地化 vendor，**无需 npm 构建/联网**）
- 图片：本地目录存放（`data/photos/`）
- 使馆回执、短信：**模拟**（回执生成批次号；短信落库 + 控制台打印）
- 一条命令启动：`./run.sh`

## 快速开始

```bash
cd visa-custody
./run.sh            # 首次自动准备依赖、建库、写入演示数据并启动
# 重建演示数据：./run.sh --reset
# 指定端口：PORT=8080 ./run.sh
```

打开 <http://127.0.0.1:8000> 。若当前精简环境没有 pip/venv，`run.sh` 会自动用
`get-pip.py` 引导到用户目录，并把依赖装进项目内 `.pydeps/`，不污染系统。

### 演示账号

| 账号 | 密码 | 岗位 | 说明 |
|---|---|---|---|
| `admin` | `admin123` | 管理员 | 全部数据、全部证件照片 |
| `zhang` | `zhang123` | 经手岗位 | 负责客户：**王芳**（订单 …0001） |
| `li` | `li123` | 经手岗位 | 负责客户：**陈强**（订单 …0002），用于验证**跨客户隔离** |
| `wang` | `wang123` | 配送员 | 可办理签收，**不可查看任何证件照片** |

登录页还提供“**客户自助查询**”（无需登录，凭订单号 + 预留手机号），例如
`V20261005-0001` / `13800000001`。公开查询只展示位置与交接，**不返回任何照片**。

## 业务模型与规则

每件原件有独立状态（当前位置）：

```
received 在旅行社  →  submitted 在使馆·外部办理中
                   →  returned 已退件·待领回
                   →  delivering 配送中
                   →  signed 已签收（终态）
```

每次状态变化都由**双方交接**产生一条 `Handover` 记录：

- **收件**：逐件编号（`订单号-P01…`）+ 拍照 + 出具收件凭证（可发模拟短信）。
- **递交**：生成**模拟使馆回执号**（一个递交批次一个号），写入每件材料。
- **退件**：使馆可**只退回部分**；未选材料继续标注“在使馆·外部办理中”。
- **送达 / 改自取**：分批送达或临时改为自取，**只追加交接记录**，最初收件单不动。
- **签收**：客户/代领人**按件签收**，逐件记录签收码/签名与对方。

### 关键约束（已在代码与验证脚本中落实）

1. **缺件不会被整单归还覆盖**
   - 状态与签收都以“件”为单位；部分退件/分批配送互不影响。
   - 订单只有在**每一件都 `signed`** 时才会完成。
   - 显式“整单完成”接口在存在任何未签收材料时返回 `409`，**禁止提前完成**。
2. **代领必须有有效授权**
   - 校验：订单存在授权、**未撤销**、**在有效期内**、代领人**姓名与证件号一致**；
     任一不满足返回 `403`。授权书可登记/撤销，撤销只置状态、不删记录。
3. **证件照片最小授权 + 客户隔离**
   - 仅 `admin` 与经手岗位 `staff` 可访问照片；配送员等岗位 `403`、未登录 `401`。
   - `staff` 只能访问**本人名下客户**，跨客户读取 `403`。
   - 客户证件与代领人证件照片同规则；文件名系统生成并做路径穿越防护。
4. **交接记录 append-only**：没有修改/删除交接记录或订单的接口。

## 验证

端到端验证脚本会自建临时库、自起服务，覆盖上述全部规则（36 项断言）：

```bash
PYTHONPATH=./.pydeps python3 verify.py
```

重点验证：缺件不能整单完成 / 部分退件其余仍在外部；代领授权的无授权、身份不符、
过期、未生效、撤销均拒绝、有效放行；跨客户与无权限岗位照片访问被拒；公开查询
不泄露照片。

## 目录结构

```
visa-custody/
├── run.sh                 # 一条命令启动（依赖+建库+种子+服务）
├── requirements.txt
├── verify.py              # 端到端关键规则验证（36 项）
├── app/
│   ├── main.py            # FastAPI 入口，挂载 /api 与前端静态资源
│   ├── config.py database.py models.py security.py deps.py
│   ├── schemas.py serializers.py services.py storage.py sms.py
│   ├── seed_data.py       # 演示数据（生成占位 PNG，无需 Pillow）
│   └── routers/           # auth/customers/orders/handovers/authorizations/photos/public/logs
├── frontend/              # index.html + app.js + styles.css + vendor/vue
└── data/                  # SQLite 与本地照片（运行后生成）
```

## 主要接口

- `POST /api/auth/login`
- `GET/POST /api/customers`，`GET/POST /api/orders`
- `POST /api/orders/{id}/materials`（收件，multipart：类型+照片）
- `POST /api/orders/{id}/submit | return | deliver | self-pickup | sign`
- `POST /api/orders/{id}/complete`（缺件时 409）
- `POST /api/orders/{id}/authorizations`、`…/{aid}/revoke`、`…/{aid}/id-photo`
- `GET /api/photos/material/{mid}`、`GET /api/photos/authorization/{aid}`（严格授权）
- `POST /api/public/track`（客户凭订单号+手机号查询，无照片）
- `GET /api/sms-logs`、`GET /api/orders/{id}/receipts`（模拟短信与使馆回执）

> 说明：本项目为演示/原型，令牌为自实现的 HMAC 签名 token、口令用 PBKDF2 加盐
> 哈希；生产环境请替换为成熟鉴权方案、加 HTTPS、加数据库迁移与操作审计。
