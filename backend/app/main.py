"""数据服务编排发布平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.services.version import VersionService
from app.store import store

app = FastAPI(title="数据服务编排发布平台", version="1.0.0")
version_service = VersionService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片，并同步数据版本契约。"""
    payload = store.overview()
    contract = version_service.current_contract()
    # 看板排列当前契约的新字段清单，历史版本（含旧版本）也一并列出
    payload["数据版本契约"] = contract.get("当前契约")
    payload["版本字段清单"] = contract.get("历史版本", [])
    return payload
