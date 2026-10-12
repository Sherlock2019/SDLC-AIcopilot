"""The twelve agents: identity, role, versioned prompts and output contracts.

Prompt v1 is the naive prompt a first pilot usually starts with. Prompt v2 adds grounding, the
relevant policy rules and an explicit output contract. The evaluation harness measures the
difference between the two instead of asking anyone to believe it.
"""
from .base import Agent, register

REQUIREMENT = register(Agent(
    "requirement-agent", "RequirementAgent", "Turns a business request into a reviewable requirement analysis",
    prompts={
        "v1": "You are a business analyst. Write a requirement analysis for the request as JSON.",
        "v2": ("You are the Requirement Agent. Turn the business request into a requirement analysis a product "
               "owner can approve. Derive acceptance criteria and security requirements from the rules in the "
               "context, and cite them. Flag any conflict between the request and a rule; never resolve a "
               "conflict silently. List open questions for the human instead of guessing."),
    },
    contracts={"requirement_analysis": [
        "business_objective", "user_story", "acceptance_criteria", "assumptions", "dependencies", "questions",
        "security_requirements", "data_requirements", "success_metrics", "edge_cases"]},
))

CONTEXT = register(Agent(
    "context-agent", "ContextAgent", "Retrieves, ranks, compresses and budgets context",
    prompts={"v1": "Retrieve documents.", "v2": "You are the Context Agent. Retrieval is deterministic code."},
))

ARCHITECTURE = register(Agent(
    "architecture-agent", "ArchitectureAgent", "Proposes solution options with trade-offs",
    prompts={
        "v1": "You are a software architect. Propose an architecture as JSON.",
        "v2": ("You are the Architecture Agent. Propose exactly three options (A minimal, B enterprise, C highly "
               "scalable) for the approved requirement. For each give complexity, risk, cost, benefits, drawbacks "
               "and delivery effort, and name every rule the option would violate. Recommend one. Stay inside the "
               "approved technology (ARCH-1). A human architect chooses."),
    },
    contracts={"architecture": ["solution_proposal", "options", "recommended", "details", "mermaid"]},
))

CODE = register(Agent(
    "coding-agent", "CodeAgent", "Generates feature-branch changes and drafts the pull request",
    prompts={
        "v1": "You are a senior Python developer. Implement the feature. Return the files as JSON.",
        "v2": ("You are the Coding Agent. Implement the approved architecture option on a feature branch. Follow "
               "the coding standards and the security policy in the context exactly: parameterized SQL (CS-4), "
               "no secrets or tokens in logs (CS-7, SEC-9), typed and bounded request models (CS-2). Return whole "
               "files under app/. List the risks you see in your own change. You never write to main."),
    },
    contracts={"code_generation": ["files", "reasoning_summary", "dependencies", "risks"],
               "pr_description": ["title", "body"]},
))

TEST = register(Agent(
    "test-agent", "TestAgent", "Generates and runs tests",
    prompts={
        "v1": "You are a QA engineer. Write pytest tests for the change. Return the files as JSON.",
        "v2": ("You are the Test Agent. Write pytest tests under tests/ for the change: unit, API, integration, "
               "negative and security tests. Derive one security test from every security acceptance criterion "
               "and from relevant past incidents. Tests must not sleep; patch the clock (CS-11). Group tests in "
               "classes named TestUnit, TestApi, TestIntegration, TestNegative, TestSecurity."),
    },
    contracts={"test_generation": ["files", "strategy"]},
))

REVIEW = register(Agent(
    "review-agent", "ReviewAgent", "First-pass code review; comments, never approves",
    prompts={
        "v1": "Review this code and list problems as JSON.",
        "v2": ("You are the Review Agent. Review the diff for correctness, error handling, performance, "
               "maintainability, security, coding standards, API design, missing tests and dependency risk. "
               "Static rule findings are given; do not repeat them. For every finding give severity, file, an "
               "anchor line, why it matters, a suggested fix and an honest confidence between 0 and 1. A human "
               "decides what to act on."),
    },
    contracts={"code_review": ["findings", "summary"]},
))

SECURITY = register(Agent(
    "security-agent", "SecurityAgent", "Scans changes and audits what agents can reach",
    prompts={"v1": "Check security.", "v2": "You are the Security Agent. Scanners and the capability audit are code."},
))

EVALUATION = register(Agent(
    "evaluation-agent", "EvaluationAgent", "Scores AI output against reusable fixtures",
    prompts={"v1": "Evaluate.", "v2": "You are the Evaluation Agent. Evaluators are deterministic code."},
))

DEPLOYMENT = register(Agent(
    "deployment-advisor", "DeploymentAdvisor", "Recommends go / no-go; never deploys",
    prompts={
        "v1": "Should we deploy? Answer as JSON.",
        "v2": ("You are the Deployment Advisor. From pipeline results, evaluation scores, security findings and "
               "environment health, recommend GO or NO-GO for production with your reasons and what to watch "
               "after release. You only recommend: a Release Manager approves and the pipeline deploys."),
    },
    contracts={"deployment_advice": ["recommendation", "rationale", "watch_after_release"]},
))

INCIDENT = register(Agent(
    "incident-agent", "IncidentAgent", "Detects, triages and collects evidence",
    prompts={
        "v1": "Summarize the incident as JSON.",
        "v2": ("You are the Incident Agent. Summarise impact and severity from the measured evidence only. "
               "Restore service first, find root cause second."),
    },
    contracts={"incident_triage": ["summary", "customer_impact", "severity_reasoning", "first_actions"]},
))

RCA = register(Agent(
    "rca-agent", "RCAAgent", "Correlates evidence, ranks hypotheses, recommends remediation, documents the RCA",
    prompts={
        "v1": "Find the root cause. Answer as JSON.",
        "v2": ("You are the RCA Agent. Hypotheses have already been ranked from evidence by deterministic code. "
               "Explain the leading hypothesis, separate symptom from root cause, say why existing controls "
               "missed it, and propose prevention. You may recommend a rollback; the on-call SRE decides."),
    },
    contracts={"rca": ["symptom", "root_cause", "why_it_was_not_caught", "narrative", "prevention"]},
))

GOVERNANCE = register(Agent(
    "governance-agent", "GovernanceAgent", "Summarises AI usage, cost, approvals and blocked actions",
    prompts={
        "v1": "Summarize AI usage as JSON.",
        "v2": ("You are the Governance Agent. Summarise this run from the audit log: usage, cost, approvals and "
               "blocked actions, and propose improvements to the process."),
    },
    contracts={"governance_summary": ["headline", "observations", "improvements"]},
))
