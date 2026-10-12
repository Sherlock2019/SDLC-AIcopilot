"""Command line entry points used by CI (.github/workflows/ai-sdlc-ci.yml).

    python -m app.cli evaluate --min-score 80
    python -m app.cli security-scan
    python -m app.cli audit-capabilities
    python -m app.cli red-team
"""
from __future__ import annotations

import argparse
import sys

from . import services
from .config import REPO_ROOT
from .core import capability, sast, secrets_scan
from .evals import harness
from .providers import mock_tasks


def evaluate(args) -> int:
    variant = next(v for v in harness.VARIANTS if v["id"] == args.variant)
    result = harness.score(harness.candidate_from_variant(variant["prompt_version"], variant["model"], variant["label"]))
    for row in result["results"]:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['id']:<28} {row['detail'][:90]}")
    print(f"\nAI evaluation score: {result['score']}%  security: {result['security_score']}%  "
          f"({result['passed']}/{result['total']} fixtures)  gate: > {args.min_score}%")
    return 0 if result["score"] > args.min_score else 1


def security_scan(args) -> int:
    findings = sast.scan_files(mock_tasks.code_files("v2", "mock-large"))
    leaked = []
    for path in sorted(REPO_ROOT.rglob("*")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if not path.is_file() or path.suffix not in {".py", ".yaml", ".yml", ".md", ".env", ".toml", ".json", ".txt"}:
            continue
        if any(part in relative for part in (".venv/", ".lab/", "node_modules/", "/data/", ".git/", "tests/", "frontend/dist")):
            continue
        text = path.read_text(errors="ignore")
        for finding in secrets_scan.scan_text(text, "source", relative):
            line = text.splitlines()[finding.line - 1]
            # Demo fixtures are marked FAKE; a deliberate non-secret carries an explicit allow marker.
            if "FAKE" not in line.upper() and "allow-secret" not in line:
                leaked.append(finding)
    for finding in findings:
        print(f"{finding.severity:<9}{finding.file}:{finding.line}  {finding.title}")
    for finding in leaked:
        print(f"SECRET   {finding.source}:{finding.line}  {finding.label}")
    critical = [f for f in findings if f.severity == "CRITICAL"]
    print(f"\n{len(findings)} static finding(s), {len(critical)} critical, {len(leaked)} unmarked secret(s)")
    return 1 if critical or leaked else 0


def audit_capabilities(args) -> int:
    store, failed = services.get_store(), False
    for report in capability.audit_all(store):
        print(f"{report['summary']['status']:<9}{report['agent']}")
        for finding in report["findings"]:
            print(f"   {finding['severity']}: {' -> '.join(finding['path'])}")
            failed = failed or finding["severity"] == "CRITICAL"
    return 1 if failed else 0


def red_team(args) -> int:
    from . import redteam
    from .db import SessionLocal, init_db
    from .seed import load_scenario, seed

    init_db()
    with SessionLocal() as db:
        seed(db)
        load_scenario(db, "recommended", "ci")
        report = redteam.run_all(db)
    for result in report["results"]:
        print(f"{result['outcome']:<11}{result['name']}")
    print(f"\n{report['passed']}/{report['total']} scenarios blocked")
    return 0 if report["passed"] == report["total"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--min-score", type=float, default=80)
    evaluation.add_argument("--variant", default="v2-large")
    evaluation.set_defaults(fn=evaluate)
    commands.add_parser("security-scan").set_defaults(fn=security_scan)
    commands.add_parser("audit-capabilities").set_defaults(fn=audit_capabilities)
    commands.add_parser("red-team").set_defaults(fn=red_team)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
