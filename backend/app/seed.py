"""Seed data so the lab looks alive immediately after installation.

Everything written here is flagged `simulated=True` and labelled SIMULATED in the UI. The live
demo run starts empty: its numbers are produced by actually running the workflow.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from . import services
from .config import settings
from .models import (AgentRun, AuditLog, Deployment, Evaluation, GithubIntegration, Incident, Metric, Pipeline,
                     Policy, Project, SecurityFinding, User, WorkflowRun, utcnow)

DEFAULT_REQUIREMENT = "Add a secure password-reset workflow to the customer portal."
USERS = [
    ("dana", "Dana Whitfield", "AI Champion (all roles, for demos)",
     ["engineer", "architect", "release_manager", "sre", "security_admin", "product_owner"]),
    ("alex", "Alex Romero", "Software Engineer", ["engineer"]),
    ("priya", "Priya Natarajan", "Solution Architect", ["architect"]),
    ("sam", "Sam Okafor", "Release Manager / on-call SRE", ["release_manager", "sre"]),
    ("morgan", "Morgan Lindqvist", "Security Engineer", ["security_admin"]),
    ("pat", "Pat Delacroix", "Product Owner", ["product_owner"]),
]
PRODUCTIVITY = [
    ("cycle_time", "Cycle time (requirement to merged)", 260, 58, "min", "lower"),
    ("test_coverage", "Test coverage", 62, 86, "%", "higher"),
    ("pr_review_time", "PR review time", 45, 12, "min", "lower"),
    ("manual_steps", "Manual steps per feature", 18, 7, "steps", "lower"),
    ("mttr", "Mean time to restore", 70, 25, "min", "lower"),
    ("defects", "Defects found after merge (per 10 features)", 6, 3, "defects", "lower"),
]
DORA = [
    ("deployment_frequency", "Deployment Frequency", 2, 5, "per week", "higher"),
    ("lead_time", "Lead Time for Changes", 77, 26, "hours", "lower"),
    ("change_failure_rate", "Change Failure Rate", 18, 11, "%", "lower"),
    ("time_to_restore", "Mean Time to Restore", 70, 25, "min", "lower"),
]
HISTORY = [
    ("Add request-id header to all responses", 9, 94.0, 31),
    ("Return 429 with Retry-After on login rate limit", 6, 91.5, 44),
    ("Add GET /profile response caching headers", 3, 88.0, 27),
]
AGENT_SEQUENCE = ["requirement-agent", "architecture-agent", "coding-agent", "test-agent", "review-agent",
                  "deployment-advisor"]


def new_run(db: Session, requirement: str, user: str, prompt_version: str = "v2", model: str = "") -> WorkflowRun:
    title = requirement.strip().rstrip(".")
    title = title[:1].upper() + title[1:]
    if len(title) > 70:
        title = title[:67] + "..."
    project = db.query(Project).first()
    run = WorkflowRun(project_id=project.id if project else None, title=title, requirement_text=requirement.strip(),
                      prompt_version=prompt_version, model=model, created_by=user, artifacts={})
    db.add(run)
    db.flush()
    return run


def load_scenario(db: Session, name: str, user: str) -> None:
    """Activate a policy scenario for the coding agent ('unsafe' or 'recommended') and persist it."""
    store = services.get_store()
    db.query(Policy).filter(Policy.agent == "coding-agent").update({"active": False})
    if name == "unsafe":
        text, source = store.scenarios["unsafe-coding-agent"], "policies/scenarios/unsafe-coding-agent.yaml"
    else:
        text, source = store.defaults["coding-agent"], "policies/agents/coding-agent.yaml"
    store.set_policy(text, source)
    db.add(Policy(agent="coding-agent", yaml_text=text, source=source, active=True, updated_by=user))


def seed(db: Session) -> bool:
    if db.query(User).count():
        return False
    now = utcnow()
    for user_id, name, title, roles in USERS:
        db.add(User(id=user_id, name=name, title=title, roles=roles))
    db.add(Project(name="Customer Portal API", repo="sample_app (local mock git)",
                   description="FastAPI service with health, login and profile endpoints."))
    db.add(GithubIntegration(mode=settings.github_mode, repo=settings.github_repo, enabled=settings.github_enabled))
    for env in ("DEV", "TEST", "STAGING", "PRODUCTION"):
        db.add(Deployment(env=env, version="1.3.2", deployed_by="ci-pipeline", approved_by="sam" if env == "PRODUCTION" else "",
                          ts=now - timedelta(days=3), notes="Baseline release"))
    for scope, rows in (("productivity", PRODUCTIVITY), ("dora", DORA)):
        for name, label, before, after, unit, better in rows:
            db.add(Metric(scope=scope, name=name, label=label, before_value=before, after_value=after, unit=unit,
                          better=better))
    db.flush()
    new_run(db, DEFAULT_REQUIREMENT, "dana")  # the live demo run is always run #1

    for index, (title, days_ago, score, minutes) in enumerate(HISTORY):
        started = now - timedelta(days=days_ago)
        run = WorkflowRun(project_id=1, title=title, requirement_text=title + ".", state="COMPLETED", step_index=25,
                          status="completed", simulated=True, created_by="alex", created_at=started,
                          updated_at=started + timedelta(minutes=minutes), artifacts={})
        db.add(run)
        db.flush()
        for offset, agent in enumerate(AGENT_SEQUENCE):
            tokens_in, tokens_out = 1800 + 420 * offset + 90 * index, 600 + 260 * offset
            db.add(AgentRun(run_id=run.id, agent=agent, task="seeded", provider="mock", model="mock-large",
                            prompt_version="v2", tokens_in=tokens_in, tokens_out=tokens_out,
                            cost_usd=round((tokens_in * 3 + tokens_out * 15) / 1e6, 5), latency_ms=900 + 700 * offset,
                            eval_score=score, simulated=True, created_at=started + timedelta(minutes=3 * offset)))
            db.add(AuditLog(ts=started + timedelta(minutes=3 * offset), agent=agent, actor_type="agent", run_id=run.id,
                            action="agent.run", input_summary="seeded history", result="completed",
                            tokens=tokens_in + tokens_out, simulated=True))
        db.add(AuditLog(ts=started + timedelta(minutes=20), user="alex", actor_type="human", run_id=run.id,
                        action="approval.approved", approval="pull request approved by alex", result="approved",
                        simulated=True))
        db.add(AuditLog(ts=started + timedelta(minutes=minutes), user="sam", actor_type="human", run_id=run.id,
                        action="approval.approved", approval="production approved by sam", result="approved",
                        simulated=True))
        db.add(Evaluation(run_id=run.id, suite="feature-suite", variant="prompt v2 · mock-large", score=score,
                          security_score=min(100.0, score + 4), accuracy=score - 2, tokens=14200, cost_usd=0.071,
                          latency_ms=5200, results=[], simulated=True, created_at=started + timedelta(minutes=14)))
        db.add(Pipeline(run_id=run.id, name="ai-sdlc-ci", ref=f"feature/history-{index + 1}", status="completed",
                        simulated=True, created_at=started + timedelta(minutes=18), gates=[], stages=[
                            {"key": key, "name": key.upper(), "status": "passed", "duration_s": seconds, "logs": [],
                             "ai": "", "human": "", "simulated": True}
                            for key, seconds in (("source", 1), ("lint", 4), ("test", 21), ("eval", 9),
                                                 ("security", 6), ("build", 48), ("staging", 12))]))
    db.add(AuditLog(ts=now - timedelta(days=6, hours=2), agent="coding-agent", actor_type="agent", action="tool.call",
                    tool="main.merge", policy_decision="DENY", result="blocked", simulated=True,
                    input_summary="merge pull request", output_summary="invariant:never_for_ai"))
    db.add(Incident(key="INC-2026-004", title="Pipeline change deployed an unreviewed build", severity="SEV2",
                    status="closed", phase="DOCUMENT RCA", mttr_minutes=64, simulated=True,
                    started_at=now - timedelta(days=41), resolved_at=now - timedelta(days=41) + timedelta(minutes=64),
                    data={"note": "Seeded history. See context_repo/incident-history.md."}))
    db.add(SecurityFinding(source="sast", severity="MEDIUM", category="dependency", status="closed", simulated=True,
                           title="Seeded: unpinned dependency in an earlier pull request",
                           recommendation="Pin the version."))

    # The lab starts with the coding agent on the configuration it "inherited from a pilot".
    load_scenario(db, "unsafe", "seed")
    db.commit()
    return True
