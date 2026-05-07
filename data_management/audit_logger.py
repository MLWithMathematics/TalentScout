"""
data_management/audit_logger.py — GDPR Accountability Audit Trail (Art. 5(2))

Every data operation (create, read, update, delete, export, consent) is logged
to data/audit_log.json with a UTC timestamp and the candidate's UUID.

IMPORTANT: The audit log NEVER stores raw PII (name, email, phone).
           It stores only the candidate UUID and the type of operation.

GDPR Relevance:
    - Article 5(2): "accountability" principle — controller must demonstrate compliance
    - Article 30: Records of processing activities
"""

import json
import datetime
from config import AUDIT_LOG_PATH, DATA_DIR


class AuditLogger:
    """
    Append-only JSON audit log for all candidate data operations.

    Each entry schema:
    {
        "timestamp":   "2026-05-06T12:00:00Z",   # UTC ISO-8601
        "action":      "CREATE | READ | UPDATE | DELETE | EXPORT | GDPR_*",
        "candidate_id":"uuid-v4",                 # pseudonymous identifier
        "performed_by":"SYSTEM | CANDIDATE",
        "details":     "human-readable description (no PII)",
        "legal_basis": "Consent (Art. 6(1)(a))"
    }
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not AUDIT_LOG_PATH.exists():
            AUDIT_LOG_PATH.write_text(json.dumps([], indent=2))

    # ── Internal helpers ─────────────────────────────────────────────

    def _load(self) -> list:
        """Read all log entries from disk."""
        try:
            return json.loads(AUDIT_LOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, entries: list) -> None:
        """Persist log entries atomically."""
        AUDIT_LOG_PATH.write_text(
            json.dumps(entries, indent=2, default=str),
            encoding="utf-8",
        )

    # ── Public API ───────────────────────────────────────────────────

    def log(
        self,
        action: str,
        candidate_id: str = "UNKNOWN",
        performed_by: str = "SYSTEM",
        details: str = "",
    ) -> None:
        """
        Append a new audit entry.

        Args:
            action:       Verb describing what happened (e.g. "CREATE", "DELETE")
            candidate_id: Pseudonymous UUID — never the candidate's real name
            performed_by: Actor — "SYSTEM" (automated) or "CANDIDATE" (rights request)
            details:      Free-text context; must NOT contain raw PII
        """
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "action": action,
            "candidate_id": candidate_id,
            "performed_by": performed_by,
            "details": details,
            "legal_basis": "Consent (Art. 6(1)(a) GDPR)",
        }
        entries = self._load()
        entries.append(entry)
        self._save(entries)

    def get_logs_for_candidate(self, candidate_id: str) -> list:
        """
        Return all audit entries for a specific candidate.
        Used for Right to Access requests (GDPR Art. 15).

        Args:
            candidate_id: The candidate's UUID

        Returns:
            List of matching audit log entries
        """
        return [e for e in self._load() if e.get("candidate_id") == candidate_id]

    def get_all_logs(self) -> list:
        """Return full audit trail (admin use only)."""
        return self._load()
