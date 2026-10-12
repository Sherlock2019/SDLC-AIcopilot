"""The SDLC journey as an explicit list of steps.

Each step declares who acts (AI agent, human, or automated system), which state it leads to,
which tools it plans to use (shown by dry-run mode), and a handler. Handlers do their work only
through RunContext, so every tool call is policy-checked and audited.
"""
from __future__ import annotations

import ast
import re
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable

from sqlalchemy.orm.attributes import flag_modified

from ..agents import definitions as A
from ..agents.base import RunContext, StepBlocked
from ..core import capability, injection, sast, secrets_scan
from ..models import (AgentRun, Approval, Architecture, Deployment, Incident, Pipeline, PullRequest, Requirement,
                      SecurityFinding, ToolCall, utcnow)
from ..ops import deploy as deploy_ops
from ..ops import rca as rca_ops
from ..ops import telemetry
from ..providers.mock_tasks import is_password_reset
from ..tools import sandbox

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


@dataclass
class Step:
    key: str
    title: str
    kind: str                      # ai | approval | human_action | system
    state_done: str
    page: str                      # frontend route that shows this step
    description: str
    agent: str = ""                # policy identity that acts
    handler: Callable | None = None
    plan: list = field(default_factory=list)   # [(identity, tool, args)] used by dry-run
    approval: dict = field(default_factory=dict)
    permission: str = ""           # human permission for human_action steps
    rework_to: str = ""            # step to return to when a human requests changes
    learn: str = ""                # Learn Mode stage key


# --- small helpers ------------------------------------------------------------------------------
def _sources(retrieval: dict, compressed: bool = True) -> list[dict]:
    return [{"citation": r["citation"], "source": r["source"], "heading": r["heading"],
             "text": r["compressed_text"] if compressed else r["text"]}
            for r in retrieval["candidates"] if r["status"] == "selected"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "feature"


def _line_of(source: str, anchor: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if anchor in line:
            return number
    return 1


def _summary(result: dict) -> dict:
    return {k: result.get(k) for k in ("total", "passed", "failed", "coverage", "duration_s", "by_category", "commit")}


def _severity_counts(findings: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    return counts


def _update_stage(pipeline: Pipeline, key: str, **changes) -> None:
    pipeline.stages = [{**stage, **changes} if stage["key"] == key else stage for stage in pipeline.stages]
    flag_modified(pipeline, "stages")


def _pipeline(ctx: RunContext) -> Pipeline:
    return ctx.db.query(Pipeline).filter(Pipeline.run_id == ctx.run.id).order_by(Pipeline.id.desc()).first()


def _incident(ctx: RunContext) -> Incident:
    return ctx.db.query(Incident).filter(Incident.run_id == ctx.run.id).order_by(Incident.id.desc()).first()


def _set_incident(incident: Incident, phase: str, **data) -> None:
    timeline = (incident.data or {}).get("timeline", []) + [{"phase": phase, "at": utcnow().isoformat() + "Z"}]
    incident.phase = phase
    incident.data = {**(incident.data or {}), **data, "timeline": timeline}
    flag_modified(incident, "data")


# --- 1. requirement -----------------------------------------------------------------------------
def requirement_analysis(ctx: RunContext) -> None:
    text = ctx.run.requirement_text
    input_flags = [f.as_dict() for f in injection.scan(text)]
    expansion = ("token expiry single-use logs sessions rate limit API status codes password policy"
                 if is_password_reset(text) else "security policy API guidelines coding standards tests")
    retrieval = ctx.tool(A.REQUIREMENT.id, "context.search", query=f"{text} {expansion}", max_tokens=3500).output
    feedback = (ctx.artifact("feedback") or {}).get("requirement_analysis", [])
    analysis = ctx.llm(A.REQUIREMENT, "requirement_analysis",
                       {"requirement": text, "sources": _sources(retrieval, compressed=False), "feedback": feedback},
                       "Analyse the business request. Ground every criterion in the context.")
    ctx.save("requirement_analysis", {
        "requirement": text, "analysis": analysis, "citations": retrieval["citations"],
        "retrieval": {k: retrieval[k] for k in ("query", "max_tokens", "used_tokens", "by_source")},
        "input_injection_flags": input_flags, "feedback": feedback,
    })
    ctx.db.add(Requirement(run_id=ctx.run.id, text=text, analysis=analysis))


# --- 2. context ---------------------------------------------------------------------------------
def context_retrieval(ctx: RunContext) -> None:
    analysis = ctx.artifact("requirement_analysis")["analysis"]
    criteria = " ".join(c["text"] for c in analysis.get("acceptance_criteria", []))
    query = f"{ctx.run.requirement_text} {criteria} architecture database schema coding standards"
    retrieval = ctx.tool(A.CONTEXT.id, "context.search", query=query, max_tokens=4000).output
    ctx.save("context", retrieval)


# --- 3. architecture ----------------------------------------------------------------------------
def architecture_design(ctx: RunContext) -> None:
    ctx.tool(A.ARCHITECTURE.id, "repo.read")
    ctx.tool(A.ARCHITECTURE.id, "repo.read", path="app/db.py")
    proposal = ctx.llm(A.ARCHITECTURE, "architecture", {
        "requirement": ctx.run.requirement_text,
        "analysis": {k: v for k, v in ctx.artifact("requirement_analysis")["analysis"].items() if k != "_meta"},
        "sources": _sources(ctx.artifact("context")),
        "feedback": (ctx.artifact("feedback") or {}).get("architecture_design", []),
    }, "Propose three options with trade-offs and recommend one.")
    proposal["selected"] = None
    ctx.save("architecture", proposal)
    ctx.db.add(Architecture(run_id=ctx.run.id, proposal=proposal))


# --- 4. code ------------------------------------------------------------------------------------
def _validate_generated_files(files, allowed_prefix: str) -> list[dict]:
    """Model output is untrusted input. Nothing is written until every check passes."""
    checks = []
    ok_shape = isinstance(files, dict) and files and all(isinstance(p, str) and isinstance(c, str)
                                                         for p, c in files.items())
    checks.append({"check": "Output is a non-empty map of path -> file content", "ok": bool(ok_shape)})
    if not ok_shape:
        return checks
    bad_paths = [p for p in files if p.startswith("/") or ".." in Path(p).parts or not p.startswith(allowed_prefix)]
    checks.append({"check": f"Every path is relative and under {allowed_prefix}", "ok": not bad_paths,
                   "detail": ", ".join(bad_paths)})
    broken = []
    for path, content in files.items():
        if path.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as exc:
                broken.append(f"{path}: {exc.msg}")
    checks.append({"check": "Every Python file parses", "ok": not broken, "detail": "; ".join(broken)})
    secrets = [s for path, content in files.items() for s in secrets_scan.scan_text(content, "source", path)]
    checks.append({"check": "No credential in generated files", "ok": not secrets,
                   "detail": ", ".join(f"{s.source}:{s.line}" for s in secrets)})
    return checks


def code_generation(ctx: RunContext) -> None:
    agent = A.CODE.id
    branch = f"feature/{_slug(ctx.run.title)}-run{ctx.run.id}"
    architecture = ctx.artifact("architecture")
    option = next(o for o in architecture["options"] if o["key"] == (architecture.get("selected") or architecture["recommended"]))
    ctx.tool(agent, "repo.read")
    existing = {path: ctx.tool(agent, "repo.read", path=path).output["content"]
                for path in ("app/main.py", "app/auth.py", "app/db.py", "app/config.py")}
    ctx.tool(agent, "repo.search", query="get_db")
    standards = ctx.tool(agent, "context.search", query="coding standards SQL parameterized logging secrets tests",
                         max_tokens=1500, doc_types=["standard", "policy"]).output
    ctx.tool(agent, "branch.create", name=branch)
    generated = ctx.llm(A.CODE, "code_generation", {
        "requirement": ctx.run.requirement_text, "option": option, "details": architecture.get("details", {}),
        "acceptance_criteria": ctx.artifact("requirement_analysis")["analysis"].get("acceptance_criteria", []),
        "existing_files": existing, "sources": _sources(standards),
    }, "Implement the approved option. Return complete files under app/.")
    files = generated.get("files")
    validation = _validate_generated_files(files, "app/")
    if not all(check["ok"] for check in validation):
        ctx.save("code", {"branch": branch, "validation": validation, "rejected": True})
        raise StepBlocked("Generated code failed output validation and was not written.", {"validation": validation})
    commit = ctx.tool(agent, "branch.write", branch=branch, files=files,
                      message=f"Add {ctx.run.title.lower()}").output["commit"]
    git = ctx.git
    notes = [generated["notice"]] if generated.get("notice") else []
    if option["key"] != architecture["recommended"] and generated["_meta"]["scripted"]:
        notes.append(f"The architect selected option {option['key']}. The mock provider only ships an "
                     f"implementation of option {architecture['recommended']}; a real provider would follow the selection.")
    ctx.save("code", {
        "branch": branch, "base": "main", "commit": commit, "files": git.diff_stats("main", branch),
        "diff": git.diff("main", branch), "reasoning_summary": generated.get("reasoning_summary", []),
        "dependencies": generated.get("dependencies", []), "risks": generated.get("risks", []),
        "validation": validation, "option": option["key"], "notes": notes, "_meta": generated["_meta"],
    })


# --- 5. tests -----------------------------------------------------------------------------------
def test_generation(ctx: RunContext) -> None:
    agent, code = A.TEST.id, ctx.artifact("code")
    branch = code["branch"]
    before = ctx.tool(agent, "test.run", ref="main").output
    source = {f["path"]: ctx.tool(agent, "repo.read", path=f["path"], ref=branch).output["content"]
              for f in code["files"] if f["path"].startswith("app/")}
    policy = ctx.tool(agent, "context.search", query="password reset security rules incidents token session",
                      max_tokens=1500, doc_types=["policy", "incident"]).output
    generated = ctx.llm(A.TEST, "test_generation", {
        "acceptance_criteria": ctx.artifact("requirement_analysis")["analysis"].get("acceptance_criteria", []),
        "changed_files": source, "sources": _sources(policy),
    }, "Write the tests. One security test per security criterion.")
    files = generated.get("files")
    validation = _validate_generated_files(files, "tests/")
    if not all(check["ok"] for check in validation):
        ctx.save("tests", {"validation": validation, "rejected": True})
        raise StepBlocked("Generated tests failed output validation and were not written.", {"validation": validation})
    commit = ctx.tool(agent, "branch.write", branch=branch, files=files, message="Add tests for the change").output["commit"]
    after = ctx.tool(agent, "test.run", ref=branch).output
    git = ctx.git
    ctx.save("tests", {
        "before": _summary(before), "after": after, "generated_files": sorted(files), "commit": commit,
        "strategy": generated.get("strategy", []), "validation": validation, "_meta": generated["_meta"],
        "executed_for_real": bool(after.get("ran")),
    })
    ctx.save("code", {**ctx.artifact("code"), "files": git.diff_stats("main", branch), "diff": git.diff("main", branch)})


# --- 6. review ----------------------------------------------------------------------------------
def ai_review(ctx: RunContext) -> None:
    agent, branch = A.REVIEW.id, ctx.artifact("code")["branch"]
    change = ctx.tool(agent, "pr.read", branch=branch).output
    files = {f["path"]: ctx.tool(agent, "repo.read", path=f["path"], ref=branch).output["content"]
             for f in change["files"] if f["status"] != "deleted"}
    source = {p: c for p, c in files.items() if not p.startswith("tests/")}
    tests = {p: c for p, c in files.items() if p.startswith("tests/")}
    static = [f.as_dict() for f in sast.scan_files(source) + sast.missing_test_findings(source, tests)]
    guidance = ctx.tool(agent, "context.search", query="coding standards API guidelines review checklist",
                        max_tokens=1200, doc_types=["standard"]).output
    review = ctx.llm(A.REVIEW, "code_review", {"files": source, "diff_files": change["files"],
                                               "static_findings": static, "sources": _sources(guidance)},
                     "Review the change. Do not repeat the static findings.")
    findings = list(static)
    for item in review.get("findings", []):
        if not isinstance(item, dict) or item.get("severity") not in SEVERITY_ORDER or item.get("file") not in files:
            continue  # drop malformed findings and findings about files that are not in the change
        line = item.get("line") or _line_of(files[item["file"]], item.get("anchor", "\0"))
        findings.append({
            "rule": "LLM", "source": "llm", "severity": item["severity"], "category": item.get("category", "review"),
            "file": item["file"], "line": int(line), "title": item.get("title", ""), "why": item.get("why", ""),
            "fix": item.get("fix", ""), "confidence": float(item.get("confidence", 0.5)),
            "reviewer_note": item.get("reviewer_note", ""),
        })
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["file"], f["line"]))
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"R-{index}"
    ctx.save("review", {"findings": findings, "summary": review.get("summary", ""),
                        "counts": _severity_counts(findings), "files_reviewed": sorted(files),
                        "static_rule_findings": len(static), "llm_findings": len(findings) - len(static),
                        "_meta": review["_meta"]})


# --- 7. security --------------------------------------------------------------------------------
def security_review(ctx: RunContext) -> None:
    agent, code = A.SECURITY.id, ctx.artifact("code")
    scan = ctx.tool(agent, "security.scan", ref=code["branch"]).output
    ctx.tool(agent, "audit.read", limit=50)
    added = "\n".join(line[1:] for line in code["diff"].splitlines() if line.startswith("+") and not line.startswith("+++"))
    diff_secrets = [s.as_dict() for s in secrets_scan.scan_text(added, "source", "pull request diff")]
    quarantined = (ctx.artifact("context") or {}).get("quarantined", [])
    input_flags = ctx.artifact("requirement_analysis").get("input_injection_flags", [])
    audits = [capability.audit_agent(name, ctx.store) for name, policy in sorted(ctx.store.policies.items())
              if policy.kind == "ai"]
    capability_findings = [f for report in audits for f in report["findings"]]

    ctx.db.query(SecurityFinding).filter(SecurityFinding.run_id == ctx.run.id).delete()
    for finding in scan["findings"]:
        ctx.db.add(SecurityFinding(run_id=ctx.run.id, source="sast", severity=finding["severity"],
                                   category=finding["category"], title=finding["title"], detail=finding["why"],
                                   file=finding["file"], line=finding["line"], recommendation=finding["fix"]))
    for item in quarantined:
        ctx.db.add(SecurityFinding(run_id=ctx.run.id, source="injection", severity="HIGH", category="prompt-injection",
                                   title=f"Prompt injection quarantined in {item['source']}", detail=item["reason"],
                                   file=item["source"], recommendation="Instruction ignored. Review the document source.",
                                   status="mitigated"))
    for finding in capability_findings:
        ctx.db.add(SecurityFinding(
            run_id=ctx.run.id, source="capability", severity=finding["severity"], category="transitive-access",
            title=f"{finding['title']}: {finding['agent']} can reach {finding['action']}",
            detail=" -> ".join(finding["path"]), recommendation=" ".join(finding["recommendation"]),
            status="accepted" if finding["accepted_risk"] else "open"))

    counts = _severity_counts(scan["findings"])
    critical_paths = [f for f in capability_findings if f["severity"] == "CRITICAL"]
    blockers = []
    if counts.get("CRITICAL"):
        blockers.append(f"{counts['CRITICAL']} critical vulnerability finding(s) in the generated code")
    if diff_secrets:
        blockers.append(f"{len(diff_secrets)} credential(s) in the diff")
    if critical_paths:
        blockers.append(f"{len(critical_paths)} unexpected path(s) from an AI agent to a critical action")
    ctx.save("security", {
        "sast": scan["findings"], "sast_counts": counts, "files_scanned": scan["files_scanned"],
        "secrets_in_diff": diff_secrets, "injection": {"quarantined": quarantined, "input_flags": input_flags},
        "capability": {"agents_audited": len(audits), "findings": capability_findings,
                       "critical": len(critical_paths),
                       "by_agent": [{"agent": r["agent"], "status": r["summary"]["status"],
                                     "critical": r["summary"]["critical"]} for r in audits]},
        "gate": {"passed": not blockers, "blockers": blockers},
    })
    if blockers:
        raise StepBlocked("Security gate failed: " + "; ".join(blockers) + ".",
                          {"blockers": blockers, "fix_page": "/security"})


# --- 8. evaluation ------------------------------------------------------------------------------
def evaluation(ctx: RunContext) -> None:
    result = ctx.tool(A.EVALUATION.id, "eval.run", suite="password-reset").output
    ctx.save("evaluation", result)
    if not result["gate_passed"]:
        raise StepBlocked(f"AI evaluation score {result['score']}% is not above the {result['threshold']}% gate.",
                          {"score": result["score"], "failed": [r["id"] for r in result["results"] if not r["passed"]]})


# --- 9. pull request ----------------------------------------------------------------------------
def pr_confidence(tests: dict, evaluation_score: float, counts: dict) -> dict:
    pass_ratio = tests["passed"] / tests["total"] if tests["total"] else 0
    coverage = min((tests.get("coverage") or 0) / 90, 1)
    findings = max(0.0, 1 - 0.6 * counts.get("CRITICAL", 0) - 0.4 * counts.get("HIGH", 0)
                   - 0.15 * counts.get("MEDIUM", 0) - 0.05 * counts.get("LOW", 0))
    value = 0.35 * evaluation_score / 100 + 0.30 * pass_ratio + 0.15 * coverage + 0.20 * findings
    return {"value": round(100 * value), "formula": "35% evaluation score + 30% test pass rate + 15% coverage "
                                                     "(capped at 90%) + 20% open-finding penalty",
            "parts": {"evaluation": evaluation_score, "test_pass_rate": round(100 * pass_ratio, 1),
                      "coverage": tests.get("coverage"), "finding_factor": round(findings, 2)}}


def pr_creation(ctx: RunContext) -> None:
    code, tests, review = ctx.artifact("code"), ctx.artifact("tests"), ctx.artifact("review")
    evaluation_result, architecture = ctx.artifact("evaluation"), ctx.artifact("architecture")
    option = next(o for o in architecture["options"] if o["key"] == code["option"])
    architect = ctx.db.query(Approval).filter(Approval.run_id == ctx.run.id, Approval.kind == "architecture",
                                              Approval.status == "approved").order_by(Approval.id.desc()).first()
    open_findings = [f for f in review["findings"] if f["severity"] != "INFO"]
    counts = _severity_counts(open_findings)
    confidence = pr_confidence(tests["after"], evaluation_result["score"], counts)
    draft = ctx.llm(A.CODE, "pr_description", {
        "title": ctx.run.title, "requirement": ctx.run.requirement_text, "option": option,
        "architect": architect.decided_by if architect else "the architect", "files": code["files"],
        "tests": _summary(tests["after"]), "coverage_before": tests["before"]["coverage"],
        "risks": code["risks"] or ["None stated"], "findings": open_findings, "severity_counts": counts,
        "evaluation": {k: evaluation_result[k] for k in ("score", "security_score", "passed", "total")},
    }, "Draft the pull request description.")
    number = ctx.tool(A.CODE.id, "pr.create", branch=code["branch"], title=str(draft["title"])[:200],
                      body=str(draft["body"])).output["number"]
    comment = "\n".join([f"AI first-pass review: {review['summary']}", ""] + [
        f"- [{f['severity']}] {f['file']}:{f['line']} {f['title']} (confidence {round(100 * f['confidence'])}%)"
        for f in review["findings"]])
    ctx.tool(A.REVIEW.id, "pr.comment", body=comment, number=number)
    pr = ctx.db.query(PullRequest).filter(PullRequest.run_id == ctx.run.id, PullRequest.number == number).one()
    pr.data = {**(pr.data or {}), "stats": {
        "confidence": confidence, "tests": {"passed": tests["after"]["passed"], "total": tests["after"]["total"]},
        "coverage": tests["after"]["coverage"], "security": counts,
        "evaluation": evaluation_result["score"], "security_score": evaluation_result["security_score"]}}
    flag_modified(pr, "data")
    ctx.save("pr", {"number": number, "branch": code["branch"]})


# --- 10. CI -------------------------------------------------------------------------------------
def ci_pipeline(ctx: RunContext) -> None:
    identity, code = "ci-pipeline", ctx.artifact("code")
    branch, evaluation_result, security = code["branch"], ctx.artifact("evaluation"), ctx.artifact("security")
    ctx.tool(identity, "repo.read", ref=branch)
    with tempfile.TemporaryDirectory(prefix="lab-ci-") as directory:
        ctx.git.export(branch, Path(directory))
        lint = sandbox.run_ruff(Path(directory))
    tests = ctx.tool(identity, "test.run", ref=branch).output
    denied = ctx.db.query(ToolCall).filter(ToolCall.run_id == ctx.run.id, ToolCall.decision == "DENY",
                                           ToolCall.actor_type != "human", ToolCall.tag == "").count()
    critical = security["sast_counts"].get("CRITICAL", 0) + security["capability"]["critical"]
    unit = [t for t in tests["tests"] if t["category"] in ("unit", "api", "negative", "security")]
    integration = [t for t in tests["tests"] if t["category"] == "integration"]
    gates = [
        {"name": "Tests must pass", "value": f"{tests['passed']}/{tests['total']}", "passed": tests["failed"] == 0 and tests["total"] > 0},
        {"name": "Coverage > 80%", "value": f"{tests['coverage']}%", "passed": (tests["coverage"] or 0) > 80},
        {"name": "No CRITICAL security finding", "value": str(critical), "passed": critical == 0},
        {"name": "AI evaluation score > 80%", "value": f"{evaluation_result['score']}%", "passed": evaluation_result["score"] > 80},
        {"name": "No policy violation", "value": str(denied), "passed": denied == 0},
    ]
    lint_ok = lint["passed"] or not lint["available"]

    def stage(key, name, ok, duration, logs, ai="", human="", simulated=False, status=None):
        return {"key": key, "name": name, "status": status or ("passed" if ok else "failed"),
                "duration_s": duration, "logs": logs, "ai": ai, "human": human, "simulated": simulated}

    stages = [
        stage("source", "SOURCE", True, 1.2, [f"checkout {branch} @ {code['commit']}", f"{len(code['files'])} files changed"],
              ai="Branch and commits authored by Coding Agent and Test Agent"),
        stage("lint", "LINT", lint_ok, lint["duration_s"], (lint["output"].strip() or "ruff: all checks passed").splitlines()[-8:]
              if lint["available"] else ["ruff is not installed in this environment - stage skipped"],
              status=None if lint["available"] else "skipped"),
        stage("test", "TEST", gates[0]["passed"] and gates[1]["passed"], tests["duration_s"],
              [f"unit/api/negative/security: {sum(t['status'] == 'passed' for t in unit)}/{len(unit)} passed",
               f"integration: {sum(t['status'] == 'passed' for t in integration)}/{len(integration)} passed",
               f"coverage {tests['coverage']}% (gate > 80%)"], ai="Tests generated by Test Agent, executed in the sandbox"),
        stage("eval", "AI EVAL", gates[3]["passed"], evaluation_result.get("duration_s", 0),
              [f"{evaluation_result['passed']}/{evaluation_result['total']} fixtures passed",
               f"overall {evaluation_result['score']}%, security {evaluation_result['security_score']}% (gate > 80%)"],
              ai="Evaluation Agent scores AI output with deterministic evaluators"),
        stage("security", "SECURITY", gates[2]["passed"] and gates[4]["passed"], 2.1,
              [f"static analysis: {sum(security['sast_counts'].values())} findings, {security['sast_counts'].get('CRITICAL', 0)} critical",
               f"secrets in diff: {len(security['secrets_in_diff'])}",
               f"capability audit: {security['capability']['critical']} critical path(s)",
               f"policy violations by agents: {denied}"], ai="Security Agent: scanners and capability auditor"),
        stage("build", "BUILD", True, 18.4, ["docker build -t customer-portal-api:candidate .",
                                             "image built (simulated in this local pipeline)"], simulated=True),
        stage("staging", "STAGING", True, 0, ["waiting for merge"], status="pending", simulated=True),
        stage("approval", "HUMAN APPROVAL", True, 0, ["waiting for Release Manager"], status="pending",
              human="Release Manager approves production"),
        stage("production", "PRODUCTION", True, 0, ["simulation only"], status="pending", simulated=True),
    ]
    passed = all(g["passed"] for g in gates) and lint_ok
    ctx.db.add(Pipeline(run_id=ctx.run.id, name="ai-sdlc-ci", ref=branch, status="passed" if passed else "failed",
                        stages=stages, gates=gates))
    ctx.db.flush()
    pr = ctx.db.query(PullRequest).filter(PullRequest.run_id == ctx.run.id).order_by(PullRequest.id.desc()).first()
    pr.data = {**(pr.data or {}), "ci": "passed" if passed else "failed"}
    flag_modified(pr, "data")
    ctx.save("ci", {"status": "passed" if passed else "failed", "gates": gates})
    if not passed:
        failed = [g["name"] for g in gates if not g["passed"]] + ([] if lint_ok else ["Lint"])
        raise StepBlocked("Pipeline failed quality gates: " + ", ".join(failed) + ".", {"gates": gates})


# --- 11. merge (human) --------------------------------------------------------------------------
def merge(ctx: RunContext) -> None:
    pr = ctx.db.query(PullRequest).filter(PullRequest.run_id == ctx.run.id).order_by(PullRequest.id.desc()).first()
    if pr.status != "approved":
        raise StepBlocked("The pull request has not been approved by a human reviewer.")
    if (pr.data or {}).get("ci") != "passed":
        raise StepBlocked("The pipeline has not passed.")
    result = ctx.gateway.call(ctx.db, ctx.user, "main.merge", {"number": pr.number}, run=ctx.run)
    if not result.ok:
        raise StepBlocked(f"Merge refused: {result.reason}")
    ctx.save("merge", {"number": pr.number, "merged_by": ctx.user.id, "commit": result.output["commit"]})


# --- 12. staging --------------------------------------------------------------------------------
def staging_deploy(ctx: RunContext) -> None:
    identity = "ci-pipeline"
    config = ctx.tool(identity, "repo.read", path="app/config.py", ref="main").output["content"]
    version = (re.search(r'APP_VERSION\s*=\s*"([^"]+)"', config) or [None, "0.0.0"])[1]
    environments = [ctx.tool(identity, "deploy.staging", env=env, version=version).output for env in ("DEV", "TEST", "STAGING")]
    pipeline = _pipeline(ctx)
    _update_stage(pipeline, "staging", status="passed", duration_s=6.3, logs=[
        f"SIMULATE_STAGING_DEPLOYMENT version={version}", *[f"{e['env']}: health {e['health']['status']}" for e in environments]])
    _update_stage(pipeline, "approval", status="waiting")

    advisor, tests, evaluation_result = A.DEPLOYMENT.id, ctx.artifact("tests")["after"], ctx.artifact("evaluation")
    ctx.tool(advisor, "ci.read")
    ctx.tool(advisor, "deploy.read")
    ctx.tool(advisor, "metrics.read", minutes=15)
    blockers = [f"{e['env']} health check failed" for e in environments if e["health"]["status"] != "healthy"]
    advice = ctx.llm(A.DEPLOYMENT, "deployment_advice", {
        "version": version, "tests_total": tests["total"], "coverage": tests["coverage"],
        "eval_score": evaluation_result["score"], "blockers": blockers}, "Recommend GO or NO-GO for production.")
    request = ctx.tool(advisor, "production.deploy", required=False, version=version)
    ctx.save("deployment", {"version": version, "environments": environments, "advice": advice,
                            "production_request": request.as_dict()})


def production_deploy(ctx: RunContext) -> None:
    approval = ctx.db.query(Approval).filter(Approval.run_id == ctx.run.id, Approval.kind == "production",
                                             Approval.status == "approved").order_by(Approval.id.desc()).first()
    version = ctx.artifact("deployment")["version"]
    ctx.tool("ci-pipeline", "production.deploy", approval_id=approval.id if approval else -1, version=version,
             approved_by=approval.decided_by if approval else "")
    pipeline = _pipeline(ctx)
    _update_stage(pipeline, "approval", status="passed", logs=[f"approved by {approval.decided_by}"])
    _update_stage(pipeline, "production", status="passed", duration_s=4.8,
                  logs=[f"PRODUCTION-SIMULATION now runs {version}", "nothing real was deployed"])
    pipeline.status = "completed"
    ctx.save("deployment", {**ctx.artifact("deployment"), "production": {
        "version": version, "approved_by": approval.decided_by, "deployed_by": "ci-pipeline", "simulation": True}})


# --- 13. monitoring -----------------------------------------------------------------------------
def monitoring(ctx: RunContext) -> None:
    metrics = ctx.tool(A.INCIDENT.id, "metrics.read", minutes=15).output
    points = metrics["points"]
    ctx.save("monitoring", {
        "version": ctx.artifact("deployment")["version"], "health": deploy_ops.health(ctx.db, "PRODUCTION"),
        "window_minutes": 15, "simulated": True,
        "error_rate_pct": round(sum(p["error_rate_pct"] for p in points) / len(points), 2),
        "latency_p95_ms": round(sum(p["latency_p95_ms"] for p in points) / len(points), 1),
        "requests": sum(p["requests"] for p in points),
        "verdict": "Release is healthy. Error rate and latency are inside their normal range.",
    })


# --- 14. incident -------------------------------------------------------------------------------
def simulate_incident(ctx: RunContext) -> None:
    """Human-triggered drill. A follow-up release with a configuration mistake reaches production."""
    now = utcnow()
    current = deploy_ops.current(ctx.db, "PRODUCTION")
    # Simulated clock: the drill pretends the healthy release has been live for a while, so the
    # bad release (8 minutes ago) and the first errors (6 minutes ago) sit after it on the timeline.
    current.ts = min(current.ts, now - timedelta(minutes=25))
    major, minor, patch = (current.version.split(".") + ["0", "0"])[:3]
    bad_version = f"{major}.{minor}.{int(patch) + 1}"
    ctx.db.add(Deployment(
        run_id=ctx.run.id, env="PRODUCTION", version=bad_version, deployed_by="ci-pipeline",
        approved_by="release manager (simulated)", ts=now - timedelta(minutes=8),
        notes="Config refactor: reset token lifetime is now configured in minutes",
        data={"diff": telemetry.BAD_RELEASE_DIFF, "pull_request": "#207 (simulated, written by a human)"}))
    key = f"INC-{now:%Y}-{ctx.run.id:03d}"
    incident = Incident(run_id=ctx.run.id, key=key, title="Password reset API returns HTTP 500", severity="",
                        status="open", phase="DETECT", started_at=now - timedelta(minutes=6), data={
                            "bad_version": bad_version, "previous_version": current.version,
                            "timeline": [{"phase": "DETECT", "at": now.isoformat() + "Z"}]})
    ctx.db.add(incident)
    ctx.db.flush()
    ctx.save("incident", {"key": key, "bad_version": bad_version})


def incident_triage(ctx: RunContext) -> None:
    agent, incident = A.INCIDENT.id, _incident(ctx)
    metrics = ctx.tool(agent, "metrics.read", minutes=45).output
    detection = rca_ops.detect(metrics["points"])
    if detection is None:
        raise StepBlocked("No anomaly found in the metrics. There is nothing to triage.")
    errors = ctx.tool(agent, "logs.search", query="ERROR", limit=80)
    history = ctx.tool(agent, "deploy.read").output["history"]
    signatures = rca_ops.error_signatures(errors.output)
    route_error = max(p["reset_route_error_rate_pct"] for p in metrics["points"])
    level = rca_ops.severity(detection["peak_error_rate_pct"], route_error)
    triage = ctx.llm(A.INCIDENT, "incident_triage", {
        "route": telemetry.RESET_ROUTE, "error_rate_pct": route_error, "started": detection["onset"],
        "overall_error_rate_pct": detection["peak_error_rate_pct"]}, "Summarise impact and severity.")
    incident.severity = level
    _set_incident(incident, "TRIAGE", detection=detection, triage=triage, severity=level)
    _set_incident(incident, "COLLECT EVIDENCE", evidence={
        "metrics": {"points": metrics["points"][-30:], "deployments": metrics["deployments"]},
        "log_sample": errors.output[:6], "error_count": len(errors.output), "signatures": signatures,
        "deployments": [{k: d[k] for k in ("version", "ts", "kind", "notes", "approved_by", "deployed_by")} | {
            "diff": d.get("diff", "")} for d in history[:4]],
        "redactions_in_logs": errors.redactions,
    })


def rca_analysis(ctx: RunContext) -> None:
    agent, incident = A.RCA.id, _incident(ctx)
    metrics = ctx.tool(agent, "metrics.read", minutes=45).output
    errors = ctx.tool(agent, "logs.search", query="ERROR", limit=80).output
    history = ctx.tool(agent, "deploy.read").output["history"]
    similar = ctx.tool(agent, "context.search", query="incident HTTP 500 after release configuration rollback",
                       max_tokens=900, doc_types=["incident", "guide"]).output
    detection = incident.data["detection"]
    signatures = rca_ops.error_signatures(errors)
    trace_files = signatures[0]["files"] if signatures else []
    suspects = rca_ops.rank_changes(history, detection["onset"], trace_files)
    ranked = rca_ops.hypotheses(metrics["points"], signatures, suspects, detection["onset"])
    if not suspects:
        raise StepBlocked("No recent production change correlates with the incident. Escalate to a human.")
    _set_incident(incident, "IDENTIFY CHANGE", suspects=suspects)
    analysis = ctx.llm(A.RCA, "rca", {
        "route": telemetry.RESET_ROUTE, "top_hypothesis": {**ranked[0], "signature": signatures[0]["signature"]},
        "suspect_change": suspects[0], "minutes_after_deploy": suspects[0]["minutes_before_onset"],
        "similar_incidents": _sources(similar)}, "Explain the leading hypothesis and propose prevention.")
    _set_incident(incident, "FORM HYPOTHESIS", hypotheses=ranked, analysis=analysis,
                  similar_incidents=similar["citations"])
    target = incident.data["previous_version"]
    request = ctx.tool(agent, "production.rollback", required=False)
    _set_incident(incident, "RECOMMEND REMEDIATION", recommendation={
        "action": f"Roll production back to {target}", "target_version": target,
        "why": "Rollback restores service in minutes and is low risk: the previous build ran healthy before the "
               "release. Fixing forward would need a new build, review and deployment while customers are affected.",
        "alternatives": [{"action": f"Fix forward: set {telemetry.BAD_SETTING} in the production manifest",
                          "trade_off": "Keeps the new release but needs a config change in production under pressure."}],
        "requires": "Approval by the on-call SRE", "agent_request": request.as_dict()})


def restore_service(ctx: RunContext) -> None:
    incident = _incident(ctx)
    approval = ctx.db.query(Approval).filter(Approval.run_id == ctx.run.id, Approval.kind == "rollback",
                                             Approval.status == "approved").order_by(Approval.id.desc()).first()
    result = ctx.tool("ci-pipeline", "production.rollback", approval_id=approval.id if approval else -1,
                      approved_by=approval.decided_by if approval else "").output
    incident.resolved_at = utcnow()
    incident.status = "mitigated"
    incident.mttr_minutes = round((incident.resolved_at - incident.started_at).total_seconds() / 60, 1)
    _set_incident(incident, "RESTORE SERVICE", restored={
        "version": result["version"], "approved_by": approval.decided_by, "executed_by": "ci-pipeline",
        "health": deploy_ops.health(ctx.db, "PRODUCTION")})


def rca_document(ctx: RunContext) -> None:
    agent, incident = A.RCA.id, _incident(ctx)
    data = incident.data
    analysis, suspect, top = data["analysis"], data["suspects"][0], data["hypotheses"][0]
    document = "\n".join([
        f"# {incident.key} - {incident.title}", "",
        f"- **Severity** {incident.severity}",
        f"- **Time to restore** {incident.mttr_minutes} minutes (simulated incident)",
        f"- **Symptom** {analysis['symptom']}",
        f"- **Root cause** {analysis['root_cause']}",
        f"- **Trigger** Release {suspect['version']} ({', '.join(suspect['changed_files'])})",
        f"- **Leading hypothesis confidence** {round(100 * top['confidence'])}%",
        f"- **Fix** Rolled back to {data['restored']['version']}, approved by {data['restored']['approved_by']}.",
        "", "## Why it was not caught", *[f"- {item}" for item in analysis["why_it_was_not_caught"]],
        "", "## Prevention", *[f"- {item}" for item in analysis["prevention"]],
        "", "## Lesson", "Restore service first, find root cause second, automate prevention third. "
                          "A setting without a safe default must be validated at start-up (ARCH-3, DEP-4).",
    ])
    path = f"incidents/{incident.key}.md"
    indexed = ctx.tool(agent, "context.write", path=path, text=document, doc_type="incident").output
    incident.status = "closed"
    _set_incident(incident, "DOCUMENT RCA", rca_document=document, context_path=path, indexed=indexed,
                  proposed_fixture={"id": "CFG-STARTUP-VALIDATION", "category": "code_correctness",
                                    "requirement": "Required settings are validated at start-up (ARCH-3).",
                                    "question": "Does the service fail its health check when a required setting is missing?"})


# --- 15. continuous improvement -----------------------------------------------------------------
def continuous_improvement(ctx: RunContext) -> None:
    agent = A.GOVERNANCE.id
    ctx.tool(agent, "audit.read", limit=200)
    runs = ctx.db.query(AgentRun).filter(AgentRun.run_id == ctx.run.id).all()
    calls = ctx.db.query(ToolCall).filter(ToolCall.run_id == ctx.run.id).all()
    approvals = ctx.db.query(Approval).filter(Approval.run_id == ctx.run.id, Approval.status == "approved").count()
    stats = {"agent_runs": len(runs), "tool_calls": len(calls),
             "blocked": sum(c.decision in ("DENY", "BLOCKED_KILL_SWITCH") for c in calls),
             "approval_requests": sum(c.decision == "REQUIRE_APPROVAL" for c in calls),
             "approvals": approvals, "cost_usd": round(sum(r.cost_usd for r in runs), 4),
             "tokens": sum(r.tokens_in + r.tokens_out for r in runs)}
    summary = ctx.llm(A.GOVERNANCE, "governance_summary", stats, "Summarise this run for the governance board.")
    ctx.save("improvement", {"stats": stats, "summary": summary,
                             "feedback_loop": ["RCA document added to the context index for future retrieval",
                                               "Regression fixture proposed for the evaluation suite",
                                               "Prevention items filed against ARCH-3 and DEP-4"]})


# --- the journey --------------------------------------------------------------------------------
STEPS: list[Step] = [
    Step("requirement_analysis", "AI requirement analysis", "ai", "REQUIREMENT_ANALYZED", "/requirements",
         "The Requirement Agent turns the business request into a user story, acceptance criteria, security "
         "requirements and open questions, grounded in the context repository.",
         agent=A.REQUIREMENT.id, handler=requirement_analysis, learn="requirements",
         plan=[(A.REQUIREMENT.id, "context.search", {"query": "<business request + policy terms>"})]),
    Step("requirement_approval", "Human approves the requirement", "approval", "REQUIREMENT_APPROVED", "/requirements",
         "A product owner or engineer confirms that the analysis says what the business actually wants.",
         approval={"kind": "requirement", "role": "engineer", "permission": "approve.requirement",
                   "title": "Approve requirement analysis"}, rework_to="requirement_analysis", learn="requirements"),
    Step("context_retrieval", "Context retrieval (RAG)", "ai", "CONTEXT_RETRIEVED", "/context",
         "The Context Agent retrieves, ranks, compresses and budgets the documents and code later agents will see.",
         agent=A.CONTEXT.id, handler=context_retrieval, learn="context",
         plan=[(A.CONTEXT.id, "context.search", {"query": "<requirement + acceptance criteria>", "max_tokens": 4000})]),
    Step("architecture_design", "AI architecture proposal", "ai", "ARCHITECTURE_GENERATED", "/architecture",
         "The Architecture Agent proposes three options with trade-offs and recommends one.",
         agent=A.ARCHITECTURE.id, handler=architecture_design, learn="architecture",
         plan=[(A.ARCHITECTURE.id, "repo.read", {}), (A.ARCHITECTURE.id, "repo.read", {"path": "app/db.py"})]),
    Step("architecture_approval", "Human architect approves", "approval", "ARCHITECTURE_APPROVED", "/architecture",
         "A human architect chooses the option. The AI recommendation is input, not a decision.",
         approval={"kind": "architecture", "role": "architect", "permission": "approve.architecture",
                   "title": "Choose and approve an architecture option"}, rework_to="architecture_design",
         learn="architecture"),
    Step("code_generation", "AI proposes code on a feature branch", "ai", "CODE_GENERATED", "/code",
         "The Coding Agent creates a feature branch and commits the implementation. It cannot write to main.",
         agent=A.CODE.id, handler=code_generation, learn="code",
         plan=[(A.CODE.id, "repo.read", {}), (A.CODE.id, "repo.search", {"query": "get_db"}),
               (A.CODE.id, "context.search", {"query": "coding standards"}),
               (A.CODE.id, "branch.create", {"name": "feature/<slug>"}),
               (A.CODE.id, "branch.write", {"branch": "feature/<slug>",
                                            "files": {"app/password_reset.py": "", "app/notifications.py": "",
                                                      "app/db.py": "", "app/config.py": "", "app/main.py": ""},
                                            "message": "Add feature"})]),
    Step("test_generation", "AI generates and runs tests", "ai", "TESTS_EXECUTED", "/tests",
         "The Test Agent writes unit, API, integration, negative and security tests and runs them in the sandbox.",
         agent=A.TEST.id, handler=test_generation, learn="tests",
         plan=[(A.TEST.id, "test.run", {"ref": "main"}),
               (A.TEST.id, "branch.write", {"branch": "feature/<slug>", "files": {"tests/test_password_reset.py": ""},
                                            "message": "Add tests"}),
               (A.TEST.id, "test.run", {"ref": "feature/<slug>"})]),
    Step("ai_review", "AI code review", "ai", "REVIEW_COMPLETED", "/review",
         "The Review Agent runs static rules and adds model judgement. It comments; it never approves.",
         agent=A.REVIEW.id, handler=ai_review, learn="review",
         plan=[(A.REVIEW.id, "pr.read", {"branch": "feature/<slug>"}),
               (A.REVIEW.id, "context.search", {"query": "coding standards"})]),
    Step("security_review", "Security review and capability audit", "ai", "SECURITY_REVIEWED", "/security",
         "The Security Agent scans the change and audits what every agent can actually reach. "
         "A critical finding blocks the workflow.",
         agent=A.SECURITY.id, handler=security_review, learn="security",
         plan=[(A.SECURITY.id, "security.scan", {"ref": "feature/<slug>"}), (A.SECURITY.id, "audit.read", {})]),
    Step("evaluation", "AI evaluation", "ai", "EVALUATED", "/evaluation",
         "The Evaluation Agent scores the AI output against fixtures. The score must be above 80%.",
         agent=A.EVALUATION.id, handler=evaluation, learn="evaluation",
         plan=[(A.EVALUATION.id, "eval.run", {"suite": "password-reset"})]),
    Step("pr_creation", "AI opens a pull request", "ai", "PR_OPENED", "/pull-requests",
         "The Coding Agent drafts the pull request description; the Review Agent posts its findings as a comment.",
         agent=A.CODE.id, handler=pr_creation, learn="pull_request",
         plan=[(A.CODE.id, "pr.create", {"branch": "feature/<slug>"}), (A.REVIEW.id, "pr.comment", {}),
               (A.CODE.id, "main.merge", {})]),
    Step("ci_pipeline", "CI pipeline", "system", "CI_PASSED", "/cicd",
         "The pipeline runs lint, tests, AI evaluation, security and build, and enforces the quality gates.",
         agent="ci-pipeline", handler=ci_pipeline, learn="cicd",
         plan=[("ci-pipeline", "repo.read", {}), ("ci-pipeline", "test.run", {"ref": "feature/<slug>"})]),
    Step("pr_approval", "Human reviews the pull request", "approval", "PR_APPROVED", "/pull-requests",
         "A human engineer reads the diff, the AI review and the evidence, then approves, requests changes or rejects.",
         approval={"kind": "pr", "role": "engineer", "permission": "approve.pr", "title": "Review pull request"},
         rework_to="code_generation", learn="pull_request"),
    Step("merge", "Human merges", "human_action", "MERGED", "/pull-requests",
         "A human clicks MERGE. No AI identity can perform this action.",
         handler=merge, permission="main.merge", learn="pull_request"),
    Step("staging_deploy", "Staging deployment (simulated)", "system", "STAGING_DEPLOYED", "/deployment",
         "The pipeline promotes the build through DEV, TEST and STAGING. The Deployment Advisor recommends go or no-go.",
         agent="ci-pipeline", handler=staging_deploy, learn="deployment",
         plan=[("ci-pipeline", "deploy.staging", {"env": "STAGING", "version": "<version>"}),
               (A.DEPLOYMENT.id, "production.deploy", {"version": "<version>"})]),
    Step("production_approval", "Human approves production", "approval", "PRODUCTION_APPROVED", "/deployment",
         "A Release Manager decides whether the release goes to production.",
         approval={"kind": "production", "role": "release_manager", "permission": "approve.production",
                   "title": "Approve production deployment", "action": "production.deploy"}, learn="deployment"),
    Step("production_deploy", "Production deployment (simulation)", "system", "PRODUCTION_DEPLOYED", "/deployment",
         "The pipeline identity deploys to the production simulation using the human approval.",
         agent="ci-pipeline", handler=production_deploy, learn="deployment",
         plan=[("ci-pipeline", "production.deploy", {"version": "<version>"})]),
    Step("monitoring", "Monitor the release", "ai", "MONITORING", "/observability",
         "Metrics for the new release are checked against their normal range.",
         agent=A.INCIDENT.id, handler=monitoring, learn="observability",
         plan=[(A.INCIDENT.id, "metrics.read", {"minutes": 15})]),
    Step("incident_simulation", "Simulate an incident", "human_action", "INCIDENT_DETECTED", "/incident",
         "A human starts a drill: a follow-up release with a configuration mistake reaches production.",
         handler=simulate_incident, permission="incident.simulate", learn="incident"),
    Step("incident_triage", "AI triage and evidence collection", "ai", "EVIDENCE_COLLECTED", "/incident",
         "The Incident Agent measures impact, sets severity and collects logs, metrics and recent changes.",
         agent=A.INCIDENT.id, handler=incident_triage, learn="incident",
         plan=[(A.INCIDENT.id, "metrics.read", {}), (A.INCIDENT.id, "logs.search", {"query": "ERROR"}),
               (A.INCIDENT.id, "deploy.read", {})]),
    Step("rca_analysis", "AI root-cause analysis", "ai", "REMEDIATION_RECOMMENDED", "/incident",
         "The RCA Agent correlates errors with recent changes, ranks hypotheses and recommends a rollback.",
         agent=A.RCA.id, handler=rca_analysis, learn="incident",
         plan=[(A.RCA.id, "logs.search", {"query": "ERROR"}), (A.RCA.id, "deploy.read", {}),
               (A.RCA.id, "production.rollback", {})]),
    Step("rollback_approval", "Human approves the rollback", "approval", "ROLLBACK_APPROVED", "/incident",
         "The on-call SRE decides. The AI may recommend a rollback; it may not execute one.",
         approval={"kind": "rollback", "role": "sre", "permission": "approve.rollback",
                   "title": "Approve production rollback", "action": "production.rollback"}, learn="incident"),
    Step("restore_service", "Restore service", "system", "SERVICE_RESTORED", "/incident",
         "The pipeline rolls production back to the previous build using the SRE's approval.",
         agent="ci-pipeline", handler=restore_service, learn="incident",
         plan=[("ci-pipeline", "production.rollback", {})]),
    Step("rca_document", "AI documents the RCA", "ai", "RCA_DOCUMENTED", "/incident",
         "The RCA Agent writes the post-incident document and adds it to the context index.",
         agent=A.RCA.id, handler=rca_document, learn="incident",
         plan=[(A.RCA.id, "context.write", {"path": "incidents/<key>.md"})]),
    Step("continuous_improvement", "Continuous improvement", "ai", "COMPLETED", "/productivity",
         "The Governance Agent summarises usage, cost, approvals and blocked actions, and feeds lessons back.",
         agent=A.GOVERNANCE.id, handler=continuous_improvement, learn="governance",
         plan=[(A.GOVERNANCE.id, "audit.read", {})]),
]
STEP_INDEX = {step.key: index for index, step in enumerate(STEPS)}
