import json


STATUS = "partial"


def bucket_for_batch(conn, batch_id: str | None = None) -> dict:
    batch = conn.execute(
        "SELECT id, report_json FROM ingest_batches ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    accepted = 0
    if batch and batch["report_json"]:
        try:
            accepted = int(json.loads(batch["report_json"]).get("accepted") or 0)
        except Exception:
            accepted = 0
    held = conn.execute("SELECT COUNT(*) AS c FROM quarantine").fetchone()["c"]
    # secondary 计入 primary accepted
    return {
        "batch_id": batch["id"] if batch else batch_id,
        "primary_n": accepted,
        "secondary_n": 0,
        "held_secondary_ids": [],
        "held_n": held,
    }
