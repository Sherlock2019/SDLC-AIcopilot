"""End-to-end: one feature through the whole SDLC, with the controls exercised on the way."""
import pytest

from app.workflow.steps import STEPS

DANA, ALEX, PRIYA = {"X-User": "dana"}, {"X-User": "alex"}, {"X-User": "priya"}
state: dict = {}


@pytest.fixture(scope="module")
def api(module_client):
    return module_client


def run(api):
    return api.get("/api/runs/1").json()


def advance(api, headers=DANA):
    return api.post("/api/runs/1/advance", headers=headers).json()


def approve(api, headers=DANA, decision="approve", **extra):
    approval = run(api)["pending_approval"]
    return api.post(f"/api/approvals/{approval['id']}/decide", headers=headers, json={"decision": decision, **extra})


def test_lab_is_seeded_and_runs_without_api_keys(api):
    meta = api.get("/api/meta").json()
    assert meta["mock_ai"] is True and meta["provider"] == "mock"
    assert run(api)["state"] == "REQUIREMENT_CREATED"
    assert len(run(api)["steps"]) == len(STEPS)


def test_requirement_is_analyzed_with_grounded_citations(api):
    assert advance(api)["state"] == "REQUIREMENT_ANALYZED"
    analysis = run(api)["artifacts"]["requirement_analysis"]["analysis"]
    criteria = analysis["acceptance_criteria"]
    assert any("15 minutes" in c["text"] for c in criteria)
    assert sum(bool(c["citations"]) for c in criteria) >= 0.8 * len(criteria)
    assert analysis["conflicts"], "the SEC-12 conflict must be surfaced, not resolved silently"


def test_engine_cannot_pass_an_approval_gate(api):
    assert advance(api)["status"] == "waiting_approval"
    assert advance(api)["status"] == "waiting_approval"
    assert run(api)["state"] == "REQUIREMENT_ANALYZED"


def test_request_changes_sends_the_work_back(api):
    assert approve(api, decision="request_changes", comment="Mention per-IP limits").status_code == 200
    assert run(api)["current_step"]["key"] == "requirement_analysis"
    advance(api)
    assert run(api)["artifacts"]["requirement_analysis"]["feedback"][0]["comment"] == "Mention per-IP limits"
    assert approve(api).status_code == 200
    assert run(api)["state"] == "REQUIREMENT_APPROVED"


def test_context_trace_shows_selected_and_rejected_sources(api):
    advance(api)
    context = run(api)["artifacts"]["context"]
    assert context["used_tokens"] <= context["max_tokens"]
    reasons = {c["reason"] for c in context["candidates"] if c["status"] == "rejected"}
    assert any("injection" in r for r in reasons) or context["quarantined"] == []
    assert all(c["source"] != "old-documentation.md" for c in context["candidates"] if c["status"] == "selected")


def test_architecture_needs_the_architect_role(api):
    advance(api)
    proposal = run(api)["artifacts"]["architecture"]
    assert [o["key"] for o in proposal["options"]] == ["A", "B", "C"] and "flowchart" in proposal["mermaid"]
    assert approve(api, headers=ALEX).status_code == 403
    assert approve(api, headers=PRIYA, option="B").status_code == 200
    assert run(api)["artifacts"]["architecture"]["selected"] == "B"


def test_code_is_generated_on_a_feature_branch_only(api):
    assert advance(api)["state"] == "CODE_GENERATED"
    code = run(api)["artifacts"]["code"]
    assert code["branch"].startswith("feature/")
    assert "app/password_reset.py" in [f["path"] for f in code["files"]]
    assert "+++ b/app/password_reset.py" in code["diff"]
    git = api.get("/api/runs/1/git").json()
    assert all("agent" not in entry["author"] for entry in git["log"]), "no agent commit on main"


def test_tests_are_generated_and_really_executed(api):
    assert advance(api)["state"] == "TESTS_EXECUTED"
    tests = run(api)["artifacts"]["tests"]
    assert tests["executed_for_real"]
    assert tests["after"]["total"] > tests["before"]["total"] and tests["after"]["failed"] == 0
    assert tests["after"]["coverage"] > 80 and tests["after"]["coverage"] > tests["before"]["coverage"]
    assert {"unit", "api", "integration", "negative", "security"} <= set(tests["after"]["by_category"])


def test_review_has_structured_findings(api):
    advance(api)
    findings = run(api)["artifacts"]["review"]["findings"]
    assert findings
    for finding in findings:
        assert {"severity", "file", "line", "title", "why", "fix", "confidence"} <= set(finding)
    assert not [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]


def test_capability_audit_blocks_the_over_privileged_agent(api):
    result = advance(api)
    assert result["status"] == "blocked" and "unexpected path" in result["reason"]
    security = run(api)["artifacts"]["security"]
    paths = [f["path"] for f in security["capability"]["findings"] if f["severity"] == "CRITICAL"]
    assert any(p[0] == "Coding Agent" and "github.workflow.write" in p and p[-1] == "production.deploy" for p in paths)
    state["redteam_unsafe"] = api.post("/api/security/redteam", headers=DANA).json()
    assert state["redteam_unsafe"]["passed"] < state["redteam_unsafe"]["total"]


def test_applying_the_recommended_policy_removes_the_path(api):
    assert api.post("/api/security/scenario", headers=ALEX, json={"name": "recommended"}).status_code == 403
    result = api.post("/api/security/scenario", headers=DANA, json={"name": "recommended"}).json()
    assert result["before"]["critical"] > 0 and result["after"]["critical"] == 0
    assert advance(api)["state"] == "SECURITY_REVIEWED"
    report = api.post("/api/security/redteam", headers=DANA).json()
    assert report["passed"] == report["total"], [r["id"] for r in report["results"] if not r["passed"]]


def test_evaluation_produces_measurable_scores(api):
    assert advance(api)["state"] == "EVALUATED"
    evaluation = run(api)["artifacts"]["evaluation"]
    assert evaluation["score"] > 80 and evaluation["total"] == 26
    expiry = next(r for r in evaluation["results"] if r["id"] == "CODE-EXPIRY")
    assert expiry["actual"] == "PASS"


def test_pull_request_and_pipeline(api):
    assert advance(api)["state"] == "PR_OPENED"
    pr = api.get("/api/runs/1/pull-request").json()
    assert "## Business requirement" in pr["description"] and pr["data"]["comments"]
    assert advance(api)["state"] == "CI_PASSED"
    pipeline = api.get("/api/pipelines?run_id=1").json()[0]
    assert all(g["passed"] for g in pipeline["gates"])


def test_only_a_human_merges_and_only_after_approval(api):
    assert approve(api).status_code == 200
    assert api.post("/api/runs/1/advance", headers=PRIYA).status_code == 403, "architect has no merge right"
    assert advance(api, ALEX)["state"] == "MERGED"
    assert api.get("/api/runs/1/pull-request").json()["merged_by"] == "alex"


def test_production_needs_a_release_manager(api):
    assert advance(api)["state"] == "STAGING_DEPLOYED"
    deployment = run(api)["artifacts"]["deployment"]
    assert deployment["production_request"]["decision"] == "REQUIRE_APPROVAL"
    assert deployment["production_request"]["executed"] is False
    assert approve(api, headers=ALEX).status_code == 403
    assert approve(api, headers={"X-User": "sam"}).status_code == 200
    assert advance(api)["state"] == "PRODUCTION_DEPLOYED"
    production = next(e for e in api.get("/api/deployments").json()["environments"] if e["env"] == "PRODUCTION")
    assert production["version"] == "1.4.0" and production["approved_by"] == "sam"


def test_incident_rca_and_human_approved_rollback(api):
    assert advance(api)["state"] == "MONITORING"
    assert advance(api)["state"] == "INCIDENT_DETECTED"
    assert advance(api)["state"] == "EVIDENCE_COLLECTED"
    assert advance(api)["state"] == "REMEDIATION_RECOMMENDED"
    incident = api.get("/api/runs/1/incident").json()
    top = incident["data"]["hypotheses"][0]
    assert top["id"] == "H1" and top["confidence"] > 0.6
    assert incident["data"]["suspects"][0]["version"] == "1.4.1"
    assert incident["data"]["recommendation"]["agent_request"]["executed"] is False
    assert next(e for e in api.get("/api/deployments").json()["environments"] if e["env"] == "PRODUCTION")["version"] == "1.4.1"
    assert approve(api, headers={"X-User": "sam"}).status_code == 200
    assert advance(api)["state"] == "SERVICE_RESTORED"
    assert next(e for e in api.get("/api/deployments").json()["environments"] if e["env"] == "PRODUCTION")["version"] == "1.4.0"
    assert advance(api)["state"] == "RCA_DOCUMENTED"
    assert advance(api)["state"] == "COMPLETED"
    assert run(api)["status"] == "completed"


def test_rca_document_feeds_back_into_retrieval(api):
    result = api.post("/api/context/search", json={"query": "reset token setting renamed missing in production"}).json()
    assert any(c["source"].startswith("incidents/INC-") and c["status"] == "selected" for c in result["candidates"])


def test_everything_is_in_the_audit_log(api):
    log = api.get("/api/audit?run_id=1&limit=500").json()
    actions = {entry["action"] for entry in log["entries"]}
    assert {"agent.run", "tool.call", "approval.approved", "step.completed"} <= actions
    assert api.get("/api/audit?q=production.rollback").json()["total"] >= 2
    productivity = api.get("/api/productivity?run_id=1").json()
    assert productivity["measured"]["ai_cost_usd"] > 0 and productivity["measured"]["human_approvals"] == 5


def test_dashboards_respond(api):
    for path in ("/api/observability/app", "/api/observability/ai", "/api/observability/security",
                 "/api/governance/agents", "/api/learn", "/api/architecture", "/api/github", "/api/mcp/tools",
                 "/api/security/secrets-demo", "/api/security/injection-demo", "/api/context/stats",
                 "/api/evals/suite", "/api/incidents", "/api/observability/logs", "/api/security/policies",
                 "/api/security/capability", "/api/evals/history", "/api/evals/promptfoo", "/api/runs"):
        assert api.get(path).status_code == 200, path
