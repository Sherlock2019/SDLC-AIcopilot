"""Sandboxed test execution.

Generated code is untrusted, so it never runs inside the lab's own process. Tests run in a
subprocess with a scrubbed environment (no API keys, no database URL, no tokens), a private
HOME, a wall-clock timeout, and a working copy exported from git.

Known limit, stated openly: this is process isolation, not a container. Network egress is not
blocked here. See policies/topology.yaml (`sandbox-process -> network.fetch`).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

TIMEOUT_SECONDS = 180
_CACHE: dict[str, dict] = {}

CATEGORIES = {"TestUnit": "unit", "TestApi": "api", "TestIntegration": "integration",
              "TestNegative": "negative", "TestSecurity": "security"}


def sandbox_env(workdir: Path, home: str) -> dict[str, str]:
    """The complete environment of the sandbox process. Nothing is inherited implicitly."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(workdir),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": home,
        "LANG": "C.UTF-8",
    }


def _category(classname: str) -> str:
    return CATEGORIES.get(classname.rsplit(".", 1)[-1], "api")


def run_command(workdir: Path, command: list[str], timeout: int = TIMEOUT_SECONDS) -> dict:
    with tempfile.TemporaryDirectory(prefix="lab-home-") as home:
        started = time.perf_counter()
        try:
            proc = subprocess.run(command, cwd=workdir, env=sandbox_env(workdir, home), capture_output=True,
                                  text=True, timeout=timeout)
            code, out = proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            code, out = 124, f"Timed out after {timeout}s"
        except FileNotFoundError as exc:
            code, out = 127, str(exc)
        return {"exit_code": code, "output": out[-6000:], "duration_s": round(time.perf_counter() - started, 2)}


def run_pytest(workdir: Path, cache_key: str = "", select: list[str] | None = None) -> dict:
    """Run pytest with coverage in the sandbox and return structured results."""
    if cache_key and cache_key in _CACHE:
        return _CACHE[cache_key]
    workdir = Path(workdir)
    with tempfile.TemporaryDirectory(prefix="lab-reports-") as reports:
        junit, cov = Path(reports) / "junit.xml", Path(reports) / "coverage.json"
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--cov=app",
                   f"--cov-report=json:{cov}", "--cov-report=", f"--junitxml={junit}", "-o", "junit_family=xunit1",
                   *(select or [])]
        raw = run_command(workdir, command)
        (workdir / ".coverage").unlink(missing_ok=True)
        tests, failures = [], []
        if junit.exists():
            for case in ET.parse(junit).getroot().iter("testcase"):
                problem = next((child for child in case if child.tag in {"failure", "error"}), None)
                skipped = any(child.tag == "skipped" for child in case)
                status = "failed" if problem is not None else ("skipped" if skipped else "passed")
                entry = {"name": case.get("name"), "classname": case.get("classname", ""),
                         "file": case.get("classname", "").split(".Test")[0].replace(".", "/") + ".py",
                         "category": _category(case.get("classname", "")), "status": status,
                         "time": float(case.get("time") or 0)}
                tests.append(entry)
                if problem is not None:
                    failures.append({"name": entry["name"], "category": entry["category"],
                                     "message": (problem.get("message") or "").strip()[:300]})
        coverage, files = None, []
        if cov.exists():
            report = json.loads(cov.read_text())
            coverage = round(report["totals"]["percent_covered"], 1)
            files = [{"path": path, "coverage": round(data["summary"]["percent_covered"], 1),
                      "missing": len(data["missing_lines"])} for path, data in sorted(report["files"].items())]
    by_category: dict[str, dict] = {}
    for test in tests:
        bucket = by_category.setdefault(test["category"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += test["status"] == "passed"
    result = {
        "ran": bool(tests), "exit_code": raw["exit_code"], "duration_s": raw["duration_s"],
        "total": len(tests), "passed": sum(t["status"] == "passed" for t in tests),
        "failed": sum(t["status"] == "failed" for t in tests), "coverage": coverage,
        "coverage_files": files, "tests": tests, "failures": failures, "by_category": by_category,
        "output_tail": raw["output"][-2500:], "sandbox": {"isolation": "subprocess", "env_keys": sorted(
            sandbox_env(workdir, "~")), "timeout_s": TIMEOUT_SECONDS},
    }
    if cache_key and result["ran"]:
        _CACHE[cache_key] = result
    return result


def run_ruff(workdir: Path) -> dict:
    # Exit code 1 means both "lint errors" and "module not found", so check availability first.
    if importlib.util.find_spec("ruff") is None:
        return {"available": False, "passed": False, "output": "ruff is not installed", "duration_s": 0}
    raw = run_command(Path(workdir), [sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache",
                                      "--select", "E,F,W", "--line-length", "120", "app", "tests"], timeout=60)
    available = raw["exit_code"] in (0, 1)
    return {"available": available, "passed": raw["exit_code"] == 0, "output": raw["output"][-1500:],
            "duration_s": raw["duration_s"]}
