"""Bridges to external evaluation frameworks. Neither framework is required to run the lab.

The suite YAML is the single source of truth. These adapters translate it so teams that already
use Promptfoo or DeepEval can reuse the same fixtures. Status: export scaffolds. The lab's own
harness (harness.py) is what tests and CI run; these adapters are not exercised in CI.
"""
from __future__ import annotations

import json
from typing import Protocol

from ..agents import definitions as agents
from .evaluators import EVALUATORS, Candidate
from .harness import load_suite


class EvaluationBackend(Protocol):
    """Anything that can turn a suite and a candidate into per-case verdicts."""

    def run(self, suite: dict, candidate: Candidate) -> list[dict]: ...


def to_promptfoo_config(suite_name: str = "password-reset") -> dict:
    """A promptfooconfig.yaml equivalent. Each case becomes a test whose Python assertion calls
    `promptfoo_assert` below. Add your own provider id under `providers` before running it."""
    suite = load_suite(suite_name)
    return {
        "description": f"AI-SDLC Champion Lab - {suite['suite']}",
        "prompts": [{"id": f"coding-agent-{version}", "raw": agents.CODE.system_prompt(version)}
                    for version in ("v1", "v2")],
        "providers": [],
        "tests": [{
            "description": f"{case['id']}: {case['question']}",
            "vars": {"requirement": case["requirement"], "case_id": case["id"], "suite": suite_name},
            "assert": [{"type": "python", "value": "file://backend/app/evals/adapters.py:promptfoo_assert",
                        "weight": case["weight"]}],
            "metadata": {"category": case["category"], "expected": case["expected"]},
        } for case in suite["cases"]],
    }


def promptfoo_assert(output: str, context: dict) -> dict:
    """Promptfoo Python assertion. Expects the model output to be the JSON `files` object."""
    variables = context.get("vars", {})
    case = next(c for c in load_suite(variables.get("suite", "password-reset"))["cases"]
                if c["id"] == variables["case_id"])
    try:
        files = json.loads(output).get("files", {})
    except ValueError:
        return {"pass": False, "score": 0, "reason": "Output is not JSON."}
    passed, detail = EVALUATORS[case["evaluator"]](Candidate(label="promptfoo", code_files=files), case["params"])
    return {"pass": passed, "score": 1 if passed else 0, "reason": detail}


class DeepEvalAdapter:
    """Builds DeepEval test cases lazily; importing this module never imports deepeval."""

    def test_cases(self, suite_name: str, candidate: Candidate) -> list:
        try:
            from deepeval.test_case import LLMTestCase
        except ImportError:
            raise RuntimeError("DeepEval is optional. Install it with: pip install deepeval") from None
        suite = load_suite(suite_name)
        output = "\n\n".join(f"# {path}\n{content}" for path, content in candidate.code_files.items())
        return [LLMTestCase(input=case["requirement"], actual_output=output, expected_output=case["expected"],
                            additional_metadata={"case_id": case["id"], "category": case["category"]})
                for case in suite["cases"]]
