"""Simulated environments: DEV, TEST, STAGING and PRODUCTION (simulation only).

Nothing is deployed anywhere. A deployment is a row in the deployments table, which is enough to
demonstrate promotion, health checks, approval gates and rollback without any real infrastructure.
"""
from sqlalchemy.orm import Session

from ..models import Deployment, Incident, to_dict

ENVIRONMENTS = ["DEV", "TEST", "STAGING", "PRODUCTION"]
LABELS = {"DEV": "DEV", "TEST": "TEST", "STAGING": "STAGING", "PRODUCTION": "PRODUCTION-SIMULATION"}


def history(db: Session, env: str | None = None, limit: int = 30) -> list[Deployment]:
    query = db.query(Deployment)
    if env:
        query = query.filter(Deployment.env == env)
    return query.order_by(Deployment.ts.desc(), Deployment.id.desc()).limit(limit).all()


def current(db: Session, env: str) -> Deployment | None:
    rows = history(db, env, 1)
    return rows[0] if rows else None


def previous_version(db: Session, env: str) -> str | None:
    rows = history(db, env, 20)
    if not rows:
        return None
    return next((row.version for row in rows[1:] if row.version != rows[0].version), None)


def deploy(db: Session, env: str, version: str, by: str, approved_by: str = "", run_id=None, notes: str = "",
           kind: str = "deploy", data: dict | None = None) -> Deployment:
    if env not in ENVIRONMENTS:
        raise ValueError(f"Unknown environment '{env}'.")
    row = Deployment(env=env, version=version, deployed_by=by, approved_by=approved_by, run_id=run_id,
                     notes=notes, kind=kind, data=data or {}, status="healthy")
    db.add(row)
    db.flush()
    return row


def rollback(db: Session, env: str, by: str, approved_by: str = "", run_id=None, notes: str = "") -> Deployment:
    target = previous_version(db, env)
    if target is None:
        raise ValueError(f"{env} has no earlier version to roll back to.")
    return deploy(db, env, target, by, approved_by, run_id, notes or "Rollback to previous build", kind="rollback")


def open_incident(db: Session) -> Incident | None:
    return db.query(Incident).filter(Incident.status == "open", Incident.simulated.is_(True),
                                     Incident.run_id.isnot(None)).order_by(Incident.id.desc()).first()


def health(db: Session, env: str) -> dict:
    row = current(db, env)
    if row is None:
        return {"env": env, "status": "empty", "version": None, "checks": []}
    degraded = env == "PRODUCTION" and open_incident(db) is not None
    return {
        "env": env, "label": LABELS[env], "version": row.version,
        "status": "degraded" if degraded else "healthy",
        "checks": [
            {"name": "GET /health returns 200", "ok": True},
            {"name": f"Reported version is {row.version}", "ok": True},
            {"name": "Error rate below 1%", "ok": not degraded},
        ],
    }


def environments(db: Session) -> list[dict]:
    out = []
    for env in ENVIRONMENTS:
        row = current(db, env)
        out.append({
            "env": env, "label": LABELS[env], "simulation": True,
            "version": row.version if row else None,
            "deployed_at": to_dict(row)["ts"] if row else None,
            "deployed_by": row.deployed_by if row else None,
            "approved_by": row.approved_by if row else "",
            "last_kind": row.kind if row else None,
            "previous_version": previous_version(db, env),
            "health": health(db, env)["status"],
            "requires_approval": env == "PRODUCTION",
        })
    return out
