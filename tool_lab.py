#!/usr/bin/env python3
"""Typed tool-boundary and durable idempotency lab reconstructed from the draft."""

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path


class IntentConflict(Exception):
    pass


class LostAfterCommit(Exception):
    pass


def initialize(db):
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE operations (
          tenant_id TEXT NOT NULL,
          tool_name TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          request_hash TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('pending','completed')),
          result_json TEXT,
          PRIMARY KEY (tenant_id, tool_name, idempotency_key)
        );
        CREATE TABLE tickets (
          ticket_id INTEGER PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          title TEXT NOT NULL,
          priority TEXT NOT NULL,
          operation_key TEXT NOT NULL
        );
        """)


def validate(value):
    fields = {"tenant_id", "idempotency_key", "title", "priority"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"arguments must contain exactly {sorted(fields)}")
    for field in ("tenant_id", "idempotency_key", "title"):
        if type(value[field]) is not str or not value[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if value["priority"] not in {"low", "medium", "high"}:
        raise ValueError("priority must be low, medium, or high")
    return {key: value[key].strip() for key in sorted(fields)}


def intent_hash(value):
    intent = {key: item for key, item in value.items() if key != "idempotency_key"}
    canonical = json.dumps(intent, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_ticket(db, raw, *, lose_result=False):
    value = validate(raw)
    digest = intent_hash(value)
    key = (value["tenant_id"], "create_ticket", value["idempotency_key"])
    conn = sqlite3.connect(db, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""
          SELECT request_hash, status, result_json FROM operations
          WHERE tenant_id=? AND tool_name=? AND idempotency_key=?
        """, key).fetchone()
        if row:
            if row[0] != digest:
                conn.rollback()
                raise IntentConflict("key is bound to different intent")
            if row[1] != "completed" or row[2] is None:
                conn.rollback()
                raise RuntimeError("operation has no atomic result")
            result = json.loads(row[2])
            conn.commit()
            return {**result, "disposition": "replayed"}
        conn.execute(
            "INSERT INTO operations VALUES (?,?,?,?, 'pending', NULL)",
            (*key, digest),
        )
        cursor = conn.execute("""
          INSERT INTO tickets(tenant_id,title,priority,operation_key)
          VALUES (?,?,?,?)
        """, (
            value["tenant_id"], value["title"], value["priority"],
            value["idempotency_key"],
        ))
        result = {
            "ticket_id": cursor.lastrowid,
            "tenant_id": value["tenant_id"],
            "title": value["title"],
            "priority": value["priority"],
        }
        conn.execute("""
          UPDATE operations SET status='completed', result_json=?
          WHERE tenant_id=? AND tool_name=? AND idempotency_key=?
        """, (json.dumps(result, sort_keys=True), *key))
        conn.commit()
        if lose_result:
            raise LostAfterCommit("synthetic connection loss after commit")
        return {**result, "disposition": "created"}
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def demo():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db = Path(handle.name)
    payload = {
        "tenant_id": "acme",
        "idempotency_key": "run-42:create-ticket",
        "title": "Restore search index",
        "priority": "high",
    }
    try:
        initialize(db)
        created = create_ticket(db, payload)
        replayed = create_ticket(db, payload)
        assert created["ticket_id"] == replayed["ticket_id"]
        try:
            create_ticket(db, {**payload, "title": "Delete search index"})
        except IntentConflict:
            pass
        else:
            raise AssertionError("changed intent was accepted")
        lost = {**payload, "idempotency_key": "run-43:create-ticket"}
        try:
            create_ticket(db, lost, lose_result=True)
        except LostAfterCommit:
            pass
        recovered = create_ticket(db, lost)
        with sqlite3.connect(db) as conn:
            counts = conn.execute(
                "SELECT (SELECT count(*) FROM operations),"
                "       (SELECT count(*) FROM tickets)"
            ).fetchone()
        assert counts == (2, 2)
        print({"created": created, "recovered": recovered, "counts": counts})
    finally:
        db.unlink(missing_ok=True)


if __name__ == "__main__":
    demo()

