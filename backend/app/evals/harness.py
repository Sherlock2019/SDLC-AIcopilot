"""Evaluation harness: fixtures in, measurable scores out.

Two entry points:
  evaluate_run(db, run)            score what the agents produced in a workflow run
  compare(variants)                score prompt v1 / v2 and model A / B side by side

"Behavior" evaluators do not trust the AI-written tests. They run an independent reference
test-suite against the generated code inside the sandbox.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from .. import services
from ..agents import definitions as agents
from ..config import settings
from ..core.tokens import cost_usd
from ..models import AgentRun, Evaluation, ToolCall
from ..providers import mock_tasks
from ..providers.mock import MockProvider
from ..tools import sandbox
from .evaluators import EVALUATORS, Candidate

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CATEGORY_LABELS = {
    "requirement_accuracy": "Requirement accuracy", "grounding": "Grounding", "hallucination": "Hallucination",
    "architecture_compliance": "Architecture compliance", "code_correctness": "Code correctness",
    "security": "Security", "test_quality": "Test quality", "tool_selection": "Tool selection",
    "policy_compliance": "Policy compliance",
}
VARIANTS = [
    {"id": "v1-large", "label": "Prompt v1 · Model A", "prompt_version": "v1", "model": "mock-large"},
    {"id": "v2-large", "label": "Prompt v2 · Model A", "prompt_version": "v2", "model": "mock-large"},
    {"id": "v1-small", "label": "Prompt v1 · Model B", "prompt_version": "v1", "model": "mock-small"},
    {"id": "v2-small", "label": "Prompt v2 · Model B", "prompt_version": "v2", "model": "mock-small"},
]
DEFAULT_REQUIREMENT = "Add a secure password-reset workflow to the customer portal."


@lru_cache(maxsize=8)
def load_suite(name: str = "password-reset") -> dict:
    suite = yaml.safe_load((FIXTURE_DIR / f"{name}.yaml").read_text())
    for case in suite["cases"]:
        case.setdefault("expected", "PASS")
        case.setdefault("weight", 1)
        case.setdefault("params", {})
        if case["evaluator"] not in EVALUATORS:
            raise ValueError(f"{case['id']}: unknown evaluator '{case['evaluator']}'")
    return suite


def corpus_knowledge() -> tuple[set, set]:
    index = services.get_index()
    text = "\n".join(d.text for d in index.documents)
    files = {d.path for d in index.documents} | {d.path.rsplit("/", 1)[-1] for d in index.documents}
    files |= set(re.findall(r"[\w./-]+\.(?:md|py|yaml|yml|txt)\b", text))
    return files, set(re.findall(r"\b[A-Z]{2,5}-\d+\b", text))


def behavior_results(code_files: dict[str, str]) -> dict[str, str]:
    """Run the reference tests against generated code in the sandbox. Cached by content hash."""
    if not code_files:
        return {}
    digest = hashlib.sha256("".join(f"{p}\0{c}" for p, c in sorted(code_files.items())).encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="lab-eval-") as directory:
        work = Path(directory) / "repo"
        shutil.copytree(settings.sample_app_dir, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.db"))
        for relative, content in {**code_files, **mock_tasks.test_files("v2", "mock-large")}.items():
            target = work / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        result = sandbox.run_pytest(work, cache_key=f"eval:{digest}")
    return {test["name"]: test["status"] for test in result["tests"]}


def score(candidate: Candidate, suite_name: str = "password-reset") -> dict:
    suite = load_suite(suite_name)
    results = []
    for case in suite["cases"]:
        try:
            passed, detail = EVALUATORS[case["evaluator"]](candidate, case["params"])
        except Exception as exc:  # an evaluator crash is a failed case, never a crashed harness
            passed, detail = False, f"evaluator error: {type(exc).__name__}: {exc}"
        actual = "PASS" if passed else "FAIL"
        results.append({
            "id": case["id"], "category": case["category"], "category_label": CATEGORY_LABELS[case["category"]],
            "requirement": case["requirement"], "question": case["question"], "evaluator": case["evaluator"],
            "expected": case["expected"], "actual": actual, "passed": actual == case["expected"],
            "detail": detail, "weight": case["weight"],
        })

    def pct(rows):
        total = sum(r["weight"] for r in rows)
        return round(100 * sum(r["weight"] for r in rows if r["passed"]) / total, 1) if total else 0.0

    by_category = [{"category": key, "label": label, "score": pct([r for r in results if r["category"] == key]),
                    "passed": sum(r["passed"] for r in results if r["category"] == key),
                    "total": sum(1 for r in results if r["category"] == key)}
                   for key, label in CATEGORY_LABELS.items()]
    overall = pct(results)
    return {
        "suite": suite["suite"], "variant": candidate.label, "threshold": suite["threshold"],
        "score": overall, "security_score": pct([r for r in results if r["category"] == "security"]),
        "accuracy": pct([r for r in results if r["category"] != "security"]),
        "passed": sum(r["passed"] for r in results), "total": len(results),
        "gate_passed": overall > suite["threshold"], "by_category": by_category, "results": results,
        "tokens": candidate.meta.get("tokens", 0), "cost_usd": candidate.meta.get("cost_usd", 0.0),
        "latency_ms": candidate.meta.get("latency_ms", 0),
    }


# --- candidates ---------------------------------------------------------------------------------
def candidate_from_run(db: Session, run) -> Candidate:
    artifacts = run.artifacts or {}
    git = services.workspace(run.id)
    branch = (artifacts.get("code") or {}).get("branch")
    files = git.read_all(branch) if branch and git.exists(branch) else {}
    known_files, known_rules = corpus_knowledge()
    requirement = artifacts.get("requirement_analysis") or {}
    code = {p: c for p, c in files.items() if not p.startswith("tests/")}
    calls = db.query(ToolCall).filter(ToolCall.run_id == run.id, ToolCall.tag == "").all()
    runs = db.query(AgentRun).filter(AgentRun.run_id == run.id).all()
    return Candidate(
        label=f"Run #{run.id} · prompt {run.prompt_version} · {run.model or 'default model'}",
        analysis=requirement.get("analysis", {}),
        selected_citations=[c["id"] for c in requirement.get("citations", [])],
        architecture=artifacts.get("architecture") or {},
        code_files=code, test_files={p: c for p, c in files.items() if p.startswith("tests/")},
        behavior=behavior_results(code),
        tool_calls=[{"actor": c.actor, "actor_type": c.actor_type, "tool": c.tool, "decision": c.decision}
                    for c in calls],
        main_authors=[entry["author"] for entry in git.log("main", 50, first_parent=True)],
        known_files=known_files | set(files), known_rules=known_rules,
        meta={"tokens": sum(r.tokens_in + r.tokens_out for r in runs),
              "cost_usd": round(sum(r.cost_usd for r in runs), 6), "latency_ms": sum(r.latency_ms for r in runs)},
    )


@lru_cache(maxsize=16)
def candidate_from_variant(prompt_version: str, model: str, label: str) -> Candidate:
    """Run the generation tasks for one prompt/model combination, outside any workflow run."""
    provider = MockProvider()
    sources = []
    if prompt_version != "v1":  # the v1 prompt is ungrounded: it gets no retrieved context at all
        retrieval = services.get_index().retrieve(DEFAULT_REQUIREMENT + " security policy acceptance criteria",
                                                  max_tokens=2500)
        sources = [{"citation": r["citation"], "source": r["source"], "text": r["text"]}
                   for r in retrieval["candidates"] if r["status"] == "selected"]
    outputs, tokens_in, tokens_out, latency = {}, 0, 0, 0
    for agent, task in ((agents.REQUIREMENT, "requirement_analysis"), (agents.ARCHITECTURE, "architecture"),
                        (agents.CODE, "code_generation"), (agents.TEST, "test_generation")):
        payload = {"requirement": DEFAULT_REQUIREMENT, "sources": sources}
        response = provider.complete(system=agent.system_prompt(prompt_version), prompt=str(payload), task=task,
                                     payload=payload, model=model, prompt_version=prompt_version)
        outputs[task] = mock_tasks.TASKS[task](payload, prompt_version, model)
        tokens_in, tokens_out, latency = (tokens_in + response.tokens_in, tokens_out + response.tokens_out,
                                          latency + response.latency_ms)
    known_files, known_rules = corpus_knowledge()
    code = outputs["code_generation"]["files"]
    expected_tools = ["repo.read", "repo.search", "context.search", "branch.create", "branch.write", "pr.create"]
    return Candidate(
        label=label, analysis=outputs["requirement_analysis"],
        selected_citations=[s["citation"] for s in sources], architecture=outputs["architecture"],
        code_files=code, test_files=outputs["test_generation"]["files"], behavior=behavior_results(code),
        tool_calls=[{"actor": "coding-agent", "actor_type": "agent", "tool": t, "decision": "ALLOW"}
                    for t in expected_tools],
        known_files=known_files | set(code), known_rules=known_rules,
        meta={"tokens": tokens_in + tokens_out, "cost_usd": cost_usd(model, tokens_in, tokens_out),
              "latency_ms": latency},
    )


# --- entry points -------------------------------------------------------------------------------
def evaluate_run(db: Session, run, suite: str = "password-reset") -> dict:
    started = time.perf_counter()
    result = score(candidate_from_run(db, run), suite)
    result["duration_s"] = round(time.perf_counter() - started, 1)
    db.add(Evaluation(run_id=run.id, suite=suite, variant=result["variant"], score=result["score"],
                      security_score=result["security_score"], accuracy=result["accuracy"],
                      latency_ms=result["latency_ms"], tokens=result["tokens"], cost_usd=result["cost_usd"],
                      results=result["results"]))
    return result


def compare(variant_ids: list[str] | None = None, suite: str = "password-reset") -> dict:
    chosen = [v for v in VARIANTS if not variant_ids or v["id"] in variant_ids]
    rows = []
    for variant in chosen:
        result = score(candidate_from_variant(variant["prompt_version"], variant["model"], variant["label"]), suite)
        rows.append({**variant, **{k: result[k] for k in (
            "score", "security_score", "accuracy", "passed", "total", "gate_passed", "tokens", "cost_usd",
            "latency_ms", "by_category")}, "failed_cases": [r for r in result["results"] if not r["passed"]]})
    return {"suite": suite, "threshold": load_suite(suite)["threshold"], "variants": rows,
            "note": "Model A = mock-large, Model B = mock-small. Scores are computed by running the evaluators "
                    "and the reference tests on each variant's real output; nothing in this table is hard-coded."}
