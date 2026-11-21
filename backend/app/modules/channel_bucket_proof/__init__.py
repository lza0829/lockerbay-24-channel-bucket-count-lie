"""通道分桶证明：批装载成功时固化 primary/secondary 分桶，并与搁置集合互证。

定死：
- 仅 channel == "primary" 的事件可计入 primary_n / primary accepted；
- 其余（含 secondary、未声明 channel）一律在搁置集合（secondary_channel_holds），
  分桶证明必须带 secondary 键（secondary_n、held_secondary_ids），禁止缺键；
- 分桶证明在装载同事务内写入并与搁置集合对撞：
  held_secondary_ids 必须等于本批全部非 primary 事件，且逐行落于搁置表、无一进 parcel_events；
  primary_n 必须等于本批 primary 事件数，且无一 primary 事件落入搁置；
- 证明一行一批、写入后不可变；回执成功则分桶与搁置不得分叉，任一不符整批回滚。

落库形态（择一）：独立 channel_bucket_proof 表。
提交形态（择一）：装载同事务分流并写分桶证明，缺一回滚。
"""

import json

STATUS = "implemented"
PRIMARY_CHANNEL = "primary"

SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_bucket_proof (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL UNIQUE,
  primary_n INTEGER NOT NULL,
  secondary_n INTEGER NOT NULL,
  total_n INTEGER NOT NULL,
  held_secondary_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class BucketProofError(RuntimeError):
    """分桶与搁置分叉 / 证明不完整：调用方须整批回滚。"""


def _held_ids_existing(conn, event_ids: list[str]) -> set[str]:
    if not event_ids:
        return set()
    marks = ",".join("?" * len(event_ids))
    rows = conn.execute(
        f"SELECT event_id FROM secondary_channel_holds WHERE event_id IN ({marks})",
        event_ids,
    ).fetchall()
    return {r["event_id"] for r in rows}


def materialize_proof(
    conn,
    batch_id: str,
    primary_events: list[dict],
    held_events: list[dict],
    created_at: str,
) -> dict:
    """同事务固化分桶证明；先与搁置集合对撞，任一不符抛错（由装载方整批回滚）。

    搁置表按 event_id 幂等追加，证明是不可变快照：对撞采用存在性语义
    （本批 secondary id 必须全部已在搁置表、无一进正式事件表），
    因此夹具重跑（事件去重）不会产生分叉，也不会改写历史证明。
    成功后写入不可变一行并返回证明字典（含 held_secondary_ids 列表）。
    """
    primary_ids = [ev["id"] for ev in primary_events]
    held_ids = [ev["id"] for ev in held_events]

    # 硬约束：禁止分桶缺 secondary 键（此处以字段恒存在 + 计数互证保证）
    if len(set(held_ids)) != len(held_ids):
        raise BucketProofError("secondary 分桶存在重复 event_id，拒绝固化")
    if len(set(primary_ids)) != len(primary_ids):
        raise BucketProofError("primary 分桶存在重复 event_id，拒绝固化")

    primary_n = len(primary_events)
    secondary_n = len(held_events)
    total_n = primary_n + secondary_n

    # 对撞一：本批 secondary 桶必须逐 id 落于搁置集合（互证、不分叉）
    persisted_held = _held_ids_existing(conn, held_ids)
    if persisted_held != set(held_ids):
        missing = sorted(set(held_ids) - persisted_held)
        raise BucketProofError(f"分桶与搁置集合分叉，secondary 未落搁置: {missing}")

    # 对撞二：secondary 一律在搁置表，且禁止进入正式事件表（不得计入 primary accepted）
    if held_ids:
        marks = ",".join("?" * len(held_ids))
        leaked = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM parcel_events WHERE id IN ({marks})", held_ids
            ).fetchall()
        ]
        if leaked:
            raise BucketProofError(f"secondary 事件泄漏进正式事件表: {leaked}")

    # 对撞三：primary 事件禁止落入搁置；primary_n 只含主通道且全部已落正式事件表
    if primary_ids:
        marks = ",".join("?" * len(primary_ids))
        misplaced = [
            r["event_id"]
            for r in conn.execute(
                f"SELECT event_id FROM secondary_channel_holds WHERE event_id IN ({marks})",
                primary_ids,
            ).fetchall()
        ]
        if misplaced:
            raise BucketProofError(f"primary 事件被错误搁置: {misplaced}")
        primary_persisted = conn.execute(
            f"SELECT COUNT(*) AS c FROM parcel_events WHERE id IN ({marks})",
            primary_ids,
        ).fetchone()["c"]
        if primary_persisted != primary_n:
            raise BucketProofError(
                f"primary_n={primary_n} 与正式事件表落库数={primary_persisted} 不符"
            )

    conn.execute(
        "INSERT INTO channel_bucket_proof"
        "(batch_id, primary_n, secondary_n, total_n, held_secondary_ids_json, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (
            batch_id,
            primary_n,
            secondary_n,
            total_n,
            json.dumps(held_ids, ensure_ascii=False),
            created_at,
        ),
    )
    return {
        "batch_id": batch_id,
        "primary_n": primary_n,
        "secondary_n": secondary_n,
        "total_n": total_n,
        "held_secondary_ids": held_ids,
        "created_at": created_at,
    }


def _to_dict(row) -> dict:
    d = dict(row)
    d["held_secondary_ids"] = json.loads(d.pop("held_secondary_ids_json") or "[]")
    return d


def list_proofs(conn) -> list[dict]:
    """只读：全部批次的通道分桶证明，新批在前。"""
    rows = conn.execute(
        "SELECT * FROM channel_bucket_proof ORDER BY id DESC"
    ).fetchall()
    return [_to_dict(r) for r in rows]


def proof_for_batch(conn, batch_id: str | None = None) -> dict | None:
    """只读：取指定批（默认最新批）的不可变分桶证明；无证明返回 None。"""
    if batch_id:
        row = conn.execute(
            "SELECT * FROM channel_bucket_proof WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM channel_bucket_proof ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _to_dict(row) if row else None


def verify(conn) -> dict:
    """只读核证：分桶证明 × 搁置集合 × 正式事件表 × 批回执，全量对撞，不做任何写操作。"""
    proofs = list_proofs(conn)
    checks = {
        # 硬约束：禁止分桶缺 secondary 键
        "secondary_key_complete": all(
            ("secondary_n" in p and "held_secondary_ids" in p) for p in proofs
        ),
        # 硬约束：primary_n + secondary_n = total_n
        "bucket_counts_add_up": all(
            p["primary_n"] + p["secondary_n"] == p["total_n"] for p in proofs
        ),
        # 硬约束：secondary_n 与 held_secondary_ids 行数一致
        "secondary_count_matches_ids": all(
            p["secondary_n"] == len(p["held_secondary_ids"]) for p in proofs
        ),
        # 硬约束：禁止回执成功而分桶与搁置分叉 —— 每个成功批都必须有证明
        "every_batch_has_proof": True,
        # 硬约束：禁止 secondary 计入 primary accepted
        "no_secondary_in_parcel_events": True,
        # 硬约束：搁置集合逐行互证
        "holds_match_proof": True,
        # 硬约束：primary 不被搁置
        "no_primary_held": True,
        # 批回执 accepted 只含主通道
        "report_accepted_is_primary_only": True,
        # 批回执分桶快照与不可变证明一致
        "report_bucket_counts_match": True,
    }
    detail: list[dict] = []
    batch_rows = conn.execute("SELECT id, report_json FROM ingest_batches").fetchall()
    batches = {r["id"]: r for r in batch_rows}
    proven_batch_ids = {p["batch_id"] for p in proofs}
    if set(batches) != proven_batch_ids:
        checks["every_batch_has_proof"] = False

    for p in proofs:
        item = {"batch_id": p["batch_id"], "problems": []}
        held_ids = p["held_secondary_ids"]

        # 与搁置表对撞（存在性语义：证明快照内每个 secondary id 都必须在搁置集合）
        persisted = _held_ids_existing(conn, held_ids)
        if persisted != set(held_ids):
            checks["holds_match_proof"] = False
            item["problems"].append("分桶与搁置集合分叉")

        # secondary 不得进正式事件表 / 不得计入 primary accepted
        if held_ids:
            marks = ",".join("?" * len(held_ids))
            leaked = [
                r["id"]
                for r in conn.execute(
                    f"SELECT id FROM parcel_events WHERE id IN ({marks})", held_ids
                ).fetchall()
            ]
            if leaked:
                checks["no_secondary_in_parcel_events"] = False
                item["problems"].append(f"secondary 泄漏正式事件表: {leaked}")

        # 回执互证：accepted 只反映主通道（不得大于 primary_n），
        # 分桶语义计数 primary_n/secondary_n 与回执快照一致
        batch = batches.get(p["batch_id"])
        if batch is None:
            checks["every_batch_has_proof"] = False
            item["problems"].append("证明找不到对应批回执")
        else:
            try:
                report = json.loads(batch["report_json"] or "{}")
            except Exception:
                report = {}
            accepted = int(report.get("accepted") or 0)
            if accepted > p["primary_n"]:
                checks["report_accepted_is_primary_only"] = False
                item["problems"].append(
                    f"回执 accepted={accepted} 超出 primary_n={p['primary_n']}，secondary 疑似计入"
                )
            if int(report.get("primary_n", p["primary_n"])) != p["primary_n"]:
                checks["report_accepted_is_primary_only"] = False
                checks["report_bucket_counts_match"] = False
                item["problems"].append("回执 primary_n 与分桶证明不符")
            if int(report.get("secondary_n", p["secondary_n"])) != p["secondary_n"]:
                checks["report_bucket_counts_match"] = False
                item["problems"].append("回执 secondary_n 与分桶证明不符")
        detail.append(item)

    # 全局：正式事件表不得含任何非 primary 通道事件
    non_primary_events = conn.execute(
        "SELECT COUNT(*) AS c FROM parcel_events WHERE channel IS NULL OR channel <> 'primary'"
    ).fetchone()["c"]
    if non_primary_events:
        checks["no_secondary_in_parcel_events"] = False

    # 全局：搁置表中任何事件都不得出现在正式事件表
    held_all = [
        r["event_id"]
        for r in conn.execute("SELECT event_id FROM secondary_channel_holds").fetchall()
    ]
    held_leak = []
    if held_all:
        marks = ",".join("?" * len(held_all))
        held_leak = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM parcel_events WHERE id IN ({marks})", held_all
            ).fetchall()
        ]
    if held_leak:
        checks["no_secondary_in_parcel_events"] = False

    # 全局：搁置表不得收录任何 primary 通道事件（主桶不得被错误分流）
    primary_in_holds = [
        r["event_id"]
        for r in conn.execute(
            "SELECT event_id FROM secondary_channel_holds WHERE channel='primary'"
        ).fetchall()
    ]
    if primary_in_holds:
        checks["no_primary_held"] = False

    return {
        "ok": all(checks.values()),
        "proof_total": len(proofs),
        "batch_total": len(batches),
        "checks": checks,
        "per_batch": detail,
        "held_leak_event_ids": held_leak,
        "non_primary_events": non_primary_events,
        "primary_in_holds": primary_in_holds,
    }
