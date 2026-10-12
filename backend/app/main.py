"""AI-SDLC Champion Lab - HTTP API."""
from __future__ import annotations

import shutil
from contextlib import asynccontextmanager

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import redteam, seed, services
from .agents import AGENTS
from .config import settings
from .core import audit, capability, injection, secrets_scan
from .core.gateway import KILL_SWITCH_MESSAGE, Actor
from .db import Base, SessionLocal, engine, get_session, init_db
from .evals import adapters, harness
from .learn import curriculum, stages
from .models import (AgentRun, Approval, AuditLog, Evaluation, GithubIntegration, Incident, Metric, Pipeline,
                     PullRequest, SecurityFinding, ToolCall, User, WorkflowRun, to_dict)
from .ops import deploy as deploy_ops
from .ops import telemetry
from .providers import provider_catalog
from .tools import github_real, impl, sandbox
from .workflow import engine as workflow
from .workflow.steps import STEPS


def bootstrap() -> None:
    init_db()
    with SessionLocal() as db:
        seed.seed(db)
        services.apply_policy_overrides(db)
        services.rebuild_index(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    yield


app = FastAPI(title="AI-SDLC Champion Lab", version="1.0.0", lifespan=lifespan,
              description="Human-in-the-Loop AI for Safer and More Productive Software Engineering")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(workflow.WorkflowError)
async def workflow_error(_: Request, error: workflow.WorkflowError):
    return JSONResponse(status_code=error.status, content={"detail": str(error)})


# --- identity -------------------------------------------------------------------------------------
def current_user(x_user: str = Header(default="dana"), db: Session = Depends(get_session)) -> Actor:
    user = db.get(User, x_user)
    if user is None:
        raise HTTPException(401, f"Unknown user '{x_user}'.")
    return Actor(user.id, "human", list(user.roles or []))


def require(permission: str):
    def check(user: Actor = Depends(current_user)) -> Actor:
        if not services.get_store().human_can(user.roles, permission):
            raise HTTPException(403, f"'{permission}' is not granted to {user.id} (roles: {', '.join(user.roles) or 'none'}).")
        return user
    return check


def get_run(run_id: int, db: Session = Depends(get_session)) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


# --- meta -----------------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "mock_ai": settings.mock_ai, "provider": settings.effective_provider}


@app.get("/api/meta")
def meta(db: Session = Depends(get_session)):
    return {
        "name": "AI-SDLC Champion Lab",
        "subtitle": "Human-in-the-Loop AI for Safer and More Productive Software Engineering",
        "messages": stages.MESSAGES, "ai_may": stages.AI_MAY, "ai_may_not": stages.AI_MAY_NOT,
        "mock_ai": settings.mock_ai, "provider": settings.effective_provider, "providers": provider_catalog(),
        "github_mode": settings.github_mode,
        "database": "postgresql" if settings.database_url.startswith("postgresql") else "sqlite",
        "users": [to_dict(u) for u in db.query(User).order_by(User.name).all()],
        "flags": audit.get_flags(db), "kill_switch_message": KILL_SWITCH_MESSAGE,
        "default_requirement": seed.DEFAULT_REQUIREMENT,
        "agents": [{"id": a.id, "name": a.name, "role": a.role} for a in AGENTS.values()],
    }


class FlagsBody(BaseModel):
    kill_switch: bool | None = None
    dry_run: bool | None = None


@app.post("/api/flags")
def set_flags(body: FlagsBody, db: Session = Depends(get_session), user: Actor = Depends(require("flags.modify"))):
    for key, value in body.model_dump(exclude_none=True).items():
        audit.set_flag(db, key, value, user.id)
        audit.record(db, action=f"flag.{key}", user=user.id, actor_type="human", input_summary=str(value),
                     output_summary=KILL_SWITCH_MESSAGE if key == "kill_switch" and value else "", result="set")
    db.commit()
    return audit.get_flags(db)


@app.post("/api/demo/reset")
def reset_demo(db: Session = Depends(get_session), user: Actor = Depends(require("flags.modify"))):
    """Wipe all lab state and seed again. Only touches the lab's own database and sandbox directory."""
    db.close()
    Base.metadata.drop_all(engine)
    shutil.rmtree(settings.data_dir / "workspaces", ignore_errors=True)
    impl.MOCK_EFFECTS.clear()
    services.reset()
    bootstrap()
    return {"status": "reset"}


# --- runs -----------------------------------------------------------------------------------------
class RunBody(BaseModel):
    requirement: str = Field(min_length=8, max_length=2000)
    prompt_version: str = Field(default="v2", pattern="^v[12]$")
    model: str = Field(default="", max_length=80)


@app.get("/api/runs")
def list_runs(db: Session = Depends(get_session)):
    rows = db.query(WorkflowRun).order_by(WorkflowRun.simulated, WorkflowRun.id.desc()).all()
    return [{k: v for k, v in to_dict(r).items() if k != "artifacts"} for r in rows]


@app.post("/api/runs")
def create_run(body: RunBody, db: Session = Depends(get_session), user: Actor = Depends(require("run.advance"))):
    run = seed.new_run(db, body.requirement, user.id, body.prompt_version, body.model)
    audit.record(db, action="run.created", user=user.id, actor_type="human", run_id=run.id,
                 input_summary=body.requirement, result="created")
    db.commit()
    return workflow.describe(db, run)


@app.get("/api/runs/{run_id}")
def read_run(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session)):
    return {**workflow.describe(db, run), "artifacts": run.artifacts or {}}


@app.post("/api/runs/{run_id}/advance")
def advance_run(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session),
                user: Actor = Depends(current_user)):
    return workflow.advance(db, run, user)


@app.post("/api/runs/{run_id}/dry-run")
def dry_run(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session),
            user: Actor = Depends(current_user)):
    return workflow.dry_run(db, run, user)


class FastForwardBody(BaseModel):
    until: str = ""


@app.post("/api/runs/{run_id}/fast-forward")
def fast_forward(body: FastForwardBody, run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session),
                 user: Actor = Depends(current_user)):
    return workflow.fast_forward(db, run, user, body.until)


@app.get("/api/runs/{run_id}/approvals")
def run_approvals(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session)):
    rows = db.query(Approval).filter(Approval.run_id == run.id).order_by(Approval.id).all()
    return [to_dict(r) for r in rows]


class DecisionBody(BaseModel):
    decision: str
    comment: str = Field(default="", max_length=2000)
    option: str = ""


@app.post("/api/approvals/{approval_id}/decide")
def decide(approval_id: int, body: DecisionBody, db: Session = Depends(get_session),
           user: Actor = Depends(current_user)):
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found.")
    return workflow.decide(db, approval, user, body.decision, body.comment, {"option": body.option} if body.option else None)


@app.get("/api/runs/{run_id}/tool-calls")
def run_tool_calls(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session), actor: str = ""):
    query = db.query(ToolCall).filter(ToolCall.run_id == run.id)
    if actor:
        query = query.filter(ToolCall.actor == actor)
    return [to_dict(r) for r in query.order_by(ToolCall.id).all()]


@app.get("/api/runs/{run_id}/pull-request")
def run_pull_request(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session)):
    pr = db.query(PullRequest).filter(PullRequest.run_id == run.id).order_by(PullRequest.id.desc()).first()
    return to_dict(pr) if pr else None


@app.get("/api/runs/{run_id}/git")
def run_git(run: WorkflowRun = Depends(get_run)):
    git = services.workspace(run.id)
    return {"mode": "local-mock-git", "branches": git.branches(), "log": git.log("main", 15),
            "protected": ["main"]}


@app.get("/api/runs/{run_id}/incident")
def run_incident(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session)):
    row = db.query(Incident).filter(Incident.run_id == run.id).order_by(Incident.id.desc()).first()
    return to_dict(row) if row else None


# --- context --------------------------------------------------------------------------------------
class SearchBody(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    max_tokens: int = Field(default=8000, ge=100, le=20000)
    doc_types: list[str] = []
    include_deprecated: bool = False


@app.get("/api/context/stats")
def context_stats():
    return services.get_index().stats()


@app.post("/api/context/search")
def context_search(body: SearchBody, db: Session = Depends(get_session)):
    result = services.get_gateway().call(db, Actor("context-agent", "agent"), "context.search", {
        "query": body.query, "max_tokens": body.max_tokens, "doc_types": body.doc_types or None,
        "include_deprecated": body.include_deprecated}, tag="explorer")
    db.commit()
    if not result.ok:
        raise HTTPException(409, result.reason)
    return result.output


# --- security -------------------------------------------------------------------------------------
@app.get("/api/security/capability")
def capability_overview():
    return capability.audit_all(services.get_store())


@app.get("/api/security/capability/{agent}")
def capability_agent(agent: str):
    try:
        return capability.audit_agent(agent, services.get_store())
    except KeyError:
        raise HTTPException(404, "Unknown agent.") from None


@app.get("/api/security/policies")
def policies():
    store = services.get_store()
    coding = store.get("coding-agent")
    return {
        "global_yaml": (settings.policies_dir / "global.yaml").read_text(), "global": store.global_rules,
        "agents": [{**p.summary(), "yaml": p.raw_yaml} for p in sorted(store.policies.values(), key=lambda p: p.agent)],
        "scenario": "unsafe" if "scenarios" in coding.source else "recommended",
        "recommended_yaml": store.defaults["coding-agent"], "unsafe_yaml": store.scenarios["unsafe-coding-agent"],
    }


class ScenarioBody(BaseModel):
    name: str = Field(pattern="^(unsafe|recommended)$")


@app.post("/api/security/scenario")
def apply_scenario(body: ScenarioBody, db: Session = Depends(get_session),
                   user: Actor = Depends(require("policy.modify"))):
    before = capability.audit_agent("coding-agent", services.get_store())["summary"]
    seed.load_scenario(db, body.name, user.id)
    after = capability.audit_agent("coding-agent", services.get_store())
    audit.record(db, action="policy.changed", user=user.id, actor_type="human", agent="coding-agent",
                 input_summary=f"scenario={body.name}", result="applied",
                 output_summary=f"critical paths {before['critical']} -> {after['summary']['critical']}")
    db.commit()
    return {"scenario": body.name, "before": before, "after": after["summary"], "allowed": after["declared"]}


@app.post("/api/security/redteam")
def run_redteam(db: Session = Depends(get_session), user: Actor = Depends(require("redteam.run"))):
    report = redteam.run_all(db)
    audit.record(db, action="redteam.run", user=user.id, actor_type="human", tag="redteam",
                 output_summary=f"{report['passed']}/{report['total']} scenarios blocked", result="completed")
    db.commit()
    return report


@app.get("/api/security/findings")
def security_findings(db: Session = Depends(get_session), run_id: int | None = None):
    query = db.query(SecurityFinding)
    if run_id:
        query = query.filter(or_(SecurityFinding.run_id == run_id, SecurityFinding.run_id.is_(None)))
    return [to_dict(r) for r in query.order_by(SecurityFinding.id.desc()).limit(200).all()]


SECRET_SURFACES = [
    ("source", "Source code", "config/settings.py",
     'DEBUG = False\nDB_PASSWORD = "FAKE-db-Xk29mQ7pL2"\nAWS_ACCESS_KEY_ID = "AKIAFAKEFAKEFAKE0000"\nTIMEOUT = 30'),
    ("logs", "Application logs", "portal.log",
     "INFO  service started version=1.4.0\nDEBUG connecting to postgresql://portal:FAKEpass12345@db.internal/portal\n"
     "INFO  GET /health 200"),
    ("prompt", "Prompt sent to a model", "user prompt",
     "Please debug why CI fails. Here is our environment:\nFAKE_GITHUB_TOKEN=ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE\n"
     "The error is 'permission denied'."),
    ("tool_result", "Result returned by a tool", "vault-mcp secrets.read",
     '{"name": "db-password", "value": "FAKE_DB_PASSWORD=fake-db-Xk29mQ7pL2"}'),
    ("environment", "Environment variables", "process environment",
     "PATH=/usr/bin:/bin\nFAKE_DB_PASSWORD=fake-db-Xk29mQ7pL2\nFAKE_AWS_KEY=AKIAFAKEFAKEFAKE0000\nLANG=C.UTF-8"),
]


@app.get("/api/security/secrets-demo")
def secrets_demo():
    surfaces = []
    for key, label, source, text in SECRET_SURFACES:
        clean, count = secrets_scan.redact(text)
        surfaces.append({"surface": key, "label": label, "source": source, "original": text, "redacted": clean,
                         "redactions": count,
                         "findings": [f.as_dict() for f in secrets_scan.scan_text(text, key, source)]})
    return {"note": "Every value on this page is fake and was created for this demo.", "surfaces": surfaces,
            "sandbox_env_keys": sorted(sandbox.sandbox_env(settings.data_dir, "~"))}


@app.get("/api/security/injection-demo")
def injection_demo():
    path = settings.context_dir / "untrusted" / "document-17.txt"
    text = path.read_text()
    findings = injection.scan(text)
    retrieval = services.get_index().retrieve("password reset email never arrives support ticket", max_tokens=2000)
    return {
        "source": "document-17.txt", "text": text, "findings": [f.as_dict() for f in findings],
        "risk": injection.risk_score(findings), "verdict": "Prompt injection detected.",
        "action": "Instruction ignored.", "reason": "Retrieved content cannot override system policy.",
        "quarantined": retrieval["quarantined"],
        "reached_prompt": any(r["source"].endswith("document-17.txt") and r["status"] == "selected"
                              for r in retrieval["candidates"]),
    }


# --- evaluation -----------------------------------------------------------------------------------
@app.get("/api/evals/suite")
def eval_suite():
    suite = harness.load_suite()
    return {**suite, "category_labels": harness.CATEGORY_LABELS}


@app.get("/api/evals/compare")
def eval_compare():
    return harness.compare()


@app.get("/api/evals/history")
def eval_history(db: Session = Depends(get_session)):
    rows = db.query(Evaluation).order_by(Evaluation.id.desc()).limit(30).all()
    return [{k: v for k, v in to_dict(r).items() if k != "results"} for r in rows]


@app.get("/api/evals/promptfoo")
def eval_promptfoo():
    return {"yaml": yaml.safe_dump(adapters.to_promptfoo_config(), sort_keys=False, width=110)}


# --- delivery -------------------------------------------------------------------------------------
@app.get("/api/pipelines")
def pipelines(db: Session = Depends(get_session), run_id: int | None = None):
    query = db.query(Pipeline)
    if run_id:
        query = query.filter(or_(Pipeline.run_id == run_id, Pipeline.simulated.is_(True)))
    return [to_dict(r) for r in query.order_by(Pipeline.id.desc()).limit(20).all()]


@app.get("/api/deployments")
def deployments(db: Session = Depends(get_session)):
    return {"environments": deploy_ops.environments(db), "simulation": True,
            "history": [{k: v for k, v in to_dict(d).items() if k != "data"} for d in deploy_ops.history(db, limit=25)]}


@app.post("/api/deployments/{env}/health-check")
def health_check(env: str, db: Session = Depends(get_session)):
    if env not in deploy_ops.ENVIRONMENTS:
        raise HTTPException(404, "Unknown environment.")
    return deploy_ops.health(db, env)


@app.post("/api/deployments/{env}/rollback")
def rollback(env: str, db: Session = Depends(get_session), user: Actor = Depends(current_user)):
    if env not in deploy_ops.ENVIRONMENTS:
        raise HTTPException(404, "Unknown environment.")
    if env == "PRODUCTION":
        raise HTTPException(409, "A production rollback needs approval from the on-call SRE. It is requested "
                                 "through the incident workflow, never performed directly.")
    if not services.get_store().human_can(user.roles, "main.merge"):
        raise HTTPException(403, "Rolling back a non-production environment needs the engineer role.")
    try:
        row = deploy_ops.rollback(db, env, user.id, notes="Manual rollback of a non-production environment")
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    audit.record(db, action="deploy.rollback", user=user.id, actor_type="human", input_summary=env,
                 output_summary=row.version, result="executed")
    db.commit()
    return deploy_ops.health(db, env)


# --- observability --------------------------------------------------------------------------------
@app.get("/api/observability/app")
def observability_app(db: Session = Depends(get_session)):
    return telemetry.app_metrics(db, 60)


@app.get("/api/observability/logs")
def observability_logs(db: Session = Depends(get_session), q: str = ""):
    lines = telemetry.logs(db, q, 40)
    for line in lines:  # the same redaction a tool result gets
        line["message"], _ = secrets_scan.redact(line["message"])
    return lines


@app.get("/api/observability/ai")
def observability_ai(db: Session = Depends(get_session)):
    runs = db.query(AgentRun).order_by(AgentRun.id).all()
    live = [r for r in runs if not r.simulated or r.task != "seeded"]

    def group(rows, key):
        out: dict[str, dict] = {}
        for row in rows:
            bucket = out.setdefault(key(row), {"runs": 0, "tokens": 0, "cost_usd": 0.0, "latency_ms": 0})
            bucket["runs"] += 1
            bucket["tokens"] += row.tokens_in + row.tokens_out
            bucket["cost_usd"] = round(bucket["cost_usd"] + row.cost_usd, 6)
            bucket["latency_ms"] += row.latency_ms
        return [{"key": k, **v, "avg_latency_ms": round(v["latency_ms"] / v["runs"])} for k, v in out.items()]

    calls = db.query(ToolCall).all()
    return {
        "totals": {"runs": len(runs), "live_runs": len(live), "tokens": sum(r.tokens_in + r.tokens_out for r in runs),
                   "cost_usd": round(sum(r.cost_usd for r in runs), 4),
                   "failed_tool_calls": sum(c.executed and not c.ok for c in calls),
                   "blocked_actions": sum(c.decision in ("DENY", "BLOCKED_KILL_SWITCH") for c in calls)},
        "by_agent": sorted(group(runs, lambda r: r.agent), key=lambda g: -g["tokens"]),
        "by_model": group(runs, lambda r: f"{r.provider} / {r.model}"),
        "by_prompt_version": group(runs, lambda r: r.prompt_version or "-"),
        "evaluations": [{"id": e.id, "score": e.score, "security_score": e.security_score, "variant": e.variant,
                         "simulated": e.simulated, "created_at": to_dict(e)["created_at"]}
                        for e in db.query(Evaluation).order_by(Evaluation.id).all()],
        "recent": [to_dict(r) for r in runs[-25:]][::-1],
        "pricing_note": "Mock model prices are illustrative. Real-provider prices come from AI_PRICE_* settings.",
    }


@app.get("/api/observability/security")
def observability_security(db: Session = Depends(get_session)):
    calls = db.query(ToolCall).all()
    denied: dict[str, int] = {}
    for call in calls:
        if call.decision == "DENY":
            denied[call.tool] = denied.get(call.tool, 0) + 1
    reports = capability.audit_all(services.get_store())
    findings = db.query(SecurityFinding).all()
    return {
        "policy_violations": sum(c.decision == "DENY" for c in calls),
        "kill_switch_blocks": sum(c.decision == "BLOCKED_KILL_SWITCH" for c in calls),
        "approval_requests": sum(c.decision == "REQUIRE_APPROVAL" for c in calls),
        "dry_runs": sum(c.decision == "DRY_RUN" for c in calls),
        "injection_attempts": sum(f.source == "injection" for f in findings) + sum(c.injection_flags > 0 for c in calls),
        "secret_access_attempts": sum(c.tool == "secrets.read" for c in calls),
        "secrets_redacted": sum(c.redactions for c in calls),
        "unexpected_capability_paths": sum(len(r["findings"]) for r in reports),
        "critical_capability_paths": sum(r["summary"]["critical"] for r in reports),
        "denied_tools": sorted(({"tool": t, "count": n} for t, n in denied.items()), key=lambda d: -d["count"]),
        "by_decision": [{"decision": d, "count": n} for d, n in db.query(
            ToolCall.decision, func.count(ToolCall.id)).group_by(ToolCall.decision).all()],
        "recent_blocked": [to_dict(c) for c in sorted(
            (c for c in calls if c.decision in ("DENY", "BLOCKED_KILL_SWITCH")), key=lambda c: -c.id)[:20]],
        "capability": reports,
    }


@app.get("/api/incidents")
def incidents(db: Session = Depends(get_session)):
    return [to_dict(r) for r in db.query(Incident).order_by(Incident.id.desc()).all()]


# --- governance -----------------------------------------------------------------------------------
@app.get("/api/governance/agents")
def governance_agents(db: Session = Depends(get_session)):
    store = services.get_store()
    usage = {agent: (runs, tokens or 0, cost or 0.0) for agent, runs, tokens, cost in db.query(
        AgentRun.agent, func.count(AgentRun.id), func.sum(AgentRun.tokens_in + AgentRun.tokens_out),
        func.sum(AgentRun.cost_usd)).group_by(AgentRun.agent).all()}
    out = []
    for policy in sorted(store.policies.values(), key=lambda p: (p.kind != "ai", p.agent)):
        report = capability.audit_agent(policy.agent, store)
        reach = {r["action"]: r["status"] for r in report["reach"]}

        def access(action: str) -> str:
            status = reach.get(action)
            if status in (None, "contained"):
                return "NO"
            return "WITH HUMAN APPROVAL" if status == "gated" else "YES"

        runs, tokens, cost = usage.get(policy.agent, (0, 0, 0.0))
        definition = AGENTS.get(policy.agent)
        out.append({
            **policy.summary(), "name": definition.name if definition else policy.display_name,
            "prompt_versions": sorted(definition.prompts) if definition else [],
            "model": settings.effective_provider if policy.kind == "ai" else "none",
            "production_access": access("production.deploy"), "secret_access": access("secrets.read"),
            "merge_rights": access("main.merge"),
            "human_approval": "YES" if policy.kind == "ai" else "FOR PRODUCTION",
            "human_approval_actions": sorted(set(policy.require_approval) | set(store.approval_at_most)),
            "capability_status": report["summary"]["status"], "unexpected_paths": len(report["findings"]),
            "usage": {"runs": runs, "tokens": int(tokens), "cost_usd": round(cost, 4)},
            "audit_log": f"/api/audit?actor={policy.agent}",
        })
    return out


@app.get("/api/audit")
def audit_log(db: Session = Depends(get_session), q: str = "", actor: str = "", decision: str = "",
              run_id: int | None = None, limit: int = 200):
    query = db.query(AuditLog)
    if run_id:
        query = query.filter(AuditLog.run_id == run_id)
    if actor:
        query = query.filter(or_(AuditLog.agent == actor, AuditLog.user == actor))
    if decision:
        query = query.filter(or_(AuditLog.policy_decision == decision, AuditLog.result == decision))
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(*[func.lower(column).like(like) for column in (
            AuditLog.action, AuditLog.tool, AuditLog.input_summary, AuditLog.output_summary, AuditLog.agent,
            AuditLog.user, AuditLog.approval)]))
    total = query.count()
    return {"total": total, "entries": [to_dict(r) for r in query.order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()]}


# --- productivity ---------------------------------------------------------------------------------
HOURLY_RATE_USD = 58.0
SIMULATED_AI_COST_USD = 1.82
SIMULATED_HOURS_SAVED = 3.1


@app.get("/api/productivity")
def productivity(db: Session = Depends(get_session), run_id: int | None = None):
    metrics = db.query(Metric).order_by(Metric.id).all()
    value = round(SIMULATED_HOURS_SAVED * HOURLY_RATE_USD)
    measured = None
    if run_id and (run := db.get(WorkflowRun, run_id)) is not None:
        runs = db.query(AgentRun).filter(AgentRun.run_id == run.id).all()
        calls = db.query(ToolCall).filter(ToolCall.run_id == run.id).all()
        tests = (run.artifacts or {}).get("tests") or {}
        cost = round(sum(r.cost_usd for r in runs), 4)
        measured = {
            "ai_cost_usd": cost, "cost_per_feature_usd": cost, "tokens": sum(r.tokens_in + r.tokens_out for r in runs),
            "agent_runs": len(runs), "tool_calls": len(calls),
            "blocked_actions": sum(c.decision in ("DENY", "BLOCKED_KILL_SWITCH") for c in calls),
            "human_approvals": db.query(Approval).filter(Approval.run_id == run.id, Approval.status == "approved").count(),
            "steps_done": run.step_index, "steps_total": len(STEPS),
            "ai_steps": sum(s.kind == "ai" for s in STEPS), "human_steps": sum(s.kind in ("approval", "human_action") for s in STEPS),
            "coverage_before": (tests.get("before") or {}).get("coverage"),
            "coverage_after": (tests.get("after") or {}).get("coverage"),
            "tests_before": (tests.get("before") or {}).get("total"), "tests_after": (tests.get("after") or {}).get("total"),
            "evaluation_score": ((run.artifacts or {}).get("evaluation") or {}).get("score"),
            "note": "Measured in this session. Cost uses mock-model prices while MOCK_AI=true.",
        }
    return {
        "simulated_notice": "SIMULATED DEMO DATA - illustrative before/after figures, not measurements.",
        "comparison": [to_dict(m) for m in metrics if m.scope == "productivity"],
        "dora": [to_dict(m) for m in metrics if m.scope == "dora"],
        "dora_note": "AI does not automatically improve DORA metrics. Faster code generation can move the "
                     "bottleneck to review or raise the change failure rate. Measure your own outcomes.",
        "roi": {"simulated": True, "engineer_hours_saved": SIMULATED_HOURS_SAVED, "hourly_rate_usd": HOURLY_RATE_USD,
                "engineering_value_usd": value, "ai_cost_usd": SIMULATED_AI_COST_USD,
                "cost_per_feature_usd": SIMULATED_AI_COST_USD,
                "net_value_usd": round(value - SIMULATED_AI_COST_USD, 2),
                "roi_multiple": round((value - SIMULATED_AI_COST_USD) / SIMULATED_AI_COST_USD, 1),
                "formula": "ROI = (hours saved x hourly rate - AI cost) / AI cost"},
        "measured": measured,
    }


# --- learn ----------------------------------------------------------------------------------------
@app.get("/api/learn")
def learn():
    store = services.get_store()
    out = {}
    for key, stage in stages.STAGES.items():
        policy = store.get(stage["agent"])
        tools = [{"tool": t, "mode": "allowed"} for t in policy.allowed] + [
            {"tool": t, "mode": "needs approval"} for t in policy.require_approval] if policy else []
        out[key] = {**stage, "what_tools_can_ai_use": tools,
                    "denied_examples": [t for t in (policy.denied if policy else [])][:6]}
    return {"stages": out, "questions": stages.QUESTIONS, "teach": stages.TEACH, "lessons": curriculum.LESSONS,
            "context_concepts": stages.CONTEXT_CONCEPTS, "rca_concepts": stages.RCA_CONCEPTS,
            "security_principles": stages.SECURITY_PRINCIPLES,
            "rca_rule": ["Restore service first.", "Find root cause second.", "Automate prevention third."]}


# --- architecture ---------------------------------------------------------------------------------
SYSTEM_DIAGRAM = """flowchart TB
  user([User]) --> ui["React UI"]
  ui --> api["FastAPI"]
  api --> wf["Workflow Engine<br/>state machine, LangGraph-compatible"]
  subgraph platform["Platform services"]
    direction LR
    ctx["Context Engine"]
    rt["Agent Runtime"]
    pol["Policy Engine"]
    ev["Evaluation Harness"]
    gw["Tool Gateway / MCP"]
  end
  wf --> rt
  wf --> ev
  rt --> ctx
  rt --> gw
  gw --> pol
  platform --> db[("PostgreSQL<br/>state, audit, pgvector-ready")]
  rt --> llm["LLM Provider<br/>mock by default"]
  gw --> git["GitHub<br/>local mock git or sandbox repo"]
  gw --> ci["CI/CD"]
  gw --> mon["Monitoring"]
"""
TOOL_FLOW_DIAGRAM = """flowchart LR
  a["Agent request"] --> k{"Kill switch?"}
  k -- on --> x1["BLOCKED"]
  k -- off --> p{"Policy check"}
  p -- DENY --> x2["DENIED"]
  p -- ALLOW --> c{"Permission check<br/>branch and path constraints"}
  p -- REQUIRE_APPROVAL --> h{"Approval check<br/>decided by a human?"}
  c -- fail --> x2
  h -- no --> w["Waits for human"]
  h -- yes --> e
  c -- ok --> e["Tool execution<br/>sandboxed"]
  e --> s["Output screening<br/>secrets redacted, injection flagged"]
  s --> l["Audit log"]
  x1 --> l
  x2 --> l
  w --> l
"""


@app.get("/api/architecture")
def architecture():
    return {"system": SYSTEM_DIAGRAM, "tool_flow": TOOL_FLOW_DIAGRAM, "state_machine": workflow.to_mermaid(),
            "principles": stages.SECURITY_PRINCIPLES,
            "honest_notes": [
                "Embeddings are a local TF-IDF hashing model held in memory. pgvector is the documented swap-in, not in use.",
                "The native workflow engine is the default. The LangGraph adapter compiles the same step list.",
                "The sandbox is a subprocess with a scrubbed environment, not a network-isolated container.",
                "Real model providers and the GitHub sandbox need your credentials; tests and CI use mocks only.",
            ]}


# --- GitHub ---------------------------------------------------------------------------------------
@app.get("/api/github")
def github_status(db: Session = Depends(get_session)):
    row = db.query(GithubIntegration).first()
    return {"mode": settings.github_mode, "enabled": settings.github_enabled, "repo": settings.github_repo,
            "token_configured": bool(settings.github_token), "last_pr_url": row.last_pr_url if row else "",
            "last_error": row.last_error if row else "",
            "allowed": ["Read repository", "Create branch", "Commit files", "Open pull request", "Read PR diff",
                        "Add AI review comment", "Read GitHub Actions result"],
            "never": ["Merge automatically", "Delete repository", "Change repository security",
                      "Modify organisation permissions"],
            "token_permissions": {"Contents": "Read/Write", "Pull requests": "Read/Write", "Actions": "Read"}}


@app.post("/api/runs/{run_id}/publish")
def publish_to_github(run: WorkflowRun = Depends(get_run), db: Session = Depends(get_session),
                      user: Actor = Depends(require("approve.pr"))):
    if settings.github_mode != "github-sandbox":
        raise HTTPException(409, "GitHub sandbox mode is off. Set GITHUB_ENABLED=true, GITHUB_TOKEN and GITHUB_REPO.")
    pr = db.query(PullRequest).filter(PullRequest.run_id == run.id).order_by(PullRequest.id.desc()).first()
    if pr is None:
        raise HTTPException(409, "This run has no pull request yet.")
    git = services.workspace(run.id)
    files = {f["path"]: git.read(f["path"], pr.branch) for f in git.diff_stats("main", pr.branch) if f["status"] != "deleted"}
    comments = (pr.data or {}).get("comments", [])
    row = db.query(GithubIntegration).first()
    try:
        result = github_real.publish_run(run, pr, files, comments[0]["body"] if comments else "")
    except github_real.GitHubError as error:
        row.last_error = str(error)
        db.commit()
        raise HTTPException(502, str(error)) from None
    row.last_pr_url, row.last_error, pr.external_url = result["url"], "", result["url"]
    audit.record(db, action="github.pr.opened", user=user.id, actor_type="human", run_id=run.id,
                 output_summary=result["url"], result="executed")
    db.commit()
    return result


# --- MCP ------------------------------------------------------------------------------------------
@app.get("/api/mcp/tools")
def mcp_tools():
    return {"tools": impl.mcp_tools()}


@app.post("/api/mcp")
def mcp_rpc(body: dict, db: Session = Depends(get_session), x_agent_id: str = Header(default="")):
    """Minimal JSON-RPC surface in MCP shape. tools/call goes through the same gateway as everything else."""
    method, rpc_id, params = body.get("method"), body.get("id"), body.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "ai-sdlc-lab-gateway", "version": "1.0.0"},
                  "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": impl.mcp_tools()}
    elif method == "tools/call":
        outcome = services.get_gateway().call(db, Actor(x_agent_id or "anonymous", "agent"), params.get("name", ""),
                                              params.get("arguments") or {}, tag="mcp")
        db.commit()
        text = audit.summarize(outcome.output, 4000) if outcome.ok else f"{outcome.decision}: {outcome.reason}"
        result = {"content": [{"type": "text", "text": text}], "isError": not outcome.ok,
                  "_meta": {"decision": outcome.decision, "rule": outcome.rule}}
    else:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
