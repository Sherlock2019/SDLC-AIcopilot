"""The critical guarantees: what an AI agent can never do, whatever its policy file says."""
import pytest

from app.core.gateway import Actor
from app.core.policy import ALLOW, DENY, REQUIRE_APPROVAL, AgentPolicy
from app.models import Approval, AuditLog, ToolCall, utcnow
from app.tools import impl
from tests.conftest import agent

AI_AGENTS = ["requirement-agent", "context-agent", "architecture-agent", "coding-agent", "test-agent",
             "review-agent", "security-agent", "evaluation-agent", "deployment-advisor", "incident-agent",
             "rca-agent", "governance-agent"]
PERMISSIVE = """
agent: rogue-agent
kind: ai
allowed: ["*"]
require_approval: []
"""


# --- policy engine (unit) -------------------------------------------------------------------------
@pytest.mark.parametrize("name", AI_AGENTS)
def test_ai_cannot_merge(store, name):
    assert store.evaluate(name, "main.merge").decision == DENY


@pytest.mark.parametrize("name", AI_AGENTS)
def test_ai_cannot_read_secrets(store, name):
    assert store.evaluate(name, "secrets.read").decision == DENY


@pytest.mark.parametrize("name", AI_AGENTS)
def test_ai_cannot_modify_its_own_policy_or_permissions(store, name):
    assert store.evaluate(name, "policy.modify").decision == DENY
    assert store.evaluate(name, "iam.modify").decision == DENY
    assert store.evaluate(name, "approval.decide").decision == DENY


@pytest.mark.parametrize("name", AI_AGENTS)
def test_ai_cannot_deploy_production_on_its_own(store, name):
    assert store.evaluate(name, "production.deploy").decision in (DENY, REQUIRE_APPROVAL)
    assert store.evaluate(name, "production.rollback").decision in (DENY, REQUIRE_APPROVAL)


def test_invariants_survive_a_policy_file_that_allows_everything(store):
    store.set_policy(PERMISSIVE, "test")
    for action in ("main.merge", "secrets.read", "iam.modify", "policy.modify", "approval.decide", "db.delete"):
        result = store.evaluate("rogue-agent", action)
        assert result.decision == DENY and result.rule == "invariant:never_for_ai", action
    assert store.evaluate("rogue-agent", "production.deploy").decision == REQUIRE_APPROVAL
    assert store.evaluate("rogue-agent", "repo.read").decision == ALLOW


def test_default_deny_and_unknown_identity(store):
    assert store.evaluate("review-agent", "branch.create").rule == "default-deny"
    assert store.evaluate("nobody", "repo.read").rule == "unknown-identity"


def test_write_constraints(store):
    store.reset("coding-agent")  # the lab boots in the unsafe scenario; this test is about the real policy
    files = {"app/x.py": ""}
    assert store.evaluate("coding-agent", "branch.write", {"branch": "feature/x", "files": files}).decision == ALLOW
    assert store.evaluate("coding-agent", "branch.write", {"branch": "main", "files": files}).decision == DENY
    for path in (".github/workflows/ci.yml", "policies/agents/coding-agent.yaml", ".env", "keys/deploy.pem"):
        assert store.evaluate("coding-agent", "branch.write", {"branch": "feature/x", "files": {path: ""}}).decision == DENY
    assert store.evaluate("test-agent", "branch.write", {"branch": "feature/x", "files": {"tests/t.py": ""}}).decision == ALLOW
    assert store.evaluate("test-agent", "branch.write", {"branch": "feature/x", "files": files}).decision == DENY


def test_policy_files_reject_unknown_fields():
    with pytest.raises(ValueError):
        AgentPolicy.from_yaml("agent: x\nallow_everything: true")


def test_human_rbac(store):
    assert store.human_can(["engineer"], "main.merge")
    assert not store.human_can(["architect"], "main.merge")
    assert not store.human_can(["engineer"], "approve.production")


# --- gateway (with database) ----------------------------------------------------------------------
def test_denied_call_does_not_execute_and_is_audited(db, gateway):
    result = gateway.call(db, agent("coding-agent"), "secrets.read", {"name": "aws-key"})
    assert result.decision == DENY and not result.executed and impl.MOCK_EFFECTS == []
    assert db.query(ToolCall).filter_by(tool="secrets.read", decision=DENY).count() == 1
    entry = db.query(AuditLog).filter_by(tool="secrets.read").one()
    assert entry.agent == "coding-agent" and entry.policy_decision == DENY and entry.result == "blocked"


def test_unknown_tool_is_denied(db, gateway):
    assert gateway.call(db, agent("coding-agent"), "shell.exec", {"cmd": "id"}).rule == "unknown-tool"


def test_agent_cannot_write_to_main_even_through_the_tool(db, gateway):
    result = gateway.call(db, agent("coding-agent"), "branch.write",
                          {"branch": "main", "files": {"app/main.py": "x"}, "message": "m"})
    assert result.decision == DENY
    from app import services
    with pytest.raises(Exception, match="Direct commits to main"):
        services.workspace("sandbox").write_files("main", {"a.py": ""}, "m", "coding-agent")


def _approval(db, status="pending", decided_by=None, action="production.deploy"):
    row = Approval(kind="production", step_key="production_approval", action=action, title="t",
                   required_role="release_manager", requested_by="deployment-advisor", status=status,
                   decided_by=decided_by, decided_at=utcnow() if decided_by else None)
    db.add(row)
    db.flush()
    return row


def test_ai_cannot_bypass_approval(db, gateway):
    pipeline, args = Actor("ci-pipeline", "system"), {"version": "9.9.9"}
    # no approval at all
    assert gateway.call(db, pipeline, "production.deploy", args).decision == REQUIRE_APPROVAL
    # forged, pending, and agent-"decided" approvals
    assert gateway.call(db, pipeline, "production.deploy", args, approval_id=424242).rule == "approval-check"
    assert gateway.call(db, pipeline, "production.deploy", args, approval_id=_approval(db).id).decision == DENY
    by_agent = _approval(db, "approved", decided_by="deployment-advisor")
    assert gateway.call(db, pipeline, "production.deploy", args, approval_id=by_agent.id).decision == DENY
    # an approval for a different action
    other = _approval(db, "approved", decided_by="sam", action="production.rollback")
    assert gateway.call(db, pipeline, "production.deploy", args, approval_id=other.id).decision == DENY
    # a real human approval works exactly once, and never for an AI identity
    real = _approval(db, "approved", decided_by="sam")
    as_agent = gateway.call(db, agent("deployment-advisor"), "production.deploy", args, approval_id=real.id)
    assert as_agent.rule == "invariant:pipeline-identity-only" and not as_agent.executed
    assert gateway.call(db, pipeline, "production.deploy", args, approval_id=real.id).ok
    assert gateway.call(db, pipeline, "production.deploy", args, approval_id=real.id).decision == DENY


def test_approval_endpoint_rejects_wrong_role_and_agents_have_no_route(client):
    client.post("/api/runs/1/advance")
    approval = client.post("/api/runs/1/advance").json()["approval"]
    wrong = client.post(f"/api/approvals/{approval['id']}/decide", headers={"X-User": "morgan"}, json={"decision": "approve"})
    assert wrong.status_code == 403
    unknown = client.post(f"/api/approvals/{approval['id']}/decide", headers={"X-User": "coding-agent"}, json={"decision": "approve"})
    assert unknown.status_code == 401
    via_mcp = client.post("/api/mcp", headers={"X-Agent-Id": "coding-agent"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "approval.decide", "arguments": {"approval_id": approval["id"]}}}).json()
    assert via_mcp["result"]["isError"] and via_mcp["result"]["_meta"]["decision"] == DENY


def test_kill_switch_blocks_tools_but_not_analysis(client, db, gateway):
    assert client.post("/api/flags", headers={"X-User": "alex"}, json={"kill_switch": True}).status_code == 403
    assert client.post("/api/flags", json={"kill_switch": True}).json()["kill_switch"] is True
    result = gateway.call(db, agent("coding-agent"), "repo.read", {})
    db.commit()
    assert result.decision == "BLOCKED_KILL_SWITCH" and result.reason == "TOOL EXECUTION DISABLED BY OPERATOR"
    blocked = client.post("/api/runs/1/advance").json()
    assert blocked["status"] == "blocked" and blocked["reason"] == "TOOL EXECUTION DISABLED BY OPERATOR"
    assert client.get("/api/security/capability/coding-agent").status_code == 200  # analysis still works
    client.post("/api/flags", json={"kill_switch": False})
    assert client.post("/api/runs/1/advance").json()["state"] == "REQUIREMENT_ANALYZED"


def test_dry_run_executes_nothing(client, db):
    client.post("/api/flags", json={"dry_run": True})
    plan = client.post("/api/runs/1/advance").json()
    assert plan["executed"] is False and plan["plan"][0]["decision"] == "DRY_RUN"
    assert "Would retrieve context" in plan["plan"][0]["would"]
    run = client.get("/api/runs/1").json()
    assert run["state"] == "REQUIREMENT_CREATED" and run["artifacts"] == {}
    assert db.query(ToolCall).filter(ToolCall.executed.is_(True)).count() == 0


def test_dry_run_reports_what_policy_would_decide(client):
    client.post("/api/runs/1/fast-forward", json={"until": "pr_creation"})
    client.post("/api/security/scenario", json={"name": "recommended"})
    client.post("/api/runs/1/fast-forward", json={"until": "pr_creation"})
    plan = {p["tool"]: p for p in client.post("/api/runs/1/dry-run").json()["plan"]}
    assert plan["pr.create"]["decision"] == "DRY_RUN"
    assert plan["main.merge"]["decision"] == DENY, "the planned merge is shown as denied"


def test_tool_output_is_redacted_before_the_agent_sees_it(db, gateway):
    result = gateway.call(db, agent("incident-agent"), "logs.search", {"query": "settings loaded"})
    assert result.ok and result.redactions >= 1
    assert "fake-db-Xk29mQ7pL2" not in str(result.output) and "[REDACTED]" in str(result.output)
