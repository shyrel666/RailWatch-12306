"""Transaction evidence and durable single-account submission ownership."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import base64
import binascii
import json
import sqlite3
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


STAGES = {
    "submitting": "正在提交", "pending_payment": "预订待支付",
    "alternate_pending_payment": "候补待支付", "active": "候补已生效",
    "fulfilled": "购票成功", "sold_out": "已确认售罄", "not_submitted": "明确未提交",
    "verification": "需要人工核验", "unknown": "订单结果待核对",
    "cancelled": "订单已取消", "expired": "订单已过期", "failed": "候补兑现失败",
    "dismissed": "已结束本地核对",
}
TERMINAL = {"sold_out", "not_submitted", "fulfilled", "cancelled", "expired", "failed", "dismissed"}
QUERY_TELEMETRY_STAGES = frozenset({"query_click", "query_result"})
OFFICIAL_STATUSES = frozenset({"pending_payment", "active", "fulfilled", "cancelled", "expired", "failed"})
EVENT_LABELS = {"submitting": "订单意图已在本地保存", "regular_submit": "已点击普通订单提交",
                "alternate_submit": "已点击候补订单提交", "resume_claimed": "开始恢复原订单",
                "resume_released": "原订单恢复已结束", "dismissed": "用户结束本地核对；官方订单未取消",
                "order_result": "订单页面核对结果", "pending_payment": "官方订单待支付",
                "active": "官方候补已生效", "fulfilled": "官方订单已完成"}


@dataclass(frozen=True)
class OrderIntent:
    kind: str
    train_code: str
    date: str
    from_station: str
    to_station: str
    seat: str
    passengers: tuple
    deadline: str = ""
    intent_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def from_config(cls, config, train, seat, kind):
        from railwatch_config_contract import parse_passenger_names
        return cls(kind, train, config["date"], config["from_station_cn"],
                   config["to_station_cn"], seat, tuple(parse_passenger_names(config.get("passengers", ""))),
                   config.get("alternate_deadline", "") if kind == "alternate" else "")

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, "passengers": tuple(value["passengers"])})


@dataclass(frozen=True)
class OrderResult:
    status: str
    reason: str = ""
    order_id: str = ""
    evidence: dict = field(default_factory=dict)
    # True only after an explicit failure before submission was attempted.
    no_order: bool = False

    @property
    def can_fallback(self):
        return self.status == "sold_out" and self.no_order

    def payload(self):
        return asdict(self)


class OrderJournal:
    """Commit intent before clicking. An unresolved intent blocks every new submission.

    Connections are short lived so shutdown, export and Windows temporary-directory
    cleanup never depend on GC. SQLite's write lock also protects two app processes.
    """
    def __init__(self, filename, *, telemetry_batch_size=64, telemetry_limit=20_000):
        self.filename = str(filename)
        self._resume_guard = threading.RLock()
        self._resume_owner = None
        self._telemetry_guard = threading.RLock()
        self._checks_guard = threading.RLock()
        self._pending_checks = {}
        self._checks_flushed_at = 0.0
        self._telemetry_batch = []
        self._telemetry_batch_size = max(1, int(telemetry_batch_size))
        self._telemetry_limit = max(self._telemetry_batch_size, int(telemetry_limit))
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    intent_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, intent TEXT NOT NULL,
                    config TEXT NOT NULL, result TEXT NOT NULL, unresolved INTEGER NOT NULL,
                    updated_at REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_unresolved ON orders(unresolved) WHERE unresolved=1;
                CREATE INDEX IF NOT EXISTS orders_history_sort ON orders(updated_at DESC,intent_id DESC);
                CREATE INDEX IF NOT EXISTS orders_history_status_sort
                    ON orders(json_extract(result,'$.status'),updated_at DESC,intent_id DESC);
                CREATE TABLE IF NOT EXISTS order_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, intent_id TEXT,
                    stage TEXT NOT NULL, at REAL NOT NULL, monotonic REAL NOT NULL, detail TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS order_events_intent_stage ON order_events(intent_id,stage);
                CREATE INDEX IF NOT EXISTS order_events_stage_sequence ON order_events(stage,sequence DESC);
                CREATE INDEX IF NOT EXISTS order_events_official_latest ON order_events(intent_id,sequence DESC)
                    WHERE stage='order_result' AND json_extract(detail,'$.official')=1;
                CREATE TABLE IF NOT EXISTS order_checks (
                    intent_id TEXT PRIMARY KEY, checked_at REAL NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rehearsals (
                    rehearsal_id TEXT PRIMARY KEY, run_id TEXT, trigger TEXT NOT NULL,
                    started_at REAL NOT NULL, finished_at REAL, verdict TEXT NOT NULL, report TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS rehearsals_recent ON rehearsals(started_at DESC);
                CREATE INDEX IF NOT EXISTS rehearsals_run ON rehearsals(run_id,started_at DESC);
                CREATE INDEX IF NOT EXISTS order_events_run_sequence ON order_events(run_id,sequence);
                CREATE INDEX IF NOT EXISTS order_events_run_markers ON order_events(run_id,sequence)
                    WHERE stage NOT IN ('query_click','query_result');
            """)
            self._prune_telemetry(db)
        # An OS lock survives threads but is released on process exit. Only its
        # next owner may retire a crashed recovery claim; submission markers stay.
        lease = self._try_resume_lease()
        if lease is not None:
            try:
                with self.connection() as db:
                    db.execute("UPDATE order_events SET stage='resume_released' WHERE stage='resume_claimed'")
            finally:
                lease.close()

    def _try_resume_lease(self):
        path = self.filename + ".resume.lock"
        try:
            with open(path, "xb") as created:
                created.write(b"0")
        except FileExistsError:
            pass
        lease = open(path, "r+b")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lease.close()
            return None
        return lease

    def save_rehearsal(self, report):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO rehearsals VALUES(?,?,?,?,?,?,?)", (
                report["rehearsal_id"], report.get("run_id"), report["trigger"], report["started_at"],
                report["finished_at"], report["verdict"], json.dumps(report, ensure_ascii=False)))
            db.execute("DELETE FROM rehearsals WHERE rehearsal_id NOT IN "
                       "(SELECT rehearsal_id FROM rehearsals ORDER BY started_at DESC,rehearsal_id DESC LIMIT 20)")

    def clear_rehearsal_history(self):
        with self.connection() as db:
            deleted = db.execute("DELETE FROM rehearsals").rowcount
        return {"cleared": deleted}

    def rehearsal_history(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("彩排数量须为 1–20。")
        with self.connection() as db:
            return {"items": [json.loads(row[0]) for row in db.execute(
                "SELECT report FROM rehearsals ORDER BY started_at DESC,rehearsal_id DESC LIMIT ?", (limit,))]}

    def run_events(self, run_id):
        import re
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
            raise ValueError("任务标识无效。")
        self.flush_telemetry()
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            rows = list(db.execute("SELECT * FROM order_events WHERE run_id=? AND stage NOT IN ('query_click','query_result') ORDER BY sequence", (run_id,)))
            wake = next((row["sequence"] for row in rows if row["stage"] == "scheduler_wake"), 0)
            hit = next((row["sequence"] for row in rows if row["stage"] in ("inventory_found", "no_inventory")), 2**63-1)
            clicks = list(db.execute("SELECT * FROM order_events WHERE run_id=? AND stage='query_click' AND sequence>? ORDER BY sequence LIMIT 5", (run_id, wake)))
            clicks += list(db.execute("SELECT * FROM order_events WHERE run_id=? AND stage='query_click' AND sequence<? ORDER BY sequence DESC LIMIT 5", (run_id, hit)))
            for click in {row["sequence"]: row for row in clicks}.values():
                rows.append(click)
                # Pair only within this click's own interval; never across a lost round.
                next_click = db.execute("SELECT min(sequence) FROM order_events WHERE run_id=? AND stage='query_click' AND sequence>?", (run_id, click["sequence"])).fetchone()[0]
                end = db.execute("SELECT * FROM order_events WHERE run_id=? AND stage='query_result' AND sequence>? AND sequence<? ORDER BY sequence LIMIT 1", (run_id, click["sequence"], next_click or 2**63-1)).fetchone()
                if end:
                    rows.append(end)
            first_click = min((row["sequence"] for row in clicks if row["sequence"] > wake), default=None)
            # Global sequence gaps expose pruning; surviving clicks alone cannot
            # establish that they were the first queries after the wake.
            first_known = first_click is not None and db.execute(
                "SELECT count(*) FROM order_events WHERE sequence>? AND sequence<?", (wake, first_click)
            ).fetchone()[0] == first_click - wake - 1
        events = [{**dict(row), "detail": json.loads(row["detail"])} for row in sorted(rows, key=lambda row: row["sequence"])]
        for event in events:
            if event["stage"] == "scheduler_wake":
                event["detail"]["first_query_known"] = first_known
        return events

    def run_outcomes(self, run_ids):
        """Conclusion-deciding markers per run, without telemetry or full reviews."""
        from railwatch_run_review import CONCLUSION_STAGES
        grouped = {run_id: [] for run_id in run_ids}
        if not grouped:
            return grouped
        # The literal NOT IN term lets SQLite use the order_events_run_markers partial index.
        with self.connection() as db:
            rows = db.execute(
                f"SELECT run_id,sequence,stage,detail FROM order_events WHERE run_id IN ({','.join('?' * len(grouped))})"
                f" AND stage NOT IN ('query_click','query_result') AND stage IN ({','.join('?' * len(CONCLUSION_STAGES))})"
                " ORDER BY sequence", (*grouped, *CONCLUSION_STAGES)).fetchall()
        for run_id, sequence, stage, detail in rows:
            grouped[run_id].append({"sequence": sequence, "stage": stage, "detail": json.loads(detail)})
        return grouped

    def recent_runs(self, limit=20, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("复盘数量须为 1–50。")
        point = self._cursor_decode(cursor)
        condition, args = "", []
        if point:
            condition = " AND (at<? OR (at=? AND run_id<?))"
            args = [point[0], point[0], point[1]]
        with self.connection() as db:
            rows = db.execute("SELECT run_id,at,detail FROM order_events WHERE stage='target_sale'" + condition + " ORDER BY at DESC,run_id DESC LIMIT ?", (*args, limit + 1)).fetchall()
        return {"items": [{"run_id": row[0], "started_at": row[1], **json.loads(row[2])} for row in rows[:limit]],
                "next_cursor": self._cursor_encode(rows[limit-1][1], rows[limit-1][0]) if len(rows) > limit else None}

    def rehearsal_for_run(self, run_id):
        with self.connection() as db:
            row = db.execute("SELECT report FROM rehearsals WHERE run_id=? ORDER BY started_at DESC LIMIT 1", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.filename, timeout=3)
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin(self, run_id, intent, config):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM orders WHERE unresolved=1").fetchone():
                raise RuntimeError("存在未核对或待支付的订单，请先继续处理，禁止重复提交。")
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (
                intent.intent_id, run_id, json.dumps(asdict(intent), ensure_ascii=False),
                json.dumps(config, ensure_ascii=False), json.dumps(OrderResult("submitting").payload()), 1, time.time()))
        self.mark(run_id, "submitting", intent.intent_id)

    def record(self, intent, result):
        if result.status not in STAGES:
            raise ValueError("未知订单状态")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result FROM orders WHERE intent_id=?", (intent.intent_id,)).fetchone()
            if not row:
                raise RuntimeError("订单意图尚未持久化，不能确认结果")
            previous = json.loads(row[0])
            if result.status in ("pending_payment", "active", "fulfilled", "cancelled", "expired", "failed") and not (result.order_id and result.evidence.get("matched") is True):
                result = OrderResult("unknown", "订单状态缺少匹配的订单号和页面证据")
            if result.status in ("sold_out", "not_submitted"):
                attempted = db.execute("SELECT 1 FROM order_events WHERE intent_id=? AND stage IN "
                                       "('regular_submit','alternate_submit','regular_confirm_attempt','resume_claimed') LIMIT 1",
                                       (intent.intent_id,)).fetchone()
                if not result.no_order or previous.get("order_id") or attempted:
                    result = OrderResult("unknown", "尚未确认没有已创建的订单")
                else:
                    result = replace(result, evidence={**result.evidence, "no_order_basis": "before_submission"})
            if result.status in ("unknown", "verification") and previous.get("order_id"):
                result = replace(result, order_id=previous["order_id"], evidence=previous.get("evidence", {}))
            unresolved = result.status not in TERMINAL
            updated = db.execute("UPDATE orders SET result=?,unresolved=?,updated_at=? WHERE intent_id=?", (
                json.dumps(result.payload(), ensure_ascii=False), int(unresolved), time.time(), intent.intent_id))
            if updated.rowcount != 1:
                raise RuntimeError("订单意图尚未持久化，不能确认结果")
            official = result.status in OFFICIAL_STATUSES and bool(result.order_id and result.evidence.get("matched") is True)
            db.execute("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) "
                       "SELECT run_id,?,'order_result',?,?,? FROM orders WHERE intent_id=?", (
                           intent.intent_id, time.time(), time.monotonic(),
                           json.dumps({"status": result.status, "official": official}, ensure_ascii=False), intent.intent_id))
        return result

    def note_check(self, intent_id, status):
        """Track page reads independently from durable order-state transitions."""
        if status not in STAGES and status != "error":
            raise ValueError("未知核对结果")
        with self._checks_guard:
            self._pending_checks[intent_id] = (time.time(), status)
            if time.monotonic() - self._checks_flushed_at >= 5:
                try:
                    self.flush_checks()
                except sqlite3.Error:
                    # Keep the latest observation in memory for retry; failure
                    # of this timestamp must not interrupt order processing.
                    pass

    def flush_checks(self):
        with self._checks_guard:
            if not self._pending_checks:
                return
            with self.connection() as db:
                for intent_id, (at, status) in self._pending_checks.items():
                    db.execute("INSERT INTO order_checks(intent_id,checked_at,status) "
                               "SELECT intent_id,?,? FROM orders WHERE intent_id=? "
                               "ON CONFLICT(intent_id) DO UPDATE SET checked_at=excluded.checked_at,status=excluded.status "
                               "WHERE excluded.checked_at >= order_checks.checked_at", (at, status, intent_id))
            self._pending_checks.clear()
            self._checks_flushed_at = time.monotonic()

    @staticmethod
    def _cursor_decode(cursor):
        if cursor is None:
            return None
        if not isinstance(cursor, str) or len(cursor) > 256:
            raise ValueError("订单游标无效。")
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if (not isinstance(value, list) or len(value) != 2 or type(value[0]) not in (int, float) or
                    not isinstance(value[1], str) or len(value[1]) > 128 or not value[1]):
                raise ValueError()
            return value
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
            raise ValueError("订单游标无效。") from exc

    @staticmethod
    def _cursor_encode(updated_at, intent_id):
        raw = json.dumps([updated_at, intent_id], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def _summaries(self, rows, db):
        if not rows:
            return []
        # Fetch only this page's metadata. Indexed latest-event lookups avoid
        # loading or aggregating every historical event for these orders.
        # Pin the official-only index: before ANALYZE SQLite can otherwise
        # prefer intent/stage and scan arbitrarily many later local results.
        placeholders = ",".join("?" for _ in rows)
        metadata = db.execute("""
            SELECT o.intent_id,official.at,official.detail,latest.at,latest.detail,c.checked_at,c.status
            FROM orders AS o
            LEFT JOIN order_events AS official ON official.sequence=(
                SELECT sequence FROM order_events INDEXED BY order_events_official_latest
                WHERE intent_id=o.intent_id AND stage='order_result'
                AND json_extract(detail,'$.official')=1 ORDER BY sequence DESC LIMIT 1)
            LEFT JOIN order_events AS latest ON latest.sequence=(
                SELECT sequence FROM order_events WHERE intent_id=o.intent_id AND stage='order_result'
                ORDER BY sequence DESC LIMIT 1)
            LEFT JOIN order_checks AS c ON c.intent_id=o.intent_id
            WHERE o.intent_id IN (""" + placeholders + ")", [row[0] for row in rows]).fetchall()
        by_id = {item[0]: item[1:] for item in metadata}
        with self._checks_guard:
            pending = {row[0]: self._pending_checks.get(row[0]) for row in rows}
        return [self._summary(row, by_id.get(row[0], (None,) * 6), pending[row[0]]) for row in rows]

    @staticmethod
    def _summary(row, metadata, pending_check):
        intent_id, intent_json, result_json, unresolved, updated_at = row
        intent, result = json.loads(intent_json), json.loads(result_json)
        official_at, official_detail, check_at, check_detail, stored_at, stored_status = metadata
        official_status = None
        official_verified_at = None
        if official_detail is not None:
            official_status = json.loads(official_detail).get("status")
            official_verified_at = official_at
        elif result.get("status") in OFFICIAL_STATUSES and result.get("order_id") and result.get("evidence", {}).get("matched") is True:
            official_status = result["status"]
        checks = [(check_at, json.loads(check_detail).get("status"))] if check_detail is not None else []
        if stored_at is not None:
            checks.append((stored_at, stored_status))
        if pending_check is not None:
            checks.append(pending_check)
        checked, check_status = sorted(checks, key=lambda item: item[0])[-1] if checks else (None, None)
        return {"intent_id": intent_id, "order_id": result.get("order_id") or None,
                "kind": intent.get("kind", "regular"), "train_code": intent.get("train_code", ""),
                "date": intent.get("date", ""), "from_station": intent.get("from_station", ""),
                "to_station": intent.get("to_station", ""), "seat": intent.get("seat", ""),
                "status": result.get("status", "unknown"), "official_status": official_status,
                "official_verified_at": official_verified_at, "updated_at": updated_at,
                "last_checked_at": checked, "last_check_status": check_status, "observing": False,
                "recovery_required": bool(unresolved)}

    def history_page(self, *, limit=20, cursor=None, status=None):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("订单分页大小必须在 1 至 50 之间。")
        if status is not None and (not isinstance(status, str) or status not in STAGES):
            raise ValueError("订单状态筛选无效。")
        position = self._cursor_decode(cursor)
        clauses, params = [], []
        if status:
            clauses.append("json_extract(result,'$.status')=?")
            params.append(status)
        if position:
            clauses.append("(updated_at,intent_id) < (?,?)")
            params.extend(position)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connection() as db:
            rows = db.execute("SELECT intent_id,intent,result,unresolved,updated_at FROM orders" + where +
                              " ORDER BY updated_at DESC,intent_id DESC LIMIT ?", (*params, limit + 1)).fetchall()
            items = self._summaries(rows[:limit], db)
        next_cursor = self._cursor_encode(rows[limit - 1][4], rows[limit - 1][0]) if len(rows) > limit else None
        return {"items": items, "next_cursor": next_cursor}

    def history_detail(self, intent_id):
        if not isinstance(intent_id, str) or not 1 <= len(intent_id) <= 128 or not all(
            char.isalnum() or char in "-_" for char in intent_id
        ):
            raise ValueError("订单标识无效。")
        with self.connection() as db:
            row = db.execute("SELECT intent_id,intent,result,unresolved,updated_at FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
            if row is None:
                raise ValueError("订单记录不存在。")
            summary = self._summaries([row], db)[0]
            raw_events = db.execute("SELECT sequence,at,stage,detail FROM order_events WHERE intent_id=? "
                                    "ORDER BY sequence DESC LIMIT 501", (intent_id,)).fetchall()
            complete = all(db.execute("SELECT 1 FROM order_events WHERE intent_id=? AND stage=? LIMIT 1",
                                      (intent_id, stage)).fetchone() for stage in ("submitting", "order_result"))
        truncated = len(raw_events) > 500
        raw_events = raw_events[:500]
        events = []
        for sequence, at, stage, detail in reversed(raw_events):
            try:
                metadata = json.loads(detail)
            except (ValueError, TypeError):
                metadata = {}
            official = stage == "order_result" and isinstance(metadata, dict) and metadata.get("official") is True
            result_status = metadata.get("status") if isinstance(metadata, dict) else None
            message = (STAGES.get(result_status, "订单页面核对结果") if stage == "order_result"
                       else EVENT_LABELS.get(stage, STAGES.get(stage, "本地处理记录")))
            events.append({"sequence": sequence, "at": at, "stage": stage,
                           "scope": "official" if official else "local", "message": message})
        return {"summary": summary, "events": events, "history_complete": complete, "events_truncated": truncated}

    def pending(self):
        with self.connection() as db:
            row = db.execute("SELECT intent,config,result,run_id,updated_at FROM orders WHERE unresolved=1").fetchone()
        if not row:
            return None
        return dict(intent=json.loads(row[0]), config=json.loads(row[1]), result=json.loads(row[2]),
                    run_id=row[3], updated_at=row[4])

    def submission_started(self, intent_id):
        with self.connection() as db:
            return bool(db.execute("SELECT 1 FROM order_events WHERE intent_id=? AND stage IN ('regular_submit','alternate_submit','resume_claimed') LIMIT 1", (intent_id,)).fetchone())

    def dismiss(self, intent_id):
        """Archive a user-dismissed review without claiming any official outcome."""
        lease = self._try_resume_lease()
        if lease is None:
            raise RuntimeError("订单正在恢复处理中，请等待任务结束后再操作。")
        try:
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT run_id,result FROM orders WHERE intent_id=? AND unresolved=1", (intent_id,)).fetchone()
                if not row:
                    raise ValueError("待核对记录已变化，请刷新后重试。")
                previous = json.loads(row[1])
                if previous.get("status") not in ("unknown", "verification"):
                    raise ValueError("仅可结束结果不明或需人工核验的记录；待支付订单请继续处理。")
                result = OrderResult("dismissed", "用户结束本地核对，官方订单状态未改变",
                                     order_id=previous.get("order_id", ""), evidence=previous.get("evidence", {}))
                db.execute("UPDATE orders SET result=?,unresolved=0,updated_at=? WHERE intent_id=?",
                           (json.dumps(result.payload(), ensure_ascii=False), time.time(), intent_id))
                db.execute("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)",
                           (row[0], intent_id, "dismissed", time.time(), time.monotonic(), '{"user_confirmed":true}'))
        finally:
            lease.close()

    def claim_resume(self, run_id, intent_id):
        with self._resume_guard:
            if self._resume_owner is not None:
                return False
            lease = self._try_resume_lease()
            if lease is None:
                return False
            try:
                with self.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE order_events SET stage='resume_released' WHERE stage='resume_claimed'")
                    if not db.execute("SELECT 1 FROM orders WHERE intent_id=? AND unresolved=1", (intent_id,)).fetchone():
                        return False
                    if db.execute("SELECT 1 FROM order_events WHERE intent_id=? AND stage IN ('regular_submit','alternate_submit') LIMIT 1", (intent_id,)).fetchone():
                        return False
                    db.execute("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)",
                               (run_id, intent_id, "resume_claimed", time.time(), time.monotonic(), "{}"))
                self._resume_owner = (run_id, intent_id, lease)
                return True
            finally:
                if self._resume_owner is None:
                    lease.close()

    def release_resume(self, run_id, intent_id):
        with self._resume_guard:
            if self._resume_owner is None or self._resume_owner[:2] != (run_id, intent_id):
                return
            try:
                with self.connection() as db:
                    db.execute("UPDATE order_events SET stage='resume_released' WHERE run_id=? AND intent_id=? AND stage='resume_claimed'", (run_id, intent_id))
            finally:
                self._resume_owner[2].close()
                self._resume_owner = None

    def mark(self, run_id, stage, intent_id="", detail=None):
        # Keep durable transaction markers ordered after any buffered query
        # telemetry without forcing every query click through SQLite.
        try:
            self.flush_telemetry()
        except sqlite3.Error:
            # Non-critical diagnostics must never prevent a durable submission
            # marker from making its own write attempt.
            pass
        with self.connection() as db:
            if stage in ("regular_submit", "alternate_submit"):
                db.execute("BEGIN IMMEDIATE")
                if not db.execute("SELECT 1 FROM orders WHERE intent_id=? AND unresolved=1", (intent_id,)).fetchone():
                    raise RuntimeError("提交意图已失效")
                if db.execute("SELECT 1 FROM order_events WHERE intent_id=? AND (stage IN ('regular_submit','alternate_submit') OR (stage='resume_claimed' AND run_id<>?)) LIMIT 1", (intent_id, run_id)).fetchone():
                    raise RuntimeError("提交已开始或由其他恢复任务持有，请核对原订单")
            cursor = db.execute("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)",
                                (run_id, intent_id, stage, time.time(), time.monotonic(), json.dumps(detail or {}, ensure_ascii=False)))
            return cursor.lastrowid

    def record_telemetry(self, run_id, stage, intent_id="", detail=None):
        """Buffer non-critical query timing events and persist them in batches."""
        if stage not in QUERY_TELEMETRY_STAGES:
            raise ValueError("仅查询遥测事件可以批量写入")
        event = (run_id, intent_id, stage, time.time(), time.monotonic(),
                 json.dumps(detail or {}, ensure_ascii=False))
        should_flush = False
        with self._telemetry_guard:
            self._telemetry_batch.append(event)
            if len(self._telemetry_batch) > self._telemetry_limit:
                self._telemetry_batch = self._telemetry_batch[-self._telemetry_limit:]
            should_flush = len(self._telemetry_batch) >= self._telemetry_batch_size
        if should_flush:
            try:
                self.flush_telemetry()
            except sqlite3.Error:
                return False
        return True

    def flush_telemetry(self):
        with self._telemetry_guard:
            if not self._telemetry_batch:
                return 0
            batch, self._telemetry_batch = self._telemetry_batch, []
        try:
            with self.connection() as db:
                db.executemany(
                    "INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)",
                    batch,
                )
                self._prune_telemetry(db)
        except Exception:
            with self._telemetry_guard:
                self._telemetry_batch = batch + self._telemetry_batch
            raise
        return len(batch)

    def _prune_telemetry(self, db):
        db.execute(
            """DELETE FROM order_events
               WHERE stage IN ('query_click','query_result')
                 AND sequence <= COALESCE((
                   SELECT sequence FROM order_events
                   WHERE stage IN ('query_click','query_result')
                   ORDER BY sequence DESC LIMIT 1 OFFSET ?
                 ), -1)""",
            (self._telemetry_limit,),
        )
