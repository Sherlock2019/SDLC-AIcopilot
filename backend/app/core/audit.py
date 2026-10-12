"""Audit log helpers. Everything an agent, a human or the pipeline does ends up here."""
import json

from sqlalchemy.orm import Session

from ..models import AuditLog, SystemFlag, utcnow
from . import secrets_scan


def summarize(value, limit: int = 220) -> str:
    """Short, secret-free, single-line description of an input or output."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    text, _ = secrets_scan.redact(" ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def record(db: Session, *, action: str, user: str = "", agent: str = "", actor_type: str = "", run_id=None,
           tool: str = "", input_summary="", output_summary="", policy_decision: str = "", approval: str = "",
           result: str = "", latency_ms: int = 0, tokens: int = 0, cost_usd: float = 0.0, tag: str = "") -> AuditLog:
    entry = AuditLog(
        ts=utcnow(), user=user, agent=agent, actor_type=actor_type, run_id=run_id, action=action, tool=tool,
        input_summary=summarize(input_summary), output_summary=summarize(output_summary),
        policy_decision=policy_decision, approval=approval, result=result, latency_ms=latency_ms,
        tokens=tokens, cost_usd=cost_usd, tag=tag,
    )
    db.add(entry)
    db.flush()
    return entry


def get_flags(db: Session) -> dict:
    flags = {"kill_switch": False, "dry_run": False}
    for row in db.query(SystemFlag).all():
        flags[row.key] = row.value
    return flags


def set_flag(db: Session, key: str, value, user: str) -> None:
    row = db.get(SystemFlag, key)
    if row is None:
        row = SystemFlag(key=key)
        db.add(row)
    row.value, row.updated_by, row.updated_at = value, user, utcnow()
    db.flush()
