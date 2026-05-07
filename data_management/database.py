"""
data_management/database.py — GDPR-Compliant SQLite & PostgreSQL Storage

Schema design:
  - PII columns (name, email, phone) are stored ENCRYPTED via Fernet.
  - All other columns are plain-text (non-PII).
  - Auto-deletion at data_retention_until timestamp (GDPR data minimisation).
  - Full GDPR rights support:
      Right to Access       → get_candidate()
      Right to Rectification→ update_candidate()
      Right to Erasure      → delete_candidate()
      Right to Portability  → export_candidate_csv()
      Art. 22 Human Review  → request_human_review()

GDPR Articles covered:
    Art. 5(1)(e): Storage limitation — 90-day retention enforced at startup
    Art. 17:      Right to erasure implemented
    Art. 20:      Data portability (CSV export)
    Art. 22:      Human review flag per candidate
    Art. 25:      Privacy by design — encrypt at rest, minimise fields
    Art. 32:      Security of processing — Fernet encryption
"""

import csv
import io
import json
import sqlite3
import datetime
import uuid
import os
from typing import Any, Dict, List, Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

from config import DATA_DIR, DATA_RETENTION_DAYS, DB_PATH, PII_FIELDS
from data_management.encryption import EncryptionManager
from data_management.audit_logger import AuditLogger


class CandidateDatabase:
    """
    Database for candidate data with field-level PII encryption.
    Supports both SQLite (local) and PostgreSQL (Neon/Render).

    Column naming convention:
      *_enc  — Fernet-encrypted ciphertext (PII fields)
      *      — Plain text (non-PII fields)
    """

    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.is_postgres = bool(self.db_url and self.db_url.startswith("postgres"))
        
        if not self.is_postgres:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            
        if self.is_postgres and psycopg2 is None:
            raise ImportError("DATABASE_URL is set, but psycopg2 is not installed. Run: pip install psycopg2-binary")

        self.enc = EncryptionManager()
        self.audit = AuditLogger()
        self._init_schema()
        self._purge_expired_records()  # GDPR Art. 5(1)(e): storage limitation

    # ── Database Abstraction ─────────────────────────────────────────

    def _execute(self, query: str, params: tuple = ()) -> None:
        if self.is_postgres:
            query = query.replace("?", "%s")
            with psycopg2.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
        else:
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.execute(query, params)

    def _query_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        if self.is_postgres:
            query = query.replace("?", "%s")
            with psycopg2.connect(self.db_url) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    row = cur.fetchone()
                    return dict(row) if row else None
        else:
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None

    def _query_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        if self.is_postgres:
            query = query.replace("?", "%s")
            with psycopg2.connect(self.db_url) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    return [dict(r) for r in cur.fetchall()]
        else:
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]

    # ── Schema ───────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create tables if they don't exist yet."""
        self._execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id            TEXT PRIMARY KEY,
                full_name_enc           TEXT,
                email_enc               TEXT,
                phone_enc               TEXT,
                years_experience        TEXT,
                desired_position        TEXT,
                current_location        TEXT,
                tech_stack              TEXT,
                qa_responses            TEXT,
                ai_decision_explanation TEXT,
                status                  TEXT DEFAULT 'SCREENING',
                consent_given           INTEGER DEFAULT 0,
                consent_timestamp       TEXT,
                consent_ip_hash         TEXT,
                data_retention_until    TEXT,
                deletion_requested      INTEGER DEFAULT 0,
                human_review_requested  INTEGER DEFAULT 0,
                created_at              TEXT,
                updated_at              TEXT
            )
        """)
        self._execute("""
            CREATE TABLE IF NOT EXISTS gdpr_requests (
                request_id      TEXT PRIMARY KEY,
                candidate_id    TEXT,
                request_type    TEXT,
                requested_at    TEXT,
                deadline_at     TEXT,
                fulfilled_at    TEXT,
                status          TEXT DEFAULT 'PENDING',
                notes           TEXT
            )
        """)

    # ── Internal helpers ─────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.datetime.utcnow().isoformat() + "Z"

    def _retention_deadline(self) -> str:
        return (
            datetime.datetime.utcnow()
            + datetime.timedelta(days=DATA_RETENTION_DAYS)
        ).isoformat() + "Z"

    def _row_to_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt PII fields and parse JSON for a given row dict."""
        data = dict(row)
        # Decrypt PII columns
        data["full_name"] = self.enc.decrypt(data.pop("full_name_enc", "") or "")
        data["email"] = self.enc.decrypt(data.pop("email_enc", "") or "")
        data["phone"] = self.enc.decrypt(data.pop("phone_enc", "") or "")
        # Parse JSON columns
        for col in ("tech_stack", "qa_responses"):
            raw = data.get(col)
            if raw:
                try:
                    data[col] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass
        return data

    # ── CRUD ─────────────────────────────────────────────────────────

    def create_candidate(self, consent: bool = True) -> str:
        """
        Insert a new candidate skeleton row and return their UUID.
        Consent timestamp is recorded for GDPR Art. 7 compliance.
        """
        cid = str(uuid.uuid4())
        now = self._now()
        self._execute(
            """INSERT INTO candidates
               (candidate_id, consent_given, consent_timestamp,
                data_retention_until, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cid, int(consent), now if consent else None,
             self._retention_deadline(), now, now),
        )
        self.audit.log("CREATE", cid, "SYSTEM",
                       "Candidate record created; consent recorded")
        return cid

    def update_candidate(self, candidate_id: str, field: str, value: Any) -> None:
        """
        Update a single field for an existing candidate.
        PII fields are encrypted before writing.
        """
        if field in PII_FIELDS:
            col = f"{field}_enc"
            db_value = self.enc.encrypt(str(value))
            log_detail = f"Updated encrypted field: {field}"
        elif field == "tech_stack" and isinstance(value, list):
            col = "tech_stack"
            db_value = json.dumps(value)
            log_detail = "Updated tech_stack"
        else:
            col = field
            db_value = value
            log_detail = f"Updated field: {field}"

        now = self._now()
        self._execute(
            f"UPDATE candidates SET {col} = ?, updated_at = ? WHERE candidate_id = ?",
            (db_value, now, candidate_id),
        )
        self.audit.log("UPDATE", candidate_id, "SYSTEM", log_detail)

    def update_qa_responses(self, candidate_id: str, qa_list: list) -> None:
        """Persist the full Q&A log for a candidate."""
        now = self._now()
        self._execute(
            "UPDATE candidates SET qa_responses = ?, updated_at = ? WHERE candidate_id = ?",
            (json.dumps(qa_list), now, candidate_id),
        )
        self.audit.log("UPDATE", candidate_id, "SYSTEM",
                       f"Q&A responses updated ({len(qa_list)} entries)")

    def get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve and decrypt a candidate record.
        GDPR Art. 15: Right of access — candidate can see everything stored.
        """
        row = self._query_one(
            "SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)
        )

        if not row:
            return None

        self.audit.log("READ", candidate_id, "SYSTEM",
                       "Full candidate record accessed")
        return self._row_to_dict(row)

    # ── GDPR Rights ──────────────────────────────────────────────────

    def delete_candidate(self, candidate_id: str) -> bool:
        """
        GDPR Art. 17 — Right to Erasure ("Right to be Forgotten").
        Permanently removes all rows from candidates and gdpr_requests tables.
        Audit entry is written BEFORE deletion (legal requirement).
        """
        self.audit.log(
            "DELETE", candidate_id, "CANDIDATE",
            "Right to Erasure invoked — all data permanently deleted from DB"
        )
        self._execute("DELETE FROM candidates WHERE candidate_id = ?", (candidate_id,))
        self._execute("DELETE FROM gdpr_requests WHERE candidate_id = ?", (candidate_id,))
        return True

    def export_candidate_csv(self, candidate_id: str) -> str:
        """
        GDPR Art. 20 — Right to Data Portability.
        Returns a machine-readable CSV string of the candidate's data.
        """
        data = self.get_candidate(candidate_id)
        if not data:
            return ""

        self.audit.log("EXPORT", candidate_id, "CANDIDATE",
                       "Data portability export generated (CSV)")

        exportable_fields = [
            "candidate_id", "full_name", "email", "phone",
            "years_experience", "desired_position", "current_location",
            "tech_stack", "consent_given", "consent_timestamp",
            "data_retention_until", "status", "created_at",
        ]

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=exportable_fields, extrasaction="ignore")
        writer.writeheader()

        row = {k: data.get(k, "") for k in exportable_fields}
        if isinstance(row.get("tech_stack"), list):
            row["tech_stack"] = ", ".join(row["tech_stack"])
        writer.writerow(row)

        return buf.getvalue()

    def rectify_candidate(self, candidate_id: str,
                          field: str, new_value: str) -> None:
        """
        GDPR Art. 16 — Right to Rectification.
        Correct inaccurate personal data.
        """
        self.update_candidate(candidate_id, field, new_value)
        self.log_gdpr_request(candidate_id, "RECTIFICATION",
                              notes=f"Field '{field}' corrected by candidate")
        self.audit.log("RECTIFY", candidate_id, "CANDIDATE",
                       f"Rectification applied to field: {field}")

    def request_human_review(self, candidate_id: str) -> None:
        """
        GDPR Art. 22 — Right not to be subject to solely automated decisions.
        Flags record for human recruiter review.
        """
        self._execute(
            "UPDATE candidates SET human_review_requested = 1 WHERE candidate_id = ?",
            (candidate_id,),
        )
        self.audit.log("HUMAN_REVIEW_REQUEST", candidate_id, "CANDIDATE",
                       "Art. 22 human review flagged — recruiter will review within 30 days")

    def log_gdpr_request(self, candidate_id: str, request_type: str,
                         notes: str = "") -> str:
        """
        Officially log a GDPR rights request to the gdpr_requests table.
        Must be fulfilled within 30 days (Art. 12).
        Returns the request UUID.
        """
        request_id = str(uuid.uuid4())
        now = self._now()
        deadline = (
            datetime.datetime.utcnow()
            + datetime.timedelta(days=30)
        ).isoformat() + "Z"

        self._execute(
            """INSERT INTO gdpr_requests
               (request_id, candidate_id, request_type,
                requested_at, deadline_at, status, notes)
               VALUES (?, ?, ?, ?, ?, 'PENDING', ?)""",
            (request_id, candidate_id, request_type, now, deadline, notes),
        )
        self.audit.log(
            f"GDPR_{request_type}", candidate_id, "CANDIDATE",
            f"GDPR {request_type} request logged (deadline: {deadline})"
        )
        return request_id

    def get_gdpr_requests(self, candidate_id: str) -> List[Dict]:
        """Return all pending/fulfilled GDPR requests for a candidate."""
        return self._query_all(
            "SELECT * FROM gdpr_requests WHERE candidate_id = ?", (candidate_id,)
        )

    # ── Data Minimisation ────────────────────────────────────────────

    def _purge_expired_records(self) -> None:
        """
        GDPR Art. 5(1)(e): Storage limitation.
        Auto-delete candidate records past their retention date.
        Runs once at startup.
        """
        now = self._now()
        expired = self._query_all(
            "SELECT candidate_id FROM candidates WHERE data_retention_until < ?",
            (now,),
        )

        for row in expired:
            cid = row["candidate_id"]
            self.audit.log(
                "AUTO_DELETE", cid, "SYSTEM",
                f"Record auto-purged after {DATA_RETENTION_DAYS}-day retention window"
            )
            self._execute("DELETE FROM candidates WHERE candidate_id = ?", (cid,))
            self._execute("DELETE FROM gdpr_requests WHERE candidate_id = ?", (cid,))
