"""Scripted answers for the mock provider, one function per agent task.

Every function has the signature (payload, prompt_version, model) -> dict and returns exactly
the JSON shape the corresponding agent validates. Where an answer cites a rule (SEC-7, API-4 ...)
the citation is resolved against the context that was really retrieved, so grounding is honest:
if retrieval did not surface the rule, the citation is missing and the evaluation says so.
"""
from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "mock_fixtures" / "password_reset"
SESSION_INVALIDATION_LINE = '    db.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))\n'
MOCK_NOTICE = ("Mock AI ships a full implementation script for the default password-reset scenario only. "
               "Set MOCK_AI=false and configure a provider to generate arbitrary features.")


def is_password_reset(text: str) -> bool:
    lowered = (text or "").lower()
    return "reset" in lowered and "password" in lowered


def _cite(rules: list[str], sources: list[dict]) -> list[str]:
    return [s["citation"] for s in sources if any(rule in s.get("text", "") for rule in rules)]


def _criterion(index: int, text: str, rules: list[str], sources: list[dict]) -> dict:
    return {"id": f"AC-{index}", "text": text, "rules": rules, "citations": _cite(rules, sources)}


# --- requirement analysis -----------------------------------------------------------------------
def requirement_analysis(payload: dict, prompt_version: str, model: str) -> dict:
    requirement, sources = payload["requirement"], payload.get("sources", [])
    if not is_password_reset(requirement):
        return _generic_requirement(requirement, sources)
    if prompt_version == "v1":
        # Ungrounded prompt: fluent, confident, and partly invented.
        return {
            "business_objective": "Allow customers to reset a forgotten password.",
            "user_story": {"as_a": "registered customer", "i_want": "to reset my password",
                           "so_that": "I can log in again"},
            "acceptance_criteria": [
                {"id": "AC-1", "text": "Customer receives a reset code by email", "rules": [], "citations": []},
                {"id": "AC-2", "text": "Reset code is valid for 24 hours", "rules": [], "citations": []},
                {"id": "AC-3", "text": "Unknown email returns 404 so the customer can correct a typo",
                 "rules": [], "citations": []},
            ],
            "assumptions": ["Email delivery is available"],
            "dependencies": ["SendGrid account (see docs/email-integration.md)"],
            "questions": [],
            "security_requirements": [{"text": "Follow OWASP guidance (rule PR-9 in docs/security-handbook.md)",
                                       "rules": ["PR-9"], "citations": []}],
            "data_requirements": ["Store the reset code on the users table"],
            "success_metrics": ["Customers can reset passwords"],
            "edge_cases": ["Email not found"],
            "conflicts": [],
        }
    criteria = [
        ("A reset token expires 15 minutes after it is issued", ["SEC-7"]),
        ("A reset token is single-use and is invalidated when redeemed", ["SEC-10"]),
        ("The reset token never appears in logs, traces or error messages", ["SEC-9", "CS-7"]),
        ("The request endpoint answers identically for known and unknown email addresses", ["SEC-11", "API-5"]),
        ("Only a hash of the token is stored; the plaintext exists only in the email", ["SEC-8", "DB-1"]),
        ("All existing sessions of the account are invalidated after a successful reset", ["SEC-12"]),
        ("The new password must be at least 12 characters", ["SEC-1"]),
        ("At most 5 reset requests per account per hour are honoured", ["SEC-13", "SEC-4"]),
        ("POST /password-reset/request returns 202; POST /password-reset/confirm returns 200, 400 or 422",
         ["API-1", "API-4"]),
    ]
    if model == "mock-small":
        criteria = [c for c in criteria if "SEC-12" not in c[1]]
    return {
        "business_objective": ("Let customers regain access to their account without contacting support, "
                               "without weakening account security."),
        "user_story": {"as_a": "registered customer",
                       "i_want": "to reset my forgotten password securely",
                       "so_that": "I can regain access without contacting support"},
        "acceptance_criteria": [_criterion(i, text, rules, sources) for i, (text, rules) in enumerate(criteria, 1)],
        "assumptions": [
            "Every customer account has a verified email address.",
            "Email is sent through the existing notifications module; this environment uses an outbox.",
            "Multi-factor authentication is out of scope for this change.",
        ],
        "dependencies": [
            "notifications.py is the only module allowed to send email (architecture.md).",
            "An additive schema change: a new password_reset_tokens table (DB-2, DB-3).",
            "Deployment manifest must list any new setting in the same pull request (DEP-4).",
        ],
        "questions": [
            "Should the customer be notified by email after a successful reset?",
            "Is per-IP rate limiting required in addition to the per-account limit?",
            "May support staff trigger a reset on behalf of a customer?",
        ],
        "security_requirements": [
            {"text": "Generate tokens with a cryptographically secure source, at least 256 bits", "rules": ["SEC-8"],
             "citations": _cite(["SEC-8"], sources)},
            {"text": "Use parameterized SQL for every query", "rules": ["CS-4"], "citations": _cite(["CS-4"], sources)},
            {"text": "Treat this workflow as an account-takeover path: any shortcut is a security defect",
             "rules": ["SEC-3", "SEC-11"], "citations": _cite(["SEC-3", "SEC-11"], sources)},
        ],
        "data_requirements": [
            "New table password_reset_tokens(token_hash, user_id, created_at, expires_at, used_at).",
            "No personal data in logs: log user_id only.",
            "Index on (user_id, created_at) for the rate-limit lookup (DB-4).",
        ],
        "success_metrics": [
            "At least 85% of started resets complete successfully.",
            "Password-related support tickets drop by 60%.",
            "Zero reset tokens found by the log scanner.",
            "p95 latency of both endpoints under 300 ms.",
        ],
        "edge_cases": [
            "Several outstanding tokens for one account", "Token redeemed twice (double click, replay)",
            "Token used after expiry", "Email with different case or surrounding spaces",
            "Unknown email address", "Weak new password (token must not be consumed)",
            "Reset while the customer has active sessions", "Rate limit reached",
        ],
        "conflicts": [
            {"text": "The request says old sessions 'may optionally' be invalidated. SEC-12 makes it mandatory. "
                     "This analysis treats it as mandatory.",
             "rules": ["SEC-12"], "citations": _cite(["SEC-12"], sources)},
        ] if model != "mock-small" else [],
    }


def _generic_requirement(requirement: str, sources: list[dict]) -> dict:
    criteria = [
        ("New endpoints follow the API guidelines for paths, verbs and status codes", ["API-1", "API-4"]),
        ("All SQL is parameterized", ["CS-4"]),
        ("No secret, token or personal data is written to logs", ["CS-7", "SEC-5"]),
        ("The change ships with API, negative and security tests and keeps coverage above 80%", ["CS-9", "CS-10"]),
        ("The change arrives as a pull request from a feature branch", ["CS-12"]),
    ]
    return {
        "business_objective": f"Deliver: {requirement.strip().rstrip('.')}.",
        "user_story": {"as_a": "customer of the portal", "i_want": requirement.strip().rstrip(".").lower(),
                       "so_that": "I can complete my task without contacting support"},
        "acceptance_criteria": [_criterion(i, t, r, sources) for i, (t, r) in enumerate(criteria, 1)],
        "assumptions": ["The feature fits the existing FastAPI service and database."],
        "dependencies": ["Any new runtime dependency needs an architecture decision (ARCH-1)."],
        "questions": ["Who is the business owner of this feature?", "What is the measurable success target?"],
        "security_requirements": [{"text": "Model output is reviewed and tested like untrusted code",
                                   "rules": ["SEC-14"], "citations": _cite(["SEC-14"], sources)}],
        "data_requirements": ["Schema changes are additive and idempotent (DB-3)."],
        "success_metrics": ["Feature adoption and error rate are tracked per route."],
        "edge_cases": ["Invalid input", "Unauthenticated caller", "Repeated request"],
        "conflicts": [],
        "notice": MOCK_NOTICE,
    }


# --- architecture -------------------------------------------------------------------------------
ARCHITECTURE_DIAGRAM = """flowchart LR
  customer([Customer])
  api["FastAPI router<br/>password_reset.py"]
  users[(users)]
  tokens[(password_reset_tokens)]
  sessions[(sessions)]
  notify["notifications.py<br/>email outbox"]
  customer -->|"1. POST /password-reset/request"| api
  api -->|"2. look up account"| users
  api -->|"3. store SHA-256 hash + expiry"| tokens
  api -->|"4. plaintext token"| notify
  notify -.->|"5. reset link by email"| customer
  customer -->|"6. POST /password-reset/confirm"| api
  api -->|"7. verify hash, expiry, unused"| tokens
  api -->|"8. update password hash"| users
  api -->|"9. delete sessions"| sessions
"""


def architecture(payload: dict, prompt_version: str, model: str) -> dict:
    sources = payload.get("sources", [])
    options = [
        {
            "key": "A", "name": "Minimal implementation",
            "summary": "One hashed reset token per account stored in two new columns on the users table. "
                       "No rate limiting, no session invalidation.",
            "complexity": "Low", "risk": "High", "cost": "Low", "effort": "0.5 day",
            "scores": {"complexity": 1, "risk": 4, "cost": 1, "effort": 1},
            "benefits": ["Smallest change", "No new table"],
            "drawbacks": ["Violates SEC-12 (sessions survive) and SEC-13 (no rate limit)",
                          "A second request silently invalidates the first email",
                          "Alters an existing table (DB-3 prefers additive changes)"],
            "policy_gaps": ["SEC-12", "SEC-13"],
        },
        {
            "key": "B", "name": "Enterprise implementation",
            "summary": "Dedicated password_reset_tokens table with hash, expiry and used_at, per-account rate "
                       "limit, generic responses, session invalidation, email through the notifications module.",
            "complexity": "Medium", "risk": "Low", "cost": "Low", "effort": "1.5 days",
            "scores": {"complexity": 3, "risk": 1, "cost": 2, "effort": 2},
            "benefits": ["Meets every rule from SEC-7 to SEC-13", "Additive schema change, trivial rollback",
                         "No new runtime dependency (ARCH-1)", "Auditable: one row per reset attempt"],
            "drawbacks": ["Expired rows need periodic clean-up", "Rate limit is per account, not per IP"],
            "policy_gaps": [],
        },
        {
            "key": "C", "name": "Highly scalable implementation",
            "summary": "Separate recovery service, tokens in Redis with native TTL, email sent through a "
                       "message queue with retries, distributed rate limiting.",
            "complexity": "High", "risk": "Medium", "cost": "High", "effort": "2-3 weeks",
            "scores": {"complexity": 5, "risk": 3, "cost": 5, "effort": 5},
            "benefits": ["Handles very high request volumes", "Email retries and back-pressure",
                         "Per-IP and per-account rate limiting"],
            "drawbacks": ["Three new dependencies need an architecture decision (ARCH-1)",
                          "More moving parts to operate, monitor and secure",
                          "Far beyond the current load of the portal"],
            "policy_gaps": ["ARCH-1"],
        },
    ]
    return {
        "solution_proposal": ("Add a two-step, token-based reset to the existing API service. Option B is "
                              "recommended: it satisfies every security rule with no new dependency and a "
                              "fully reversible schema change."),
        "options": options,
        "recommended": "B",
        "details": {
            "components_affected": ["app/password_reset.py (new router)", "app/notifications.py (new)",
                                    "app/db.py (schema)", "app/config.py (settings)", "app/main.py (wiring)"],
            "api_changes": ["POST /password-reset/request -> 202 with a generic body",
                            "POST /password-reset/confirm -> 200, 400 (invalid, expired or used) or 422"],
            "database_changes": ["CREATE TABLE password_reset_tokens(token_hash PK, user_id, created_at, "
                                 "expires_at, used_at)", "CREATE INDEX on (user_id, created_at)"],
            "security_model": ["256-bit random token from the secrets module", "SHA-256 hash at rest",
                               "15 minute expiry, single use", "Generic response prevents account enumeration",
                               "Sessions deleted on success", "5 requests per account per hour"],
            "logging": ["One event per outcome with user_id only", "Token and email are never logged"],
            "monitoring": ["Reset requests, confirmations and rejections per minute",
                           "Error rate and p95 latency per route", "Alert on rejection spikes (possible attack)"],
            "deployment_changes": ["New settings RESET_TOKEN_TTL_SECONDS and RESET_MAX_REQUESTS_PER_HOUR "
                                   "with safe defaults", "Schema is created idempotently at start-up"],
            "dependencies": ["None beyond the approved stack"],
        },
        "citations": _cite(["ARCH-1", "ARCH-2", "SEC-7", "SEC-8", "DB-1", "DB-2", "DB-3", "API-4"], sources),
        "mermaid": ARCHITECTURE_DIAGRAM,
        **({} if is_password_reset(payload.get("requirement", "")) else {"notice": MOCK_NOTICE}),
    }


# --- code and tests -----------------------------------------------------------------------------
def _read_tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text() for p in sorted(root.rglob("*.py"))}


def code_files(prompt_version: str, model: str) -> dict[str, str]:
    files = _read_tree(FIXTURES / "v2")
    if prompt_version == "v1":
        files.update(_read_tree(FIXTURES / "v1"))
    elif model == "mock-small":
        files["app/password_reset.py"] = files["app/password_reset.py"].replace(SESSION_INVALIDATION_LINE, "")
    return files


def test_files(prompt_version: str, model: str) -> dict[str, str]:
    files = _read_tree(FIXTURES / "tests")
    if prompt_version == "v1":
        happy_path_only = files["tests/test_password_reset.py"].split("\n\nclass TestNegative")[0] + "\n"
        return {"tests/test_password_reset.py": happy_path_only}
    return files


def code_generation(payload: dict, prompt_version: str, model: str) -> dict:
    grounded = prompt_version != "v1"
    return {
        "files": code_files(prompt_version, model),
        "reasoning_summary": [
            "Implemented architecture option B: a dedicated token table and a new router, no new dependency.",
            "Tokens come from secrets.token_urlsafe(32); only the SHA-256 hash is stored (SEC-8, DB-1).",
            "Expiry, single use and session invalidation are enforced in the confirm handler (SEC-7, SEC-10, SEC-12).",
            "The request handler returns one generic 202 response for every outcome (SEC-11, API-5).",
            "The token is passed only to notifications.send_reset_email and never to a logger (SEC-9).",
        ] if grounded else [
            "Added request and confirm endpoints for password reset.",
            "Stored the token in a new table and emailed it to the customer.",
        ],
        "dependencies": [],
        "risks": [
            "Known and unknown accounts do different amounts of work, so response time may differ slightly.",
            "Rate limiting is per account only.",
            "Expired token rows are never purged.",
        ] if grounded else ["None identified."],
        **({} if is_password_reset(payload.get("requirement", "")) else {"notice": MOCK_NOTICE}),
    }


def test_generation(payload: dict, prompt_version: str, model: str) -> dict:
    return {
        "files": test_files(prompt_version, model),
        "strategy": [
            "Unit tests for hashing and configuration values.",
            "API tests for status codes and response bodies of both endpoints.",
            "Integration tests for the complete reset-then-login flow.",
            "Negative tests for bad tokens, weak passwords and missing fields.",
            "Security tests derived one-to-one from SEC-7 to SEC-13 and from incident history.",
            "Back-fill for existing gaps found in auth.py (profile and session expiry were untested).",
        ] if prompt_version != "v1" else ["Happy-path tests for the two new endpoints."],
    }


# --- review -------------------------------------------------------------------------------------
def code_review(payload: dict, prompt_version: str, model: str) -> dict:
    files = payload.get("files", {})
    source = files.get("app/password_reset.py", "")
    if "token_hash" not in source:
        return {"findings": [], "summary": "Static rules already report blocking security defects. "
                                           "No further review until those are fixed."}
    findings = [
        {"severity": "MEDIUM", "category": "security", "file": "app/password_reset.py",
         "anchor": "notifications.send_reset_email(email, token)",
         "title": "Response time can reveal whether an account exists",
         "why": "A known account triggers an INSERT and an email; an unknown one returns immediately. "
                "SEC-11 asks for no observable difference, and timing is observable.",
         "fix": "Queue the email asynchronously, or perform equivalent dummy work for unknown accounts.",
         "confidence": 0.71},
        {"severity": "LOW", "category": "maintainability", "file": "app/password_reset.py",
         "anchor": "INSERT INTO password_reset_tokens",
         "title": "Expired and used tokens are never purged",
         "why": "The table grows without bound and keeps data longer than needed.",
         "fix": "Delete rows older than 24 hours in a scheduled job, or opportunistically on request.",
         "confidence": 0.86},
        {"severity": "LOW", "category": "security", "file": "app/password_reset.py",
         "anchor": "recent >= config.RESET_MAX_REQUESTS_PER_HOUR",
         "title": "Rate limit is per account only",
         "why": "One client can still trigger reset emails for many different accounts.",
         "fix": "Add a per-IP limit at the gateway. Raised as an open question in the requirement.",
         "confidence": 0.78},
        {"severity": "INFO", "category": "api-design", "file": "app/password_reset.py",
         "anchor": "GENERIC_RESPONSE = {",
         "title": "Shared response dictionary is returned by reference",
         "why": "A future handler that mutates it would change every later response.",
         "fix": "Return a copy, or build the body in a small function.",
         "confidence": 0.62},
        {"severity": "INFO", "category": "security", "file": "app/security.py", "anchor": "def hash_token",
         "title": "Token hash is unsalted SHA-256",
         "why": "Unsalted fast hashes are weak for passwords.",
         "fix": "Consider a salted slow hash.",
         "confidence": 0.34,
         "reviewer_note": "Likely false positive: the token is 256 bits of randomness, not a human password, "
                          "so salting and key stretching add nothing. Left visible on purpose - low-confidence "
                          "findings need human judgement."},
    ]
    if "DELETE FROM sessions" not in source:
        findings = [f for f in findings if f["title"] != "Shared response dictionary is returned by reference"]
    return {"findings": findings,
            "summary": "No blocking issue. One medium finding on timing, the rest are hardening suggestions."}


# --- pull request -------------------------------------------------------------------------------
def pr_description(payload: dict, prompt_version: str, model: str) -> dict:
    p = payload
    files = "\n".join(f"- `{f['path']}` ({f['status']}, +{f['additions']} / -{f['deletions']})" for f in p["files"])
    findings = "\n".join(f"- **{f['severity']}** {f['title']} (`{f['file']}:{f['line']}`)" for f in p["findings"]) \
        or "- None"
    body = f"""## Business requirement
{p['requirement']}

## Architecture decision
Option {p['option']['key']} - {p['option']['name']}, approved by {p['architect']}.
{p['option']['summary']}

## Files changed
{files}

## Tests added
{p['tests']['passed']} of {p['tests']['total']} tests pass. Coverage {p['coverage_before']}% -> {p['tests']['coverage']}%.
Categories: {', '.join(f"{k} {v['passed']}/{v['total']}" for k, v in p['tests']['by_category'].items())}.

## Risks
{chr(10).join('- ' + r for r in p['risks'])}

## Security findings
{p['severity_counts'].get('CRITICAL', 0)} critical, {p['severity_counts'].get('HIGH', 0)} high, {p['severity_counts'].get('MEDIUM', 0)} medium.
{findings}

## Evaluation result
Overall {p['evaluation']['score']}%, security {p['evaluation']['security_score']}% ({p['evaluation']['passed']} of {p['evaluation']['total']} fixtures pass).

## Deployment impact
Additive schema change created idempotently at start-up. Two new optional settings with safe defaults.
Rollback is a redeploy of the previous image; the new table can stay.

---
This description was drafted by the Coding Agent. A human reviewer decides whether it merges.
"""
    return {"title": p["title"], "body": body}


# --- operations ---------------------------------------------------------------------------------
def deployment_advice(payload: dict, prompt_version: str, model: str) -> dict:
    blockers = payload.get("blockers", [])
    return {
        "recommendation": "NO-GO" if blockers else "GO",
        "rationale": blockers or [
            f"All {payload['tests_total']} tests pass and coverage is {payload['coverage']}%.",
            f"AI evaluation score is {payload['eval_score']}% (gate: above 80%).",
            "No critical or high security finding is open.",
            "Staging health check returned the expected version.",
            "The schema change is additive, so rollback is a redeploy of the previous image.",
        ],
        "watch_after_release": ["Error rate of /password-reset/* for 30 minutes",
                                "Rejection rate of /password-reset/confirm (attack signal)",
                                "Login error rate (sessions are invalidated on reset)"],
        "note": "This is a recommendation. A Release Manager approves; the pipeline deploys.",
    }


def incident_triage(payload: dict, prompt_version: str, model: str) -> dict:
    return {
        "summary": (f"{payload['route']} has returned HTTP 500 for {payload['error_rate_pct']}% of requests since "
                    f"{payload['started']}. Other routes are healthy."),
        "customer_impact": "Customers cannot start a password reset. Login and profile are unaffected.",
        "severity_reasoning": "One customer-facing recovery path is fully down, with no workaround except support.",
        "first_actions": ["Collect error logs for the failing route", "Compare error onset with recent deployments",
                          "Check whether a rollback target exists"],
    }


def rca(payload: dict, prompt_version: str, model: str) -> dict:
    top, change = payload["top_hypothesis"], payload["suspect_change"]
    return {
        "symptom": f"{payload['route']} returns HTTP 500.",
        "root_cause": (f"Release {change['version']} renamed the setting RESET_TOKEN_TTL_SECONDS to "
                       f"RESET_TOKEN_TTL_MINUTES and reads it without a default. The deployment manifest was not "
                       f"updated, so the variable is missing in production and every request raises "
                       f"{top['signature']}."),
        "why_it_was_not_caught": [
            "The test environment sets the new variable, so every test passed.",
            "The service does not validate required settings at start-up (ARCH-3), so the health check stayed green.",
            "The pull request changed a setting name without touching the deployment manifest (DEP-4).",
        ],
        "narrative": (f"Errors start {payload['minutes_after_deploy']} minutes after {change['version']} reached "
                      f"production. All errors share one stack trace ending in app/config.py, the file changed by "
                      f"that release. Traffic volume and database latency are normal, which rules out load and "
                      f"database causes."),
        "prevention": [
            "Validate required settings at start-up so a bad release fails its health check, not customers.",
            "Add a CI check: a pull request that changes config.py must also change the deployment manifest.",
            "Add a smoke test that calls /password-reset/request against staging with production-like settings.",
            "Add this incident to the context repository and to the evaluation fixtures.",
        ],
    }


def governance_summary(payload: dict, prompt_version: str, model: str) -> dict:
    return {
        "headline": (f"{payload['agent_runs']} agent runs, {payload['tool_calls']} tool calls, "
                     f"{payload['blocked']} blocked by policy, {payload['approvals']} human approvals."),
        "observations": [
            f"Total AI cost for this feature: ${payload['cost_usd']:.4f}.",
            "No agent merged, deployed or read a secret. Every such attempt was denied and logged.",
            "Every production-affecting action carries the name of the human who approved it.",
        ],
        "improvements": [
            "Add the incident as a regression fixture to the evaluation suite.",
            "Run test.run in a network-isolated container to close the accepted sandbox risk.",
            "Review agent cost ceilings quarterly against measured usage.",
        ],
    }


TASKS = {
    "requirement_analysis": requirement_analysis,
    "architecture": architecture,
    "code_generation": code_generation,
    "test_generation": test_generation,
    "code_review": code_review,
    "pr_description": pr_description,
    "deployment_advice": deployment_advice,
    "incident_triage": incident_triage,
    "rca": rca,
    "governance_summary": governance_summary,
}
