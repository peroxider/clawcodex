"""Ledger DDL and schema migrations.

The ledger is the single source of truth for the solidification layer:
crystal_revision only ever INSERTs, never UPDATEs or DELETEs.
crystal_head is the only mutable state and can be fully rebuilt by replaying the ledger.

Migration strategy: advance one-way by PRAGMA user_version. Each new version appends a
_MIGRATIONS entry, and migrate() only executes the parts after user_version.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("memory-server.solidification")

SCHEMA_VERSION = 4

_DDL_V1 = """
-- Main ledger: INSERT only, never UPDATE / DELETE
CREATE TABLE IF NOT EXISTS crystal_revision (
  rev_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  crystal_id    TEXT    NOT NULL,
  parent_rev    INTEGER,
  batch_id      TEXT    NOT NULL,
  version       INTEGER NOT NULL,
  op            TEXT    NOT NULL,
  status        TEXT    NOT NULL,

  body          TEXT    NOT NULL,
  asset_json    TEXT    NOT NULL,
  facets_json   TEXT    NOT NULL,
  knowledge_type TEXT,
  asset_type    TEXT,
  subject       TEXT,
  confidence    REAL,
  source_ids_json TEXT,
  content_hash  TEXT    NOT NULL,

  valid_from    TEXT,
  valid_to      TEXT,
  recorded_at   TEXT    NOT NULL,

  actor         TEXT,
  rationale     TEXT,
  audit_json    TEXT,

  scope_json    TEXT,
  FOREIGN KEY (parent_rev) REFERENCES crystal_revision(rev_id)
);
CREATE INDEX IF NOT EXISTS idx_rev_crystal ON crystal_revision(crystal_id, rev_id);
CREATE INDEX IF NOT EXISTS idx_rev_batch   ON crystal_revision(batch_id);
CREATE INDEX IF NOT EXISTS idx_rev_hash    ON crystal_revision(content_hash);

-- Only mutable state: pointer to the current revision
CREATE TABLE IF NOT EXISTS crystal_head (
  crystal_id TEXT PRIMARY KEY,
  rev_id     INTEGER NOT NULL REFERENCES crystal_revision(rev_id),
  updated_at TEXT    NOT NULL
);

-- Cross-crystal relationships (merge / split / supersede)
CREATE TABLE IF NOT EXISTS crystal_lineage (
  rev_id          INTEGER NOT NULL REFERENCES crystal_revision(rev_id),
  from_crystal_id TEXT    NOT NULL,
  to_crystal_id   TEXT    NOT NULL,
  relation        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lineage_from ON crystal_lineage(from_crystal_id);
CREATE INDEX IF NOT EXISTS idx_lineage_to   ON crystal_lineage(to_crystal_id);

-- Graph projection edges (traversal enabled in phase five; phase one only persists deterministic derivation)
CREATE TABLE IF NOT EXISTS crystal_edge (
  edge_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  rev_id     INTEGER NOT NULL REFERENCES crystal_revision(rev_id),
  crystal_id TEXT    NOT NULL,
  subject    TEXT    NOT NULL,
  predicate  TEXT    NOT NULL,
  object     TEXT    NOT NULL,
  valid_from TEXT,
  valid_to   TEXT,
  status     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edge_subject ON crystal_edge(subject, status);
CREATE INDEX IF NOT EXISTS idx_edge_object  ON crystal_edge(object,  status);

-- Projection watermark: records up to which revision each projection has synced
CREATE TABLE IF NOT EXISTS projection_state (
  projection  TEXT PRIMARY KEY,
  through_rev INTEGER NOT NULL,
  updated_at  TEXT    NOT NULL
);
"""

PROJECTIONS = ("vector", "graph", "document")

_DDL_V2 = """
-- A legitimate batch rollback can leave a historical crystal temporarily without a head.
-- This marker belongs to the head projection; it stores no knowledge content, and only serves
-- to distinguish an intentional detachment from an accidentally lost head row.
CREATE TABLE IF NOT EXISTS crystal_head_detachment (
  crystal_id TEXT PRIMARY KEY,
  batch_id   TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detachment_batch
  ON crystal_head_detachment(batch_id);
"""

_DDL_V3 = """
-- Phase five queries always constrain edges by the current head rev_id first, then traverse by subject/predicate.
CREATE INDEX IF NOT EXISTS idx_edge_current
  ON crystal_edge(rev_id, subject, predicate);
"""

_DDL_V4 = """
-- Durable workflow for validity verification. It stores detection/evidence/leases but does not
-- define knowledge truth; the final conclusion exists only in crystal_revision.
CREATE TABLE IF NOT EXISTS verification_case (
  case_id              TEXT PRIMARY KEY,
  case_key             TEXT UNIQUE NOT NULL,
  case_type            TEXT NOT NULL,
  state                TEXT NOT NULL,
  priority             INTEGER NOT NULL,
  scope_json           TEXT NOT NULL,
  subject              TEXT,
  predicate            TEXT,
  left_crystal_id      TEXT,
  left_head_rev        INTEGER,
  right_crystal_id     TEXT,
  right_head_rev       INTEGER,
  trigger_rev_id       INTEGER,
  trigger_payload_json TEXT NOT NULL,
  policy_version       TEXT NOT NULL,
  evidence_round       INTEGER NOT NULL DEFAULT 0,
  decision_input_hash  TEXT,
  attempts             INTEGER NOT NULL DEFAULT 0,
  next_attempt_at      TEXT,
  lease_owner          TEXT,
  lease_until          TEXT,
  opened_rev_ids_json  TEXT NOT NULL DEFAULT '[]',
  result_rev_ids_json  TEXT,
  result_json          TEXT,
  last_error           TEXT,
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_case_queue
  ON verification_case(state, next_attempt_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_verification_case_scope
  ON verification_case(subject, predicate, state);

CREATE TABLE IF NOT EXISTS verification_evidence (
  evidence_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id          TEXT NOT NULL REFERENCES verification_case(case_id),
  collection_round INTEGER NOT NULL,
  source_kind      TEXT NOT NULL,
  source_ref       TEXT NOT NULL,
  observed_hash    TEXT NOT NULL,
  snapshot_json    TEXT NOT NULL,
  recorded_at      TEXT NOT NULL,
  UNIQUE(case_id, collection_round, source_kind, source_ref, observed_hash)
);
CREATE INDEX IF NOT EXISTS idx_verification_evidence_case
  ON verification_evidence(case_id, collection_round);

CREATE TABLE IF NOT EXISTS verification_cursor (
  detector    TEXT PRIMARY KEY,
  through_rev INTEGER NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_decision_cache (
  decision_input_hash TEXT PRIMARY KEY,
  result_json         TEXT NOT NULL,
  created_at          TEXT NOT NULL
);
"""

_MIGRATIONS = {1: _DDL_V1, 2: _DDL_V2, 3: _DDL_V3, 4: _DDL_V4}


def connect(db_path: str, *, timeout: float = 30.0) -> sqlite3.Connection:
    """Open a ledger connection.

    isolation_level=None means autocommit; transactions are explicitly controlled by the caller
    with BEGIN IMMEDIATE -- the mode required for "single writer + multiple readers" under WAL,
    avoiding Python sqlite3 implicitly opening transactions.
    """
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path), timeout=timeout, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=%d" % int(timeout * 1000))
    return conn


def migrate(conn: sqlite3.Connection, *, now: str) -> int:
    """Create tables incrementally by user_version. Returns the migrated schema version."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current >= SCHEMA_VERSION:
        return current
    for version in range(current + 1, SCHEMA_VERSION + 1):
        ddl = _MIGRATIONS.get(version)
        if ddl is None:
            raise RuntimeError(f"solidification: 缺少 schema v{version} 的迁移脚本")
        conn.executescript(ddl)
        conn.execute(f"PRAGMA user_version={version}")
        logger.info("固化层: 账本 schema 迁移到 v%d", version)
    for projection in PROJECTIONS:
        conn.execute(
            "INSERT OR IGNORE INTO projection_state(projection, through_rev, updated_at)"
            " VALUES (?, 0, ?)",
            (projection, now),
        )
    return SCHEMA_VERSION
