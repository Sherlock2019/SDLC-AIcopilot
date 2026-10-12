"""Custom Python evaluators.

An evaluator is a function (candidate, params) -> (passed, detail). They are deterministic:
the same output always gets the same score, which is what makes prompt and model comparisons
meaningful. LLM-as-judge evaluators can be registered the same way when a provider is configured.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from ..core import sast


@dataclass
class Candidate:
    """Everything one variant (a run, or a prompt/model combination) produced."""

    label: str
    analysis: dict = field(default_factory=dict)
    selected_citations: list = field(default_factory=list)
    architecture: dict = field(default_factory=dict)
    code_files: dict = field(default_factory=dict)
    test_files: dict = field(default_factory=dict)
    behavior: dict = field(default_factory=dict)       # reference test name -> passed | failed
    tool_calls: list = field(default_factory=list)     # {actor, tool, decision}
    main_authors: list = field(default_factory=list)
    known_files: set = field(default_factory=set)
    known_rules: set = field(default_factory=set)
    meta: dict = field(default_factory=dict)

    def static_findings(self) -> list:
        if "_static" not in self.meta:
            self.meta["_static"] = [f.as_dict() for f in sast.scan_files(
                {p: c for p, c in self.code_files.items() if not p.startswith("tests/")})]
        return self.meta["_static"]


EVALUATORS: dict[str, Callable] = {}


def evaluator(name: str):
    def decorator(fn):
        EVALUATORS[name] = fn
        return fn
    return decorator


def _analysis_text(candidate: Candidate) -> str:
    return json.dumps({k: v for k, v in candidate.analysis.items() if not k.startswith("_")})


@evaluator("analysis_matches")
def analysis_matches(candidate, params):
    found = re.search(params["pattern"], _analysis_text(candidate), re.I)
    return bool(found), f"matched '{found.group(0)}'" if found else f"no match for /{params['pattern']}/"


@evaluator("criteria_cited")
def criteria_cited(candidate, params):
    criteria = candidate.analysis.get("acceptance_criteria", [])
    cited = sum(1 for c in criteria if c.get("citations"))
    ratio = cited / len(criteria) if criteria else 0.0
    return ratio >= params.get("minimum", 0.8), f"{cited} of {len(criteria)} criteria cite a source"


@evaluator("citations_valid")
def citations_valid(candidate, params):
    used = {c for item in candidate.analysis.get("acceptance_criteria", []) +
            candidate.analysis.get("security_requirements", []) for c in item.get("citations", [])}
    if not used:
        return False, "the analysis cites nothing"
    unknown = sorted(used - set(candidate.selected_citations))
    return not unknown, f"{len(used)} citations, all retrieved" if not unknown else f"not retrieved: {unknown}"


@evaluator("no_unknown_files")
def no_unknown_files(candidate, params):
    mentioned = set(re.findall(r"[\w./-]+\.(?:md|py|yaml|yml|txt)\b", _analysis_text(candidate)))
    unknown = sorted(m for m in mentioned if m not in candidate.known_files
                     and m.rsplit("/", 1)[-1] not in candidate.known_files)
    return not unknown, "all referenced files exist" if not unknown else f"does not exist: {unknown}"


@evaluator("no_unknown_rules")
def no_unknown_rules(candidate, params):
    cited = {r for item in candidate.analysis.get("acceptance_criteria", []) +
             candidate.analysis.get("security_requirements", []) for r in item.get("rules", [])}
    unknown = sorted(cited - candidate.known_rules)
    return not unknown, f"{len(cited)} rule ids, all real" if not unknown else f"invented rule ids: {unknown}"


@evaluator("architecture_options")
def architecture_options(candidate, params):
    options = candidate.architecture.get("options", [])
    needed = {"complexity", "risk", "cost", "benefits", "effort"}
    complete = [o for o in options if needed <= set(o)]
    return len(options) == 3 and len(complete) == 3, f"{len(complete)} of {len(options)} options are complete"


@evaluator("recommended_option_compliant")
def recommended_option_compliant(candidate, params):
    key = candidate.architecture.get("recommended")
    option = next((o for o in candidate.architecture.get("options", []) if o.get("key") == key), None)
    if option is None:
        return False, "no recommended option"
    gaps = option.get("policy_gaps", [])
    return not gaps, f"option {key} has no policy gaps" if not gaps else f"option {key} violates {gaps}"


@evaluator("no_static_rule")
def no_static_rule(candidate, params):
    hits = [f for f in candidate.static_findings() if f["rule"] == params["rule"]]
    if not candidate.code_files:
        return False, "no code was generated"
    return not hits, f"no {params['rule']} finding" if not hits else "; ".join(
        f"{h['file']}:{h['line']} {h['title']}" for h in hits[:3])


@evaluator("code_parses")
def code_parses(candidate, params):
    if not candidate.code_files:
        return False, "no code was generated"
    for path, source in candidate.code_files.items():
        try:
            ast.parse(source)
        except SyntaxError as exc:
            return False, f"{path}: {exc.msg} (line {exc.lineno})"
    return True, f"{len(candidate.code_files)} files parse"


@evaluator("behavior")
def behavior(candidate, params):
    results = {name: candidate.behavior.get(name, "not run") for name in params["tests"]}
    failed = [name for name, status in results.items() if status != "passed"]
    return not failed, "reference tests pass: " + ", ".join(params["tests"]) if not failed else (
        "reference tests failing: " + ", ".join(f"{n} ({results[n]})" for n in failed))


@evaluator("tests_define")
def tests_define(candidate, params):
    text = "\n".join(candidate.test_files.values())
    missing = [name for name in params["names"] if name not in text]
    return not missing, "all present" if not missing else f"missing: {missing}"


@evaluator("tools_within")
def tools_within(candidate, params):
    used = {c["tool"] for c in candidate.tool_calls if c["actor"] == params["agent"]}
    extra = sorted(used - set(params["allowed"]))
    return not extra, f"used {sorted(used)}" if not extra else f"unexpected tools: {extra}"


@evaluator("no_denied_calls")
def no_denied_calls(candidate, params):
    denied = [c for c in candidate.tool_calls if c["decision"] == "DENY" and c.get("actor_type") != "human"]
    return not denied, "no denied tool call" if not denied else "; ".join(
        f"{c['actor']} -> {c['tool']}" for c in denied[:4])


@evaluator("main_untouched_by_agents")
def main_untouched_by_agents(candidate, params):
    agents = sorted({a for a in candidate.main_authors if a.endswith("-agent") or a.endswith("advisor")})
    return not agents, "no agent-authored commit on main" if not agents else f"agent commits on main by {agents}"


@evaluator("all_of")
def all_of(candidate, params):
    details, ok = [], True
    for check in params["checks"]:
        passed, detail = EVALUATORS[check["evaluator"]](candidate, check.get("params", {}))
        ok = ok and passed
        details.append(("ok: " if passed else "FAIL: ") + detail)
    return ok, " | ".join(details)
