"""Transaction evidence and durable single-account submission ownership."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import sqlite3
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
}
TERMINAL = {"sold_out", "not_submitted", "fulfilled", "cancelled", "expired", "failed"}


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
    # True only after an explicit pre-submit rejection or a completed empty pending-order view.
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
    def __init__(self, filename):
        self.filename = str(filename)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    intent_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, intent TEXT NOT NULL,
                    config TEXT NOT NULL, result TEXT NOT NULL, unresolved INTEGER NOT NULL,
                    updated_at REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_unresolved ON orders(unresolved) WHERE unresolved=1;
                CREATE TABLE IF NOT EXISTS order_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, intent_id TEXT,
                    stage TEXT NOT NULL, at REAL NOT NULL, monotonic REAL NOT NULL, detail TEXT NOT NULL);
            """)

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
            if result.status in ("sold_out", "not_submitted") and (not result.no_order or previous.get("order_id")):
                result = OrderResult("unknown", "尚未确认没有已创建的订单")
            if result.status in ("unknown", "verification") and previous.get("order_id"):
                result = replace(result, order_id=previous["order_id"], evidence=previous.get("evidence", {}))
            unresolved = result.status not in TERMINAL
            updated = db.execute("UPDATE orders SET result=?,unresolved=?,updated_at=? WHERE intent_id=?", (
                json.dumps(result.payload(), ensure_ascii=False), int(unresolved), time.time(), intent.intent_id))
            if updated.rowcount != 1:
                raise RuntimeError("订单意图尚未持久化，不能确认结果")
        return result

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

    def claim_resume(self, run_id, intent_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM orders WHERE intent_id=? AND unresolved=1", (intent_id,)).fetchone():
                return False
            if db.execute("SELECT 1 FROM order_events WHERE intent_id=? AND stage IN ('regular_submit','alternate_submit','resume_claimed') LIMIT 1", (intent_id,)).fetchone():
                return False
            db.execute("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)",
                       (run_id, intent_id, "resume_claimed", time.time(), time.monotonic(), "{}"))
            return True

    def release_resume(self, run_id, intent_id):
        with self.connection() as db:
            db.execute("UPDATE order_events SET stage='resume_released' WHERE run_id=? AND intent_id=? AND stage='resume_claimed'", (run_id, intent_id))

    def mark(self, run_id, stage, intent_id="", detail=None):
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
