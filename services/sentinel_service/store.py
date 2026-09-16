"""
Sentinel SQLite storage layer.
Thread-safe error and service-status persistence with WAL mode,
fingerprinting, incident grouping, secret masking, and rotation.
"""

import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.models.sentinel import (
    ErrorRecord,
    ErrorReport,
    ErrorSeverity,
    IncidentSummary,
    ServiceStatusEvent,
)

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = _BASE_DIR / "memory" / "sentinel.db"

INCIDENT_WINDOW_SEC = 30
RETENTION_DAYS = 7
MAX_ROWS = 50_000

# ── Secret masking ────────────────────────────────────────────────────────────

_SENSITIVE_KEYS = re.compile(
    r"(api_key|gemini_api_key|token|authorization|password|secret|access_key)",
    re.IGNORECASE,
)

# Matches long hex/base64 strings that look like API keys (32+ chars, alphanumeric + special)
_LOOKS_LIKE_KEY = re.compile(r"[A-Za-z0-9_\-]{32,}")


def _mask_value(value: str) -> str:
    """Mask a single string value if it looks like a secret."""
    if _LOOKS_LIKE_KEY.fullmatch(value.strip()):
        return "***MASKED***"
    return value


def _mask_secrets_in_str(text: str) -> str:
    """Mask secrets embedded in free text (message / traceback)."""
    if not text:
        return text
    # Mask key=value patterns
    text = re.sub(
        r"""(?i)(api_key|gemini_api_key|token|authorization|password|secret|access_key)\s*[=:]\s*['"]?([^\s'",:}{]{8,})""",
        r"\1=***MASKED***",
        text,
    )
    return text


def _mask_dict(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Deep-mask sensitive values in a dict."""
    if not d:
        return d
    out = {}
    for k, v in d.items():
        if _SENSITIVE_KEYS.search(k):
            out[k] = "***MASKED***"
        elif isinstance(v, str):
            out[k] = _mask_value(v)
        elif isinstance(v, dict):
            out[k] = _mask_dict(v)
        else:
            out[k] = v
    return out


# ── Fingerprint ───────────────────────────────────────────────────────────────

# Patterns to strip from messages so similar errors collapse
_NORM_PATTERNS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d]*\b"), "<TS>"),
    (re.compile(r"[A-Za-z]:\\[^\s:\"']+"), "<PATH>"),  # Windows paths
    (re.compile(r"/[^\s:\"']+"), "<PATH>"),  # Unix paths
    (re.compile(r"\b\d+\b"), "<N>"),
]


def _normalize_message(msg: str) -> str:
    for pat, repl in _NORM_PATTERNS:
        msg = pat.sub(repl, msg)
    return msg


def _make_fingerprint(service: str, severity: str, source: str, message: str) -> str:
    norm = _normalize_message(message)
    raw = f"{service}|{severity}|{source}|{norm}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


# ── Store ─────────────────────────────────────────────────────────────────────

class SentinelStore:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS errors (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                received_ts REAL    NOT NULL,
                service     TEXT    NOT NULL,
                severity    TEXT    NOT NULL,
                source      TEXT    NOT NULL,
                message     TEXT    NOT NULL,
                traceback   TEXT,
                correlation_id TEXT,
                context     TEXT,
                fingerprint TEXT    NOT NULL,
                incident_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_errors_ts            ON errors(ts);
            CREATE INDEX IF NOT EXISTS idx_errors_service       ON errors(service);
            CREATE INDEX IF NOT EXISTS idx_errors_correlation_id ON errors(correlation_id);
            CREATE INDEX IF NOT EXISTS idx_errors_fingerprint   ON errors(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_errors_incident_id   ON errors(incident_id);

            CREATE TABLE IF NOT EXISTS service_status (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      REAL    NOT NULL,
                service TEXT    NOT NULL,
                status  TEXT    NOT NULL,
                detail  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_status_ts      ON service_status(ts);
            CREATE INDEX IF NOT EXISTS idx_status_service  ON service_status(service);
        """)
        self._conn.commit()

    # ── Incident assignment ───────────────────────────────────────────────────

    def _assign_incident_id(self, ts: float) -> str:
        row = self._conn.execute(
            "SELECT incident_id, ts FROM errors ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row and row["incident_id"] and (ts - row["ts"]) < INCIDENT_WINDOW_SEC:
            return row["incident_id"]
        return uuid.uuid4().hex[:12]

    # ── Write ─────────────────────────────────────────────────────────────────

    def insert_error(self, report: ErrorReport) -> ErrorRecord:
        now = time.time()
        # Mask secrets
        msg = _mask_secrets_in_str(report.message)
        tb = _mask_secrets_in_str(report.traceback) if report.traceback else None
        ctx = _mask_dict(report.context)
        ctx_json = json.dumps(ctx, ensure_ascii=False) if ctx else None

        fp = _make_fingerprint(report.service, report.severity.value, report.source, report.message)
        inc_id = self._assign_incident_id(report.ts or now)

        cur = self._conn.execute(
            """INSERT INTO errors
               (ts, received_ts, service, severity, source, message,
                traceback, correlation_id, context, fingerprint, incident_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.ts or now,
                now,
                report.service,
                report.severity.value,
                report.source,
                msg,
                tb,
                report.correlation_id,
                ctx_json,
                fp,
                inc_id,
            ),
        )
        self._conn.commit()

        return ErrorRecord(
            id=cur.lastrowid or 0,
            ts=report.ts or now,
            received_ts=now,
            service=report.service,
            severity=report.severity,
            source=report.source,
            message=msg,
            traceback=tb,
            correlation_id=report.correlation_id,
            context=ctx,
            fingerprint=fp,
            incident_id=inc_id,
        )

    def insert_error_batch(self, reports: List[ErrorReport]) -> List[ErrorRecord]:
        records = []
        for r in reports:
            records.append(self.insert_error(r))
        return records

    def insert_status(self, event: ServiceStatusEvent):
        self._conn.execute(
            "INSERT INTO service_status (ts, service, status, detail) VALUES (?, ?, ?, ?)",
            (event.ts, event.service, event.status, event.detail),
        )
        self._conn.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def _row_to_record(self, row: sqlite3.Row) -> ErrorRecord:
        ctx = None
        if row["context"]:
            try:
                ctx = json.loads(row["context"])
            except Exception:
                ctx = {"raw": row["context"]}
        return ErrorRecord(
            id=row["id"],
            ts=row["ts"],
            received_ts=row["received_ts"],
            service=row["service"],
            severity=row["severity"],
            source=row["source"],
            message=row["message"],
            traceback=row["traceback"],
            correlation_id=row["correlation_id"],
            context=ctx,
            fingerprint=row["fingerprint"],
            incident_id=row["incident_id"],
        )

    def query_errors(
        self,
        service: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[float] = None,
        correlation_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        group: bool = False,
    ) -> list:
        clauses, params = [], []
        if service:
            clauses.append("service = ?")
            params.append(service)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if correlation_id:
            clauses.append("correlation_id = ?")
            params.append(correlation_id)
        if incident_id:
            clauses.append("incident_id = ?")
            params.append(incident_id)
        if search:
            clauses.append("message LIKE ?")
            params.append(f"%{search}%")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        if group:
            sql = f"""
                SELECT fingerprint, service, severity, source,
                       message, MAX(ts) as ts, MIN(ts) as first_ts,
                       COUNT(*) as cnt, correlation_id, incident_id
                FROM errors {where}
                GROUP BY fingerprint
                ORDER BY ts DESC
                LIMIT ?
            """
            params.append(limit)
            rows = self._conn.execute(sql, params).fetchall()
            results = []
            for r in rows:
                results.append({
                    "fingerprint": r["fingerprint"],
                    "service": r["service"],
                    "severity": r["severity"],
                    "source": r["source"],
                    "message": r["message"],
                    "ts": r["ts"],
                    "first_ts": r["first_ts"],
                    "count": r["cnt"],
                    "correlation_id": r["correlation_id"],
                    "incident_id": r["incident_id"],
                })
            return results

        sql = f"SELECT * FROM errors {where} ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_trace(self, correlation_id: str) -> List[ErrorRecord]:
        rows = self._conn.execute(
            "SELECT * FROM errors WHERE correlation_id = ? ORDER BY ts ASC",
            (correlation_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_incidents(self, limit: int = 50) -> List[IncidentSummary]:
        rows = self._conn.execute(
            """SELECT incident_id, MIN(ts) as started, MAX(ts) as ended,
                      COUNT(*) as cnt, MAX(severity) as sev
               FROM errors
               WHERE incident_id IS NOT NULL
               GROUP BY incident_id
               ORDER BY started DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        results = []
        for r in rows:
            # Fetch services involved
            svc_rows = self._conn.execute(
                "SELECT DISTINCT service FROM errors WHERE incident_id = ?",
                (r["incident_id"],),
            ).fetchall()
            services = [s["service"] for s in svc_rows]

            # Root cause: earliest CRITICAL/ERROR event; health_monitor prioritized
            root_row = self._conn.execute(
                """SELECT * FROM errors
                   WHERE incident_id = ? AND severity IN ('CRITICAL', 'ERROR')
                   ORDER BY ts ASC, CASE WHEN source = 'health_monitor' THEN 0 ELSE 1 END
                   LIMIT 1""",
                (r["incident_id"],),
            ).fetchone()

            root_cause = self._row_to_record(root_row) if root_row else None

            # Determine overall severity
            sev = ErrorSeverity.ERROR
            if r["sev"] == "CRITICAL":
                sev = ErrorSeverity.CRITICAL
            elif r["sev"] == "WARNING":
                sev = ErrorSeverity.WARNING

            results.append(IncidentSummary(
                incident_id=r["incident_id"],
                started_ts=r["started"],
                ended_ts=r["ended"],
                services=services,
                root_cause=root_cause,
                error_count=r["cnt"],
                severity=sev,
            ))
        return results

    def get_incident(self, incident_id: str) -> Optional[dict]:
        events = self._conn.execute(
            "SELECT * FROM errors WHERE incident_id = ? ORDER BY ts ASC",
            (incident_id,),
        ).fetchall()
        if not events:
            return None

        records = [self._row_to_record(r) for r in events]

        # Root cause
        root = None
        for rec in records:
            if rec.severity in (ErrorSeverity.CRITICAL, ErrorSeverity.ERROR):
                if root is None:
                    root = rec
                elif rec.ts < root.ts:
                    root = rec
                elif rec.ts == root.ts and rec.source == "health_monitor":
                    root = rec

        svc_rows = self._conn.execute(
            "SELECT DISTINCT service FROM errors WHERE incident_id = ?",
            (incident_id,),
        ).fetchall()

        return {
            "incident_id": incident_id,
            "events": [r.model_dump() for r in records],
            "root_cause": root.model_dump() if root else None,
            "services": [s["service"] for s in svc_rows],
            "error_count": len(records),
        }

    def get_stats(self, window_sec: int = 3600) -> dict:
        now = time.time()
        cutoff_1h = now - 3600
        cutoff_24h = now - 86400

        # Counts by severity (last hour)
        hour_rows = self._conn.execute(
            """SELECT severity, COUNT(*) as cnt
               FROM errors WHERE ts >= ?
               GROUP BY severity""",
            (cutoff_1h,),
        ).fetchall()
        by_severity_1h = {r["severity"]: r["cnt"] for r in hour_rows}

        # Counts by severity (last 24h)
        day_rows = self._conn.execute(
            """SELECT severity, COUNT(*) as cnt
               FROM errors WHERE ts >= ?
               GROUP BY severity""",
            (cutoff_24h,),
        ).fetchall()
        by_severity_24h = {r["severity"]: r["cnt"] for r in day_rows}

        # Counts by service (last hour)
        svc_rows = self._conn.execute(
            """SELECT service, COUNT(*) as cnt
               FROM errors WHERE ts >= ?
               GROUP BY service""",
            (cutoff_1h,),
        ).fetchall()
        by_service_1h = {r["service"]: r["cnt"] for r in svc_rows}

        # Latest status per service
        status_rows = self._conn.execute(
            """SELECT service, status, ts FROM service_status
               WHERE id IN (
                   SELECT MAX(id) FROM service_status GROUP BY service
               )"""
        ).fetchall()
        statuses = {r["service"]: {"status": r["status"], "ts": r["ts"]} for r in status_rows}

        return {
            "by_severity_1h": by_severity_1h,
            "by_severity_24h": by_severity_24h,
            "by_service_1h": by_service_1h,
            "service_statuses": statuses,
            "total_1h": sum(by_severity_1h.values()),
            "total_24h": sum(by_severity_24h.values()),
        }

    def clear_all(self):
        self._conn.execute("DELETE FROM errors")
        self._conn.execute("DELETE FROM service_status")
        self._conn.commit()

    # ── Rotation ──────────────────────────────────────────────────────────────

    def rotate(self):
        """Delete old entries. Called periodically (e.g. every hour)."""
        cutoff = time.time() - (RETENTION_DAYS * 86400)
        self._conn.execute("DELETE FROM errors WHERE ts < ?", (cutoff,))

        # Hard cap on row count
        count = self._conn.execute("SELECT COUNT(*) as c FROM errors").fetchone()["c"]
        if count > MAX_ROWS:
            excess = count - MAX_ROWS
            self._conn.execute(
                "DELETE FROM errors WHERE id IN (SELECT id FROM errors ORDER BY ts ASC LIMIT ?)",
                (excess,),
            )

        # Clean old status entries too (keep last 7 days)
        self._conn.execute("DELETE FROM service_status WHERE ts < ?", (cutoff,))
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
