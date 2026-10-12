"""Prompt-injection detection for untrusted content.

Detection is a tripwire, not the defence. The defence is structural: retrieved documents and
tool results are data, they can never raise an agent's permissions, and every action still has
to pass the policy engine. This module exists so attempts are noticed, quarantined and audited.
"""
import re
from dataclasses import asdict, dataclass

PATTERNS = [
    ("override-instructions", "Tries to override prior instructions", 0.9,
     re.compile(r"(?i)\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|security)\b[^.\n]{0,30}\b(instructions?|rules?|polic(?:y|ies)|prompts?|guardrails?)")),
    ("role-impersonation", "Impersonates a system or developer message", 0.8,
     re.compile(r"(?i)\b(important\s+)?(system|developer|admin(?:istrator)?)\s+(message|prompt|override|notice)\b|\byou are now\b|\bnew instructions?\s*:")),
    ("exfiltration", "Asks for secrets or data to be sent elsewhere", 0.95,
     re.compile(r"(?i)\b(send|post|upload|email|exfiltrate|forward|leak)\b[^.\n]{0,60}\b(secrets?|credentials?|tokens?|passwords?|api keys?|env(?:ironment)?)\b")),
    ("privileged-action", "Asks for a privileged action", 0.85,
     re.compile(r"(?i)\b(deploy|merge|push|rollback|delete|drop|grant)\b[^.\n]{0,60}\b(production|prod|main|master|database|permissions?|admin)\b")),
    ("self-modification", "Asks the agent to change its own rules", 0.9,
     re.compile(r"(?i)\b(update|change|rewrite|modify|edit|disable|remove)\b[^.\n]{0,40}\b(your|its|the agent'?s?)\s+(own\s+)?(instructions?|polic(?:y|ies)|system prompt|permissions?|approval)")),
    ("approval-bypass", "Asks to skip human approval", 0.9,
     re.compile(r"(?i)\b(human\s+)?approval\b[^.\n]{0,30}\b(no longer|not)\s+(required|needed|necessary)\b|\b(skip|bypass|without)\b[^.\n]{0,20}\b(approval|review|security)\b")),
    ("hidden-channel", "Contains an encoded or hidden instruction marker", 0.5,
     re.compile(r"(?i)<!--[^>]{0,200}(instruction|ignore|system)[^>]{0,200}-->|\bbase64\s*:\s*[A-Za-z0-9+/=]{24,}")),
]


@dataclass
class InjectionFinding:
    rule: str
    label: str
    confidence: float
    line: int
    excerpt: str

    def as_dict(self) -> dict:
        return asdict(self)


# A policy that says "no agent may deploy to production" is a prohibition, not an attack. A match
# is ignored when the text before it on the same line negates it.
NEGATION = re.compile(r"(?i)\b(no|never|not|cannot|can't|must not|may not|nobody|forbidden|without)\b")
TRUSTED_THRESHOLD = 0.97    # trusted documents need two independent strong signals
UNTRUSTED_THRESHOLD = 0.5   # untrusted documents are quarantined on one


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Join indented continuation lines so a hard-wrapped sentence is judged as one sentence."""
    lines: list[tuple[int, str]] = []
    for number, line in enumerate((text or "").splitlines(), start=1):
        if lines and line[:1] in (" ", "\t") and line.strip() and lines[-1][1].strip():
            lines[-1] = (lines[-1][0], lines[-1][1].rstrip() + " " + line.strip())
        else:
            lines.append((number, line))
    return lines


def scan(text: str) -> list[InjectionFinding]:
    findings: list[InjectionFinding] = []
    for number, line in _logical_lines(text):
        for rule, label, confidence, pattern in PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            sentence_so_far = re.split(r"[.;:!?]\s", line[:match.start()])[-1]
            if not NEGATION.search(sentence_so_far):
                findings.append(InjectionFinding(rule, label, confidence, number, line.strip()[:200]))
    return findings


def should_quarantine(findings: list[InjectionFinding], trusted: bool) -> bool:
    return risk_score(findings) >= (TRUSTED_THRESHOLD if trusted else UNTRUSTED_THRESHOLD)


def risk_score(findings: list[InjectionFinding]) -> float:
    """Combine independent signals: 1 - prod(1 - confidence)."""
    score = 1.0
    for rule in {f.rule: f for f in findings}.values():
        score *= 1 - rule.confidence
    return round(1 - score, 3)


def is_injection(text: str, threshold: float = 0.75) -> bool:
    return risk_score(scan(text)) >= threshold
