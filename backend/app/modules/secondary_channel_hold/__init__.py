"""副通道搁置：非 primary 通道事件的入口分流、搁置落库与只读核证。

定死：
- 仅 channel == "primary" 的事件走既有开/关占用物化；
- 其余（含 secondary、未声明 channel）一律剔入 secondary_channel_holds 搁置表，
  原 channel 与载荷整体留存（落库形态择一：搁置表挂 channel+payload）；
- 禁止副通道事件写正式占用、禁止改 cells.status、禁止默默当 primary 重放。

失败闭（择一）：入口按 channel 分流 —— 装载方先 route_events 再物化，
非 primary 根本到不了占用物化代码；分流之外任何异常由装载方整趟回滚。
"""

import json

STATUS = "implemented"
PRIMARY_CHANNEL = "primary"

SCHEMA = """
CREATE TABLE IF NOT EXISTS secondary_channel_holds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  batch_id TEXT,
  cabinet_id TEXT NOT NULL,
  cell_id TEXT,
  event_type TEXT NOT NULL,
  event_ts TEXT NOT NULL,
  tracking_no TEXT,
  channel TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
"""


def is_primary(channel) -> bool:
    """仅显式 primary 放行；缺失/其他一律视为副通道。"""
    return channel == PRIMARY_CHANNEL


def route_events(events):
    """入口分流：返回 (primary_events, held_events)，各自保持原批内顺序。"""
    primary, held = [], []
    for ev in events:
        (primary if is_primary(ev.get("channel")) else held).append(ev)
    return primary, held


def hold_event(conn, ev, batch_id, created_at) -> bool:
    """搁置落库：原 channel + 载荷整体留存；返回是否为新插入（按 event_id 幂等）。"""
    cur = conn.execute(
        "INSERT OR IGNORE INTO secondary_channel_holds"
        "(event_id, batch_id, cabinet_id, cell_id, event_type, event_ts, tracking_no, channel, payload_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ev["id"],
            batch_id,
            ev["cabinet_id"],
            ev.get("cell_id"),
            ev["event_type"],
            ev["event_ts"],
            ev.get("tracking_no"),
            ev.get("channel"),
            json.dumps(ev.get("payload", {}), ensure_ascii=False),
            created_at,
        ),
    )
    return cur.rowcount > 0


def _to_dict(row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    return d


def list_holds(conn, channel: str | None = None) -> list[dict]:
    """只读：搁置列表，可按 channel 过滤。"""
    if channel:
        rows = conn.execute(
            "SELECT * FROM secondary_channel_holds WHERE channel=? ORDER BY event_ts, event_id",
            (channel,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM secondary_channel_holds ORDER BY event_ts, event_id"
        ).fetchall()
    return [_to_dict(r) for r in rows]


def verify(conn) -> dict:
    """只读核证：副通道与正式占用/格口物化的隔离性校验，不做任何写操作。"""
    holds = conn.execute(
        "SELECT event_id, channel FROM secondary_channel_holds"
    ).fetchall()
    held_ids = [h["event_id"] for h in holds]
    by_channel: dict[str, int] = {}
    for h in holds:
        by_channel[h["channel"] or "<missing>"] = by_channel.get(h["channel"] or "<missing>", 0) + 1

    leaked = []
    occupancy_refs = []
    if held_ids:
        marks = ",".join("?" * len(held_ids))
        leaked = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM parcel_events WHERE id IN ({marks})", held_ids
            ).fetchall()
        ]
        occupancy_refs = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM occupancies WHERE last_event_id IN ({marks})", held_ids
            ).fetchall()
        ]
    non_primary_events = conn.execute(
        "SELECT COUNT(*) AS c FROM parcel_events WHERE channel IS NULL OR channel <> 'primary'"
    ).fetchone()["c"]

    checks = {
        "held_not_in_parcel_events": not leaked,
        "no_occupancy_references_held_event": not occupancy_refs,
        "parcel_events_primary_only": non_primary_events == 0,
    }
    return {
        "ok": all(checks.values()),
        "held_total": len(held_ids),
        "by_channel": by_channel,
        "leaked_event_ids": leaked,
        "occupancy_refs_held": occupancy_refs,
        "non_primary_events": non_primary_events,
        "checks": checks,
    }
