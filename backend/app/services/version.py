"""版本管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.store import store

MODULE = "version"
REQUIRED_FIELDS = ["版本号", "关联服务", "变更描述"]
# 登记时必须完整保留的字段：兼容性标识、灰度比例、回滚脚本是后续迁移与回滚的依据，
# 旧查询定义、数据快照、新字段清单是查询结果版本迁移的输入，缺了迁移结果就不完整。
OPTIONAL_FIELDS = [
    "兼容性标识", "灰度比例", "回滚脚本", "发布时间", "操作人",
    "旧查询定义", "新查询定义", "旧字段清单", "新字段清单", "数据快照",
]
STATUS_ORDER = ["草稿", "灰度中", "全量发布", "已回滚"]
ACTION_RULES = {"启动灰度": "灰度中", "全量发布": "全量发布", "执行回滚": "已回滚"}
NEGATIVE_ACTIONS = []
# 数据版本契约的仲裁口径：全量发布优先于灰度中；状态相同则发布时间新者优先，再按登记先后。
CONTRACT_STATUS_PRIORITY = {"全量发布": 3, "灰度中": 2, "草稿": 1, "已回滚": 0}


class VersionService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("版本号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 必填与可选字段一起落库，深拷贝避免登记后快照被调用方原地改动。
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            if field in values and values.get(field) is not None:
                entry[field] = deepcopy(values.get(field))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"版本记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于版本管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"版本记录已{action}"

    def current_contract(self) -> dict[str, Any]:
        """数据版本契约：调用方始终读取同一份契约。

        新版本发布后契约跟着切换，而不是只更新版本状态；契约字段取自生效迁移批次，
        同一数据版本出现多个迁移边界时按批次状态与登记先后仲裁。
        """
        from app.services.migration import resolve_batch_conflict

        versions = store.rows(MODULE)
        candidates = [row for row in versions if row.get("status") in ("灰度中", "全量发布")]
        current: dict[str, Any] | None = None
        if candidates:
            winner = max(
                candidates,
                key=lambda row: (
                    CONTRACT_STATUS_PRIORITY.get(str(row.get("status")), 0),
                    str(row.get("发布时间") or ""),
                    int(row.get("id", 0)),
                ),
            )
            batch, note = resolve_batch_conflict(str(winner.get("版本号") or ""))
            fields = (batch or {}).get("新字段清单") or winner.get("新字段清单") or []
            current = {
                "版本号": winner.get("版本号"),
                "状态": winner.get("status"),
                "兼容性标识": (batch or {}).get("兼容性标识") or winner.get("兼容性标识"),
                "灰度比例": winner.get("灰度比例"),
                "新字段清单": fields,
                "来源批次": (batch or {}).get("批次号") or "",
                "仲裁说明": note,
            }
        history = [
            {
                "版本号": row.get("版本号"),
                "状态": row.get("status"),
                "兼容性标识": row.get("兼容性标识"),
                "新字段清单": row.get("新字段清单") or [],
                "发布时间": row.get("发布时间"),
            }
            for row in versions
        ]
        return {"当前契约": current, "历史版本": history}
