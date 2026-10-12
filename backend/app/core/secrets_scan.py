"""Secret detection and redaction.

Used on five surfaces: source code, logs, prompts, tool results and environment variables.
Every credential in this repository is fake and carries a FAKE marker.
"""
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass

RULES = [
    ("aws-access-key", "AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", "GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("private-key", "Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("slack-token", "Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer-token", "Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.=]{24,}\b")),
    ("connection-string", "Database URL with password", re.compile(r"\b[a-z][a-z0-9+]*://[^\s:/@]+:[^\s:/@]{4,}@[^\s/]+")),
    # NAME = "value" in code or config (any case), value must be quoted.
    ("credential-assignment", "Hard-coded credential", re.compile(
        r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_?KEY|ACCESS_?KEY|TOKEN)[A-Z0-9_]*)\b[\"']?\s*[:=]\s*[\"']([^\s\"']{8,})[\"']")),
    # NAME=value as found in .env files, shell history and log lines (upper-case names only).
    ("env-credential", "Credential in environment or log line", re.compile(
        r"\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_?KEY|ACCESS_?KEY|TOKEN)[A-Z0-9_]*)=([^\s\"',;]{8,})")),
]
_ASSIGNMENT_RULES = {"credential-assignment", "env-credential"}

# Values that look like assignments but are obviously not credentials: references, placeholders,
# and plain lower-case phrases such as the passwords used by test fixtures.
_BENIGN = re.compile(
    r"(?i)^(os\.environ|settings\.|config\.|none$|null$|true$|false$|<|\{|\$\{|example|changeme|your[_-]|\[redacted)"
    r"|(?-i:^[a-z]+(?:-(?:[a-z]+|\d+))+$)|\(")


@dataclass
class SecretFinding:
    rule: str
    label: str
    surface: str
    source: str
    line: int
    preview: str
    entropy: float

    def as_dict(self) -> dict:
        return asdict(self)


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    return round(-sum(c / len(value) * math.log2(c / len(value)) for c in counts.values()), 2)


def _mask(value: str) -> str:
    return value[:4] + "*" * max(4, len(value) - 4) if len(value) > 4 else "****"


def scan_text(text: str, surface: str = "source", source: str = "") -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for number, line in enumerate((text or "").splitlines(), start=1):
        seen_spans: list[tuple[int, int]] = []
        for rule, label, pattern in RULES:
            for match in pattern.finditer(line):
                assignment = rule in _ASSIGNMENT_RULES
                value = match.group(2) if assignment else match.group(0)
                if assignment and _BENIGN.search(value):
                    continue
                span = match.span(2) if assignment else match.span(0)
                if any(a <= span[0] < b for a, b in seen_spans):
                    continue
                seen_spans.append(span)
                findings.append(
                    SecretFinding(rule, label, surface, source, number, _mask(value), shannon_entropy(value))
                )
    return findings


def redact(text: str) -> tuple[str, int]:
    """Replace every detected secret with a placeholder. Returns (clean_text, count)."""
    count = 0

    def _sub_whole(match: re.Match) -> str:
        nonlocal count
        count += 1
        return "[REDACTED]"

    def _sub_assignment(match: re.Match) -> str:
        nonlocal count
        value = match.group(2)
        if _BENIGN.search(value):
            return match.group(0)
        count += 1
        return match.group(0).replace(value, "[REDACTED]")

    for rule, _, pattern in RULES:
        text = pattern.sub(_sub_assignment if rule in _ASSIGNMENT_RULES else _sub_whole, text)
    return text, count


def scan_env(env: dict[str, str], source: str = "process environment") -> list[SecretFinding]:
    text = "\n".join(f"{key}={value}" for key, value in env.items())
    return scan_text(text, surface="environment", source=source)
