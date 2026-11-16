"""查询结果版本迁移：以版本记录的旧查询定义与数据快照为起点，按兼容性标识迁移结果字段。

迁移批次必须同时写入旧结果快照、兼容性标识和新字段清单，否则回滚时无法恢复原查询结果。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.store import store

MODULE = "migration"
VERSION_MODULE = "version"
STATUS_ORDER = ["待执行", "迁移中", "已完成", "部分失败", "已回滚"]
# 同一数据版本出现多个迁移边界时的仲裁口径：先按批次状态，状态相同则登记在后（id 大）者优先。
BATCH_STATUS_PRIORITY = {"已完成": 4, "部分失败": 3, "迁移中": 2, "待执行": 1, "已回滚": 0}


def resolve_batch_conflict(version_no: str) -> tuple[dict[str, Any] | None, str]:
    """仲裁同一数据版本下的多个迁移批次，返回生效批次与仲裁说明。

    被覆盖的批次保留在列表里并标注仲裁说明，迁移记录里的旧/新查询定义不动，
    版本关系始终可核对。
    """
    batches = [
        row for row in store.rows(MODULE)
        if str(row.get("版本号") or "") == version_no and row.get("status") != "已回滚"
    ]
    if not batches:
        return None, ""
    ordered = sorted(
        batches,
        key=lambda row: (BATCH_STATUS_PRIORITY.get(str(row.get("status")), 0), int(row.get("id", 0))),
        reverse=True,
    )
    winner = ordered[0]
    if len(ordered) == 1:
        winner.setdefault("仲裁说明", "")
        return winner, ""
    note = (
        f"版本 {version_no} 存在 {len(ordered)} 个迁移边界，"
        f"按批次状态与登记先后仲裁，生效批次为 {winner.get('批次号')}"
    )
    winner["仲裁说明"] = note
    for loser in ordered[1:]:
        loser["仲裁说明"] = f"被批次 {winner.get('批次号')} 仲裁覆盖"
    return winner, note


class MigrationService:
    def list_batches(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("批次号", "")) or keyword in str(row.get("版本号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, batch_id)

    def create_batch(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        version_no = str(values.get("版本号") or "").strip()
        if not version_no:
            return None, ["版本号"]
        version = next(
            (row for row in store.rows(VERSION_MODULE) if str(row.get("版本号") or "") == version_no),
            None,
        )
        if version is None:
            return None, [f"版本记录 {version_no} 不存在或已归档"]
        rows = store.rows(MODULE)
        batch_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        batch: dict[str, Any] = {"id": batch_id, "批次号": f"MIG-{batch_id:04d}"}
        batch["版本号"] = version_no
        batch["关联服务"] = version.get("关联服务")
        # 批次登记时把版本关系整体拷贝下来：之后旧结果快照与新查询定义再被更新，
        # 迁移记录里仍保留可核对的版本关系。
        batch["兼容性标识"] = values.get("兼容性标识") or version.get("兼容性标识")
        batch["旧查询定义"] = values.get("旧查询定义") or version.get("旧查询定义")
        batch["新查询定义"] = values.get("新查询定义") or version.get("新查询定义")
        batch["旧字段清单"] = deepcopy(values.get("旧字段清单") or version.get("旧字段清单") or [])
        batch["新字段清单"] = deepcopy(values.get("新字段清单") or version.get("新字段清单") or [])
        snapshot = values.get("数据快照") if values.get("数据快照") is not None else version.get("数据快照")
        batch["旧结果快照"] = deepcopy(snapshot or [])
        batch["迁移明细"] = []
        batch["迁移结果"] = []
        batch["失败记录"] = []
        batch["修正记录"] = {}
        missing = []
        if not batch["旧结果快照"]:
            missing.append("旧结果快照")
        if not str(batch["兼容性标识"] or "").strip():
            missing.append("兼容性标识")
        if not batch["新字段清单"]:
            missing.append("新字段清单")
        if missing:
            return None, missing
        batch["status"] = "待执行"
        batch["pending"] = True
        batch["abnormal"] = False
        batch["仲裁说明"] = ""
        rows.append(batch)
        resolve_batch_conflict(version_no)
        return batch, []

    @staticmethod
    def _migrate_row(row: dict[str, Any], compat: str, new_fields: list[Any]) -> dict[str, Any]:
        if any(str(key).startswith("__") for key in row):
            raise ValueError("记录携带未处理的冲突标记，需修正后重试")
        if compat == "不兼容":
            # 不兼容：结果只保留新字段清单里的字段，旧字段整体下线
            return {field: row.get(field) for field in new_fields}
        # 兼容：旧字段全部保留，新字段清单里的字段逐个补齐
        migrated = dict(row)
        for field in new_fields:
            migrated.setdefault(field, None)
        return migrated

    def _run_indices(self, batch: dict[str, Any], indices: list[int]) -> list[int]:
        """迁移指定序号的记录，返回仍失败的序号；已成功的记录不重复迁移。"""
        snapshot = batch.get("旧结果快照") or []
        fixes = batch.get("修正记录") or {}
        compat = str(batch.get("兼容性标识") or "").strip()
        new_fields = batch.get("新字段清单") or []
        details = {int(item["序号"]): item for item in batch.get("迁移明细") or []}
        failures: list[int] = []
        for index in indices:
            row = snapshot[index]
            source = fixes.get(str(index), row)
            try:
                migrated = self._migrate_row(source, compat, new_fields)
            except ValueError as exc:
                details[index] = {
                    "序号": index, "状态": "失败",
                    "旧数据": deepcopy(row), "迁移数据": None, "说明": str(exc),
                }
                failures.append(index)
            else:
                details[index] = {
                    "序号": index, "状态": "成功",
                    "旧数据": deepcopy(row), "迁移数据": migrated, "说明": "",
                }
        ordered = [details[key] for key in sorted(details)]
        batch["迁移明细"] = ordered
        batch["失败记录"] = failures
        batch["迁移结果"] = [item["迁移数据"] for item in ordered if item["状态"] == "成功"]
        batch["status"] = "部分失败" if failures else "已完成"
        batch["pending"] = bool(failures)
        batch["abnormal"] = bool(failures)
        return failures

    def run_batch(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        batch = store.find(MODULE, batch_id)
        if batch is None:
            return None, f"迁移批次 {batch_id} 不存在或已归档"
        if batch.get("status") == "已回滚":
            return None, "批次已回滚，不能重复执行迁移；如需重做请新建批次"
        snapshot = batch.get("旧结果快照") or []
        if not snapshot or not str(batch.get("兼容性标识") or "").strip() or not batch.get("新字段清单"):
            return None, "迁移批次必须同时写入旧结果快照、兼容性标识和新字段清单，否则回滚时无法恢复原查询结果"
        done = {
            int(item["序号"]) for item in batch.get("迁移明细") or [] if item.get("状态") == "成功"
        }
        todo = [index for index in range(len(snapshot)) if index not in done]
        batch["status"] = "迁移中"
        failures = self._run_indices(batch, todo)
        resolve_batch_conflict(str(batch.get("版本号") or ""))
        if failures:
            return batch, f"迁移完成但 {len(failures)} 条记录失败，已记入失败记录，可修正后重试"
        return batch, "迁移完成，结果数据集已生成"

    def retry_failed(
        self, batch_id: int, fixes: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        """中断后续跑：只重试失败记录里的序号，已成功的记录保持不动。"""
        batch = store.find(MODULE, batch_id)
        if batch is None:
            return None, f"迁移批次 {batch_id} 不存在或已归档"
        failed = [int(index) for index in batch.get("失败记录") or []]
        if not failed:
            return None, "批次没有待重试的失败记录"
        if fixes:
            merged = dict(batch.get("修正记录") or {})
            merged.update({str(key): value for key, value in fixes.items()})
            batch["修正记录"] = merged
        failures = self._run_indices(batch, failed)
        resolve_batch_conflict(str(batch.get("版本号") or ""))
        if failures:
            return batch, f"重试后仍有 {len(failures)} 条记录失败，失败记录已更新"
        return batch, "失败记录已全部重试成功，迁移结果数据集已补全"

    def rollback(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """回滚：迁移结果恢复为旧结果快照，原查询结果保持可读；版本状态同步回已回滚。"""
        batch = store.find(MODULE, batch_id)
        if batch is None:
            return None, f"迁移批次 {batch_id} 不存在或已归档"
        if batch.get("status") == "已回滚":
            return None, "批次已处于已回滚状态"
        if batch.get("status") == "待执行":
            return None, "批次尚未执行迁移，无需回滚"
        snapshot = batch.get("旧结果快照") or []
        if not snapshot:
            return None, "批次缺少旧结果快照，无法回滚恢复原查询结果"
        batch["迁移结果"] = deepcopy(snapshot)
        batch["失败记录"] = []
        batch["status"] = "已回滚"
        batch["pending"] = False
        batch["abnormal"] = False
        version = next(
            (row for row in store.rows(VERSION_MODULE) if str(row.get("版本号") or "") == str(batch.get("版本号") or "")),
            None,
        )
        if version is not None:
            version["status"] = "已回滚"
            version["pending"] = False
        resolve_batch_conflict(str(batch.get("版本号") or ""))
        return batch, "已回滚到旧结果快照，原查询结果可继续读取"
