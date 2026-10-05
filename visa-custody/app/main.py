from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import (
    auth,
    authorizations,
    customers,
    handovers,
    logs,
    orders,
    photos,
    public,
)

# 建表（开发/演示用；生产用迁移）
Base.metadata.create_all(bind=engine)

app = FastAPI(title="旅游签证材料原件托管与领回系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router,
    customers.router,
    orders.router,
    handovers.router,
    authorizations.router,
    photos.router,
    public.router,
    logs.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


# 前端静态资源（Vue 本地化，无需联网/构建）。
# 必须在所有 /api 路由之后挂载：StaticFiles 只匹配已存在文件，
# 且 API 路由已先行注册，因此不会拦截接口。
from pathlib import Path as _Path

FRONTEND_DIR = _Path(__file__).resolve().parent.parent / "frontend"
app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)
