"""Relational schema. JSON columns keep stage artifacts flexible while the audit trail stays tabular."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_dict(obj) -> dict:
    out = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        out[column.name] = value.isoformat() + "Z" if isinstance(value, datetime) else value
    return out


class User(Base):
    __tablename__ = "users"
    id = Column(String(40), primary_key=True)
    name = Column(String(120), nullable=False)
    title = Column(String(120), default="")
    roles = Column(JSON, default=list)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    repo = Column(String(200), default="")
    description = Column(Text, default="")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    title = Column(String(200), nullable=False)
    requirement_text = Column(Text, nullable=False)
    state = Column(String(60), default="REQUIREMENT_CREATED")
    step_index = Column(Integer, default=0)
    status = Column(String(30), default="active")  # active | waiting_approval | blocked | completed | rejected
    blocked_reason = Column(Text, default="")
    artifacts = Column(JSON, default=dict)
    prompt_version = Column(String(10), default="v2")
    model = Column(String(60), default="")
    created_by = Column(String(40), default="")
    simulated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Requirement(Base):
    __tablename__ = "requirements"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("workflow_runs.id"))
    text = Column(Text, nullable=False)
    analysis = Column(JSON, default=dict)
    status = Column(String(30), default="analyzed")
    created_at = Column(DateTime, default=utcnow)


class Architecture(Base):
    __tablename__ = "architectures"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("workflow_runs.id"))
    proposal = Column(JSON, default=dict)
    selected_option = Column(String(10), default="")
    status = Column(String(30), default="proposed")
    created_at = Column(DateTime, default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    agent = Column(String(60), index=True)
    task = Column(String(60))
    provider = Column(String(40))
    model = Column(String(80))
    prompt_version = Column(String(10))
    status = Column(String(30), default="completed")
    input_summary = Column(Text, default="")
    output_summary = Column(Text, default="")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    eval_score = Column(Float)
    simulated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow, index=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    actor = Column(String(60), index=True)
    actor_type = Column(String(20))
    tool = Column(String(60), index=True)
    args_summary = Column(Text, default="")
    decision = Column(String(30))  # ALLOW | DENY | REQUIRE_APPROVAL | BLOCKED_KILL_SWITCH | DRY_RUN
    rule = Column(String(120), default="")
    reason = Column(Text, default="")
    executed = Column(Boolean, default=False)
    ok = Column(Boolean, default=False)
    result_summary = Column(Text, default="")
    redactions = Column(Integer, default=0)
    injection_flags = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    tag = Column(String(40), default="")
    simulated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow, index=True)


class Policy(Base):
    __tablename__ = "policies"
    id = Column(Integer, primary_key=True)
    agent = Column(String(60), index=True)
    yaml_text = Column(Text)
    source = Column(String(200))
    active = Column(Boolean, default=True)
    updated_by = Column(String(40))
    updated_at = Column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    kind = Column(String(40))  # requirement | architecture | pr | production | rollback
    step_key = Column(String(60))
    action = Column(String(60), default="")
    title = Column(String(200))
    summary = Column(Text, default="")
    required_role = Column(String(40))
    requested_by = Column(String(60))
    status = Column(String(30), default="pending")  # pending | approved | changes_requested | rejected
    decided_by = Column(String(40))
    comment = Column(Text, default="")
    payload = Column(JSON, default=dict)
    consumed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    suite = Column(String(80))
    variant = Column(String(80))
    score = Column(Float)
    security_score = Column(Float)
    accuracy = Column(Float)
    latency_ms = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    results = Column(JSON, default=list)
    simulated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class SecurityFinding(Base):
    __tablename__ = "security_findings"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    source = Column(String(40))  # sast | secrets | injection | capability | redteam | review
    severity = Column(String(12))
    category = Column(String(60))
    title = Column(String(240))
    detail = Column(Text, default="")
    file = Column(String(200), default="")
    line = Column(Integer)
    recommendation = Column(Text, default="")
    status = Column(String(20), default="open")
    simulated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    key = Column(String(40))
    title = Column(String(240))
    severity = Column(String(12))
    status = Column(String(30), default="open")
    phase = Column(String(40), default="DETECT")
    data = Column(JSON, default=dict)
    mttr_minutes = Column(Float)
    simulated = Column(Boolean, default=True)
    started_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime)


class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    scope = Column(String(40), index=True)  # productivity | dora
    name = Column(String(80))
    label = Column(String(120))
    before_value = Column(Float)
    after_value = Column(Float)
    unit = Column(String(20))
    better = Column(String(10), default="lower")
    simulated = Column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=utcnow, index=True)
    user = Column(String(60), default="")
    agent = Column(String(60), default="", index=True)
    actor_type = Column(String(20), default="")
    run_id = Column(Integer, index=True)
    action = Column(String(80))
    tool = Column(String(60), default="")
    input_summary = Column(Text, default="")
    output_summary = Column(Text, default="")
    policy_decision = Column(String(30), default="")
    approval = Column(String(80), default="")
    result = Column(String(30), default="")
    latency_ms = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    tag = Column(String(40), default="")
    simulated = Column(Boolean, default=False)


class GithubIntegration(Base):
    __tablename__ = "github_integrations"
    id = Column(Integer, primary_key=True)
    mode = Column(String(30))
    repo = Column(String(200), default="")
    enabled = Column(Boolean, default=False)
    last_pr_url = Column(String(300), default="")
    last_error = Column(Text, default="")
    updated_at = Column(DateTime, default=utcnow)


class PullRequest(Base):
    __tablename__ = "pull_requests"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    number = Column(Integer)
    title = Column(String(240))
    branch = Column(String(120))
    base = Column(String(60), default="main")
    author = Column(String(60))
    description = Column(Text, default="")
    status = Column(String(30), default="open")  # open | approved | changes_requested | rejected | merged
    data = Column(JSON, default=dict)
    merged_by = Column(String(40))
    external_url = Column(String(300), default="")
    created_at = Column(DateTime, default=utcnow)


class Pipeline(Base):
    __tablename__ = "pipelines"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    name = Column(String(120))
    ref = Column(String(120))
    status = Column(String(30))
    stages = Column(JSON, default=list)
    gates = Column(JSON, default=list)
    simulated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class Deployment(Base):
    __tablename__ = "deployments"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, index=True)
    env = Column(String(40), index=True)
    version = Column(String(40))
    status = Column(String(30), default="healthy")
    kind = Column(String(20), default="deploy")  # deploy | rollback
    deployed_by = Column(String(60))
    approved_by = Column(String(60), default="")
    notes = Column(Text, default="")
    data = Column(JSON, default=dict)
    simulated = Column(Boolean, default=True)
    ts = Column(DateTime, default=utcnow, index=True)


class ContextDocument(Base):
    """Documents added to the context index at runtime (for example a finished RCA)."""

    __tablename__ = "context_documents"
    id = Column(Integer, primary_key=True)
    path = Column(String(200), unique=True)
    text = Column(Text)
    meta = Column(JSON, default=dict)
    added_by = Column(String(60))
    created_at = Column(DateTime, default=utcnow)


class SystemFlag(Base):
    __tablename__ = "system_flags"
    key = Column(String(60), primary_key=True)
    value = Column(JSON)
    updated_by = Column(String(60), default="")
    updated_at = Column(DateTime, default=utcnow)
