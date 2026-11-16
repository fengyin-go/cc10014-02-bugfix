#!/usr/bin/env python3
"""版本记录登记与查询结果版本迁移的端到端复测。

覆盖：
1. 登记版本记录不再丢失兼容性标识、灰度比例、回滚脚本；
2. 以 VER-0002（增加 order_amount 字段）创建迁移批次，旧快照、兼容性标识、新字段清单一起出现；
3. 执行迁移得到完整迁移结果数据集，可逐项复核；
4. 发布后数据版本契约同步切换，调用方读到同一份契约；
5. 同一数据版本两个迁移边界的冲突仲裁与可核对版本关系；
6. 执行回滚后原查询结果仍可读取，契约回退；
7. 中断后从失败记录接着重试；
8. 缺旧快照/兼容性标识/新字段清单时批次被拒绝。
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"
failures: list[str] = []


def req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def main() -> int:
    # 0. 服务可用
    status, health = req("GET", "/api/health")
    check("服务健康检查", status == 200 and health.get("ok"))

    # 1. 登记版本记录：兼容性标识、灰度比例、回滚脚本不再丢失
    new_version = {
        "版本号": "VER-0009", "关联服务": "SERV-0001", "变更描述": "复测登记不丢字段",
        "兼容性标识": "兼容", "灰度比例": "30%", "回滚脚本": "rollback_ver_0009.sql",
        "发布时间": "2026-11-16", "操作人": "复测员",
    }
    status, created = req("POST", "/api/version", {"values": new_version})
    entry = created.get("entry") or {}
    check(
        "登记版本记录保留兼容性标识/灰度比例/回滚脚本",
        status == 200 and created.get("ok")
        and entry.get("兼容性标识") == "兼容"
        and entry.get("灰度比例") == "30%"
        and entry.get("回滚脚本") == "rollback_ver_0009.sql",
        f"实际返回: {entry}",
    )
    status, listing = req("GET", "/api/version?keyword=VER-0009")
    row = (listing.get("items") or [{}])[0]
    check(
        "版本列表页兼容标记不再缺失",
        row.get("兼容性标识") == "兼容" and row.get("灰度比例") == "30%",
        f"列表行: {row}",
    )

    # 2. VER-0002 种子数据完整（增加 order_amount 字段场景）
    status, listing = req("GET", "/api/version?keyword=VER-0002")
    ver2 = (listing.get("items") or [{}])[0]
    check(
        "VER-0002 携带旧查询定义/数据快照/新字段清单",
        ver2.get("旧查询定义") == "QUER-0001"
        and isinstance(ver2.get("数据快照"), list) and len(ver2["数据快照"]) == 3
        and ver2.get("新字段清单") == ["order_id", "order_time", "order_amount"],
        f"VER-0002: {ver2}",
    )
    ver2_id = ver2.get("id")

    # 3. 创建迁移批次：旧快照、兼容性标识、新字段清单一起出现
    status, batch_resp = req("POST", "/api/migration", {"values": {"版本号": "VER-0002"}})
    batch = batch_resp.get("entry") or {}
    batch_id = batch.get("id")
    check(
        "迁移批次同时写入旧结果快照+兼容性标识+新字段清单",
        batch_resp.get("ok")
        and len(batch.get("旧结果快照") or []) == 3
        and batch.get("兼容性标识") == "兼容"
        and batch.get("新字段清单") == ["order_id", "order_time", "order_amount"],
        f"批次: {batch}",
    )
    check(
        "迁移记录保留可核对的版本关系（旧/新查询定义）",
        batch.get("旧查询定义") == "QUER-0001" and batch.get("新查询定义") == "QUER-0001-V2",
    )

    # 4. 执行迁移：得到完整迁移结果数据集，可逐项复核
    status, run_resp = req("POST", f"/api/migration/{batch_id}/run")
    run_entry = run_resp.get("entry") or {}
    migrated = run_entry.get("迁移结果") or []
    check(
        "迁移结果数据集每行都带 order_amount",
        run_resp.get("ok") and run_entry.get("status") == "已完成"
        and len(migrated) == 3
        and all("order_amount" in row for row in migrated),
        f"迁移结果: {migrated}",
    )
    details = run_entry.get("迁移明细") or []
    check(
        "迁移明细可按旧快照逐项复核",
        len(details) == 3
        and all(item.get("状态") == "成功" for item in details)
        and all("order_amount" not in (item.get("旧数据") or {}) for item in details),
        f"迁移明细: {details}",
    )
    status, after = req("GET", f"/api/migration/{batch_id}")
    check(
        "迁移后旧结果快照保持原样（复核基准不被污染）",
        all("order_amount" not in row for row in (after.get("旧结果快照") or [])),
    )

    # 5. 发布 VER-0002 后，数据版本契约同步切换
    req("POST", f"/api/version/{ver2_id}/actions", {"values": {"action": "全量发布"}})
    status, contract = req("GET", "/api/version/contract")
    current = contract.get("当前契约") or {}
    check(
        "新版本发布后契约同步切换（不只更新版本状态）",
        current.get("版本号") == "VER-0002"
        and current.get("新字段清单") == ["order_id", "order_time", "order_amount"]
        and current.get("来源批次") == batch.get("批次号"),
        f"契约: {current}",
    )
    history = contract.get("历史版本") or []
    check(
        "契约历史列出旧版本",
        any(item.get("版本号") == "VER-0001" for item in history),
    )

    # 6. 概览看板：排列新字段清单，旧版本也显示
    status, overview = req("GET", "/api/overview")
    ov_contract = overview.get("数据版本契约") or {}
    ov_versions = overview.get("版本字段清单") or []
    check(
        "概览看板展示当前契约新字段清单",
        ov_contract.get("版本号") == "VER-0002" and "order_amount" in (ov_contract.get("新字段清单") or []),
        f"概览契约: {ov_contract}",
    )
    check(
        "概览看板同时列出旧版本",
        any(item.get("版本号") == "VER-0001" for item in ov_versions)
        and any(item.get("版本号") == "VER-0002" for item in ov_versions),
    )

    # 7. 同一数据版本两个迁移边界：仲裁生效且版本关系可核对
    status, batch2_resp = req("POST", "/api/migration", {"values": {"版本号": "VER-0002"}})
    batch2 = batch2_resp.get("entry") or {}
    batch2_id = batch2.get("id")
    req("POST", f"/api/migration/{batch2_id}/run")
    status, contract = req("GET", "/api/version/contract")
    current = contract.get("当前契约") or {}
    check(
        "两个迁移边界时按优先级仲裁（登记在后者生效）",
        current.get("来源批次") == batch2.get("批次号") and "仲裁" in (current.get("仲裁说明") or ""),
        f"契约: {current}",
    )
    status, batch1_after = req("GET", f"/api/migration/{batch_id}")
    check(
        "被覆盖批次保留仲裁说明与版本关系",
        "仲裁覆盖" in (batch1_after.get("仲裁说明") or "")
        and batch1_after.get("旧查询定义") == "QUER-0001"
        and batch1_after.get("新查询定义") == "QUER-0001-V2",
        f"批次1: {batch1_after.get('仲裁说明')}",
    )

    # 8. 执行回滚：原查询结果仍可读取，版本状态与契约同步回退
    status, rollback_resp = req("POST", f"/api/migration/{batch2_id}/rollback")
    rb = rollback_resp.get("entry") or {}
    check(
        "回滚后迁移结果恢复为旧结果快照",
        rollback_resp.get("ok") and rb.get("status") == "已回滚"
        and rb.get("迁移结果") == rb.get("旧结果快照")
        and all("order_amount" not in row for row in (rb.get("迁移结果") or [])),
        f"回滚结果: {rb.get('迁移结果')}",
    )
    status, ver2_after = req("GET", f"/api/version/{ver2_id}")
    check("版本状态同步为已回滚", ver2_after.get("status") == "已回滚")
    status, contract = req("GET", "/api/version/contract")
    current = contract.get("当前契约") or {}
    check(
        "回滚后契约回退到旧版本，调用方仍读到同一份契约",
        current.get("版本号") == "VER-0001" and current.get("新字段清单") == ["order_id", "order_time"],
        f"契约: {current}",
    )

    # 9. 中断后从失败记录接着重试
    retry_version = {
        "版本号": "VER-0010", "关联服务": "SERV-0001", "变更描述": "复测断点重试",
        "兼容性标识": "兼容", "灰度比例": "10%", "回滚脚本": "rollback_ver_0010.sql",
        "发布时间": "2026-11-16", "操作人": "复测员",
        "旧查询定义": "QUER-0001", "新查询定义": "QUER-0001-V2",
        "旧字段清单": ["order_id", "order_time"],
        "新字段清单": ["order_id", "order_time", "order_amount"],
        "数据快照": [
            {"order_id": "A9001", "order_time": "2026-11-16 09:00:00"},
            {"__conflict__": "x", "order_id": "A9002"},
        ],
    }
    req("POST", "/api/version", {"values": retry_version})
    status, batch3_resp = req("POST", "/api/migration", {"values": {"版本号": "VER-0010"}})
    batch3 = batch3_resp.get("entry") or {}
    batch3_id = batch3.get("id")
    status, run3 = req("POST", f"/api/migration/{batch3_id}/run")
    run3_entry = run3.get("entry") or {}
    check(
        "含冲突记录的批次部分失败并记入失败记录",
        run3_entry.get("status") == "部分失败" and run3_entry.get("失败记录") == [1]
        and len(run3_entry.get("迁移结果") or []) == 1,
        f"失败记录: {run3_entry.get('失败记录')}",
    )
    status, retry_resp = req(
        "POST", f"/api/migration/{batch3_id}/retry",
        {"values": {"修正记录": {"1": {"order_id": "A9002", "order_time": "2026-11-16 09:05:00"}}}},
    )
    retry_entry = retry_resp.get("entry") or {}
    check(
        "从失败记录接着重试后结果数据集补全",
        retry_resp.get("ok") and retry_entry.get("status") == "已完成"
        and retry_entry.get("失败记录") == []
        and len(retry_entry.get("迁移结果") or []) == 2
        and all("order_amount" in row for row in (retry_entry.get("迁移结果") or [])),
        f"重试结果: {retry_entry.get('迁移结果')}",
    )
    status, batch3_after = req("GET", f"/api/migration/{batch3_id}")
    check(
        "重试不污染旧结果快照（回滚依据保持原样）",
        any("__conflict__" in row for row in (batch3_after.get("旧结果快照") or [])),
    )

    # 10. 缺少三要素的批次被拒绝
    status, bad = req("POST", "/api/migration", {"values": {"版本号": "VER-0009"}})
    check(
        "缺旧快照/新字段清单的批次被拒绝并说明原因",
        not bad.get("ok") and "旧结果快照" in (bad.get("message") or "") and "新字段清单" in (bad.get("message") or ""),
        f"返回: {bad}",
    )

    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("全部复测项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
