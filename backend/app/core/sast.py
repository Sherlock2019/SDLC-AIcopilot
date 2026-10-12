"""Small static analyser for Python changes.

These rules are deterministic code, not model output. The Review and Security agents run them
first and let the model add judgement on top, so a missed model finding never hides a rule hit.
"""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import asdict, dataclass

from . import secrets_scan

SENSITIVE_NAMES = re.compile(r"(?i)(token|password|passwd|secret|api_?key|email)")
SAFE_SUFFIX = re.compile(r"(?i)(_id|_hash|_count|_ttl|_length)$")
APPROVED_IMPORTS = {"fastapi", "pydantic", "starlette", "sqlite3", "app", "pytest", "httpx"}


@dataclass
class Finding:
    rule: str
    severity: str
    category: str
    file: str
    line: int
    title: str
    why: str
    fix: str
    confidence: float = 0.95
    source: str = "static-rule"

    def as_dict(self) -> dict:
        return asdict(self)


def _is_dynamic_string(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _contains_str(node)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _contains_str(node.func.value)
    return False


def _contains_str(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str) for n in ast.walk(node)) or any(
        isinstance(n, ast.JoinedStr) for n in ast.walk(node))


def _names(node: ast.AST) -> list[str]:
    names = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
    return names


def scan_python(path: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding("PY-000", "HIGH", "correctness", path, exc.lineno or 1, "File does not parse",
                        "Code that does not parse cannot be tested or deployed.", "Fix the syntax error.")]

    for node in ast.walk(tree):
        # SQL built from strings
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {
                "execute", "executemany", "executescript"} and node.args and _is_dynamic_string(node.args[0]):
            findings.append(Finding(
                "SQLI-001", "CRITICAL", "security", path, node.lineno,
                "SQL statement built with string interpolation",
                "User-controlled values become part of the SQL text, which allows SQL injection (CS-4).",
                "Use a parameterized query: db.execute(\"... WHERE email = ?\", (email,)).", 0.97))

        # Sensitive values in log calls
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {
                "debug", "info", "warning", "error", "exception", "critical"} and _names(node.func.value)[:1] in (
                ["logger"], ["logging"], ["log"]):
            leaked = [n for arg in node.args[1:] + [k.value for k in node.keywords] for n in _names(arg)
                      if SENSITIVE_NAMES.search(n) and not SAFE_SUFFIX.search(n)]
            if node.args and isinstance(node.args[0], ast.JoinedStr):
                leaked += [n for n in _names(node.args[0]) if SENSITIVE_NAMES.search(n) and not SAFE_SUFFIX.search(n)]
            if leaked:
                findings.append(Finding(
                    "LOG-001", "HIGH", "security", path, node.lineno,
                    f"Sensitive value written to logs ({', '.join(sorted(set(leaked)))})",
                    "Logs are widely readable and long lived. A logged reset token is a usable credential (SEC-9, CS-7).",
                    "Log the event name and the internal user_id only.", 0.9))

        # Weak randomness for security values
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(
                node.func.value, ast.Name) and node.func.value.id == "random":
            findings.append(Finding(
                "RAND-001", "HIGH", "security", path, node.lineno,
                "Non-cryptographic random source",
                "The random module is predictable and must not be used for tokens (SEC-8).",
                "Use secrets.token_urlsafe(32).", 0.8))

        # Swallowed exceptions
        if isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception")) and all(
                isinstance(stmt, ast.Pass) for stmt in node.body):
            findings.append(Finding(
                "EXC-001", "LOW", "error-handling", path, node.lineno,
                "Exception swallowed silently",
                "Failures disappear, which hides incidents and makes root cause analysis harder (CS-8).",
                "Log and convert to a defined error response, or re-raise.", 0.9))

        # Unbounded request strings
        if isinstance(node, ast.ClassDef) and any(_names(base)[-1:] == ["BaseModel"] for base in node.bases):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.annotation, ast.Name) \
                        and stmt.annotation.id == "str" and stmt.value is None:
                    findings.append(Finding(
                        "VAL-001", "LOW", "api-design", path, stmt.lineno,
                        f"Request field '{getattr(stmt.target, 'id', '?')}' has no length limit",
                        "Unbounded input is a cheap denial-of-service vector (API-9, CS-2).",
                        "Declare Field(max_length=...).", 0.85))

        # Unapproved dependencies
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for module in modules:
                root = module.split(".")[0]
                if isinstance(node, ast.ImportFrom) and node.level:
                    continue
                if root and root not in sys.stdlib_module_names and root not in APPROVED_IMPORTS:
                    findings.append(Finding(
                        "DEP-001", "MEDIUM", "dependency", path, node.lineno,
                        f"New third-party dependency '{root}'",
                        "New runtime dependencies need an architecture decision and a supply-chain review (ARCH-1, CS-3).",
                        "Use the standard library or request approval for the dependency.", 0.8))

    findings += _reset_token_rules(path, source)
    for secret in secrets_scan.scan_text(source, surface="source", source=path):
        findings.append(Finding(
            "SECRET-001", "CRITICAL", "secrets", path, secret.line,
            f"{secret.label} committed to source ({secret.preview})",
            "A credential in source control must be treated as compromised (SEC-5).",
            "Remove it, rotate it, and load it from the platform secret store at deploy time.", 0.9))
    return sorted(findings, key=lambda f: (f.file, f.line))


def _line_of(source: str, pattern: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if re.search(pattern, line):
            return number
    return 1


def _reset_token_rules(path: str, source: str) -> list[Finding]:
    """Domain rules for credential-like tables (DB-1, DB-2, SEC-7, SEC-8, SEC-10, SEC-11)."""
    if "password_reset_tokens" not in source or "INSERT INTO" not in source.upper():
        return []
    findings = []
    insert_line = _line_of(source, r"(?i)INSERT INTO password_reset_tokens")
    if "token_hash" not in source:
        findings.append(Finding(
            "TOK-001", "HIGH", "security", path, insert_line, "Reset token stored in plaintext",
            "Anyone who can read the table or a backup can take over accounts (SEC-8, DB-1).",
            "Store hash_token(token) in a token_hash column.", 0.9))
    if "expires_at" not in source:
        findings.append(Finding(
            "TOK-002", "HIGH", "security", path, insert_line, "Reset token never expires",
            "A leaked link stays usable for ever. Policy requires 15 minutes (SEC-7).",
            "Store expires_at and reject tokens past it.", 0.9))
    if "used_at" not in source and "DELETE FROM password_reset_tokens" not in source:
        findings.append(Finding(
            "TOK-003", "HIGH", "security", path, insert_line, "Reset token can be used more than once",
            "A token seen once (proxy log, browser history) can be replayed (SEC-10).",
            "Mark the token used in the same transaction that changes the password.", 0.88))
    if re.search(r"status_code\s*=\s*404", source) and "email" in source:
        findings.append(Finding(
            "ENUM-001", "MEDIUM", "security", path, _line_of(source, r"status_code\s*=\s*404"),
            "Response reveals whether an account exists",
            "Different answers for known and unknown emails allow account enumeration (SEC-11, API-5).",
            "Return the same 202 response in both cases.", 0.85))
    if "DELETE FROM sessions" not in source:
        findings.append(Finding(
            "SESS-001", "MEDIUM", "security", path, _line_of(source, r"UPDATE users SET password_hash"),
            "Existing sessions survive a password reset",
            "An attacker who already holds a session keeps access after the customer resets (SEC-12).",
            "Delete the account's sessions when the password changes.", 0.85))
    return findings


def scan_files(files: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    for path, source in sorted(files.items()):
        if path.endswith(".py"):
            findings += scan_python(path, source)
        else:
            for secret in secrets_scan.scan_text(source, surface="source", source=path):
                findings.append(Finding(
                    "SECRET-001", "CRITICAL", "secrets", path, secret.line,
                    f"{secret.label} committed to source ({secret.preview})",
                    "A credential in source control must be treated as compromised (SEC-5).",
                    "Remove it and rotate it.", 0.9))
    return findings


def missing_test_findings(files: dict[str, str], test_sources: dict[str, str]) -> list[Finding]:
    """Every route declared in the change should be exercised by at least one test."""
    tests = "\n".join(test_sources.values())
    findings = []
    for path, source in files.items():
        prefix = re.search(r"APIRouter\(prefix=\"([^\"]+)\"", source)
        for match in re.finditer(r"@router\.(get|post|put|delete|patch)\(\"([^\"]*)\"", source):
            route = (prefix.group(1) if prefix else "") + match.group(2)
            if route and route not in tests:
                findings.append(Finding(
                    "TEST-001", "MEDIUM", "missing-tests", path, source[:match.start()].count("\n") + 1,
                    f"No test exercises {match.group(1).upper()} {route}",
                    "Untested endpoints regress silently (CS-9).",
                    "Add API, negative and security tests for the endpoint.", 0.9))
    return findings
