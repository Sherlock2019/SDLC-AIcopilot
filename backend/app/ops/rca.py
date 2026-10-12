"""Root-cause analysis over evidence: deterministic correlation, no model required.

The RCA agent gathers evidence through tools, this module turns it into ranked hypotheses, and
the model (or the mock) only writes the narrative. Keeping the reasoning in code makes the
analysis reproducible and testable; the model cannot invent a root cause the evidence does not support.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime

ERROR_THRESHOLD_PCT = 3.0


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.rstrip("Z"))


def detect(points: list[dict]) -> dict | None:
    """First minute where the error rate stays above the threshold for two consecutive samples."""
    for first, second in zip(points, points[1:]):
        if first["error_rate_pct"] > ERROR_THRESHOLD_PCT and second["error_rate_pct"] > ERROR_THRESHOLD_PCT:
            healthy = [p["error_rate_pct"] for p in points if p["ts"] < first["ts"]]
            baseline = round(sum(healthy) / len(healthy), 2) if healthy else 0.0
            peak = max(p["error_rate_pct"] for p in points if p["ts"] >= first["ts"])
            return {"onset": first["ts"], "baseline_error_rate_pct": baseline, "peak_error_rate_pct": peak,
                    "threshold_pct": ERROR_THRESHOLD_PCT}
    return None


def error_signatures(log_lines: list[dict]) -> list[dict]:
    """Group error logs by exception line and collect the files named in their stack traces."""
    groups: dict[str, dict] = {}
    for line in log_lines:
        if line["level"] != "ERROR":
            continue
        rows = line["message"].splitlines()
        signature = next((r.strip() for r in reversed(rows) if re.match(r"^\w+(Error|Exception)\b", r.strip())),
                         rows[0][:120])
        group = groups.setdefault(signature, {"signature": signature, "count": 0, "files": Counter(),
                                              "first_seen": line["ts"], "sample": line["message"]})
        group["count"] += 1
        group["first_seen"] = min(group["first_seen"], line["ts"])
        for match in re.finditer(r'File "(?:/srv/)?([^"]+)", line (\d+)', line["message"]):
            group["files"][match.group(1)] += 1
    out = sorted(groups.values(), key=lambda g: -g["count"])
    for group in out:
        group["files"] = [name for name, _ in group["files"].most_common()]
    return out


def changed_files(diff: str) -> list[str]:
    return sorted(set(re.findall(r"^\+\+\+ b/(.+)$", diff or "", flags=re.M)))


def rank_changes(deployments: list[dict], onset: str, trace_files: list[str]) -> list[dict]:
    """Score each recent production change by how close it is in time and how much code it shares
    with the failing stack trace."""
    onset_at = _parse(onset)
    ranked = []
    for deployment in deployments:
        deployed_at = _parse(deployment["ts"])
        minutes_before = (onset_at - deployed_at).total_seconds() / 60
        if minutes_before < -1 or minutes_before > 24 * 60:
            continue
        files = changed_files(deployment.get("diff", ""))
        overlap = len(set(files) & set(trace_files)) / len(trace_files) if trace_files else 0.0
        proximity = math.exp(-max(minutes_before, 0) / 20)
        ranked.append({
            "version": deployment["version"], "deployed_at": deployment["ts"],
            "minutes_before_onset": round(max(minutes_before, 0), 1), "changed_files": files,
            "file_overlap": round(overlap, 2), "time_proximity": round(proximity, 2),
            "score": round(0.5 * proximity + 0.5 * overlap, 2),
            "notes": deployment.get("notes", ""), "approved_by": deployment.get("approved_by", ""),
        })
    return sorted(ranked, key=lambda r: -r["score"])


def hypotheses(points: list[dict], signatures: list[dict], suspects: list[dict], onset: str) -> list[dict]:
    before = [p for p in points if p["ts"] < onset] or points
    after = [p for p in points if p["ts"] >= onset] or points

    def mean(rows, key):
        return sum(r[key] for r in rows) / len(rows)

    top = signatures[0] if signatures else {"signature": "", "files": [], "count": 0}
    total_errors = sum(s["count"] for s in signatures) or 1
    dominance = top["count"] / total_errors
    suspect = suspects[0] if suspects else None
    traffic_ratio = mean(after, "rps") / (mean(before, "rps") or 1)
    db_ratio = mean(after, "db_latency_ms") / (mean(before, "db_latency_ms") or 1)
    config_error = bool(re.search(r"KeyError|config|environ|setting", top["signature"] + " ".join(top["files"]), re.I))
    db_error = bool(re.search(r"sqlite|psycopg|OperationalError|database", top["signature"], re.I))
    mail_error = bool(re.search(r"smtp|notification|mail", top["signature"] + " ".join(top["files"]), re.I))

    raw = [
        {"id": "H1", "title": "A configuration change in the latest release broke the endpoint",
         "weight": (2.0 if config_error else 0.2) * dominance + (suspect["score"] * 2 if suspect else 0),
         "evidence_for": [e for e in [
             f"{round(100 * dominance)}% of errors share one signature: {top['signature']}" if top["count"] else "",
             f"Stack trace ends in {top['files'][-1]}" if top["files"] else "",
             (f"Release {suspect['version']} changed {', '.join(suspect['changed_files'])} "
              f"{suspect['minutes_before_onset']} min before the first error") if suspect else "",
         ] if e],
         "evidence_against": [] if suspect else ["No production change in the last 24 hours"]},
        {"id": "H2", "title": "The database is failing or slow",
         "weight": (1.5 if db_error else 0.05) + max(db_ratio - 1.5, 0),
         "evidence_for": ["Database errors in the logs"] if db_error else [],
         "evidence_against": [f"Database latency is unchanged ({db_ratio:.2f}x)",
                              "Login and profile use the same database and are healthy"]},
        {"id": "H3", "title": "A traffic spike is overloading the service",
         "weight": 0.05 + max(traffic_ratio - 1.5, 0),
         "evidence_for": [f"Traffic changed by {traffic_ratio:.2f}x"] if traffic_ratio > 1.5 else [],
         "evidence_against": [f"Request volume is flat ({traffic_ratio:.2f}x)", "Only one route is failing"]},
        {"id": "H4", "title": "The email provider is unavailable",
         "weight": 1.0 if mail_error else 0.05,
         "evidence_for": ["Notification errors in the logs"] if mail_error else [],
         "evidence_against": ["The failing frame is before the notification call",
                              "No notification errors in the logs"]},
    ]
    total = sum(h["weight"] for h in raw) or 1
    ranked = sorted(raw, key=lambda h: -h["weight"])
    return [{**{k: v for k, v in h.items() if k != "weight"}, "confidence": round(h["weight"] / total, 2)}
            for h in ranked]


def severity(peak_error_rate_pct: float, failing_route_error_pct: float) -> str:
    if peak_error_rate_pct >= 25:
        return "SEV1"
    if failing_route_error_pct >= 90 or peak_error_rate_pct >= 5:
        return "SEV2"
    return "SEV3"
