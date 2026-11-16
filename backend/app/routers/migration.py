"""查询结果版本迁移接口：维护迁移批次，覆盖执行迁移、重试失败、执行回滚等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.migration import MigrationService

router = APIRouter(prefix="/api/migration", tags=["版本迁移"])

service = MigrationService()

LIST_FIELDS = ["批次号", "版本号", "关联服务", "兼容性标识", "旧查询定义", "新查询定义", "新字段清单"]
STATUSES = ["待执行", "迁移中", "已完成", "部分失败", "已回滚"]


@router.get("", response_model=PageResult[dict])
def list_batches(
    keyword: str | None = Query(default=None, description="按批次号或版本号检索"),
    status: str | None = Query(default=None, description="待执行、迁移中、已完成、部分失败、已回滚"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按批次号、版本号与状态过滤迁移批次列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_batches(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_batches() -> dict[str, Any]:
    """导出版本迁移清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_batches(page=1, size=10000)
    return {"module": "migration", "total": total, "items": items}


@router.get("/{batch_id}", response_model=dict)
def get_batch(batch_id: int) -> dict:
    """读取单条迁移批次明细：旧结果快照、兼容性标识、新字段清单与迁移明细一起返回。"""
    batch = service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"迁移批次 {batch_id} 不存在或已归档")
    return batch


@router.post("", response_model=ActionResult)
def create_batch(payload: EntryPayload) -> ActionResult:
    """登记迁移批次：必须同时写入旧结果快照、兼容性标识和新字段清单，否则回滚没有依据。"""
    batch, missing = service.create_batch(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"迁移批次缺少必要内容：{'、'.join(missing)}")
    return ActionResult(ok=True, message="迁移批次已登记", entry=batch)


@router.post("/{batch_id}/run", response_model=ActionResult)
def run_batch(batch_id: int) -> ActionResult:
    """执行迁移：从旧查询定义与数据快照出发，按兼容性标识生成迁移结果数据集。"""
    batch, message = service.run_batch(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/{batch_id}/retry", response_model=ActionResult)
def retry_batch(batch_id: int, payload: EntryPayload) -> ActionResult:
    """中断后续跑：只重试失败记录，可随请求带上修正后的记录。"""
    fixes = payload.values.get("修正记录") if payload.values else None
    batch, message = service.retry_failed(batch_id, fixes if isinstance(fixes, dict) else None)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/{batch_id}/rollback", response_model=ActionResult)
def rollback_batch(batch_id: int) -> ActionResult:
    """执行回滚：迁移结果恢复为旧结果快照，原查询结果保持可读。"""
    batch, message = service.rollback(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)
