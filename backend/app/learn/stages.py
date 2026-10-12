"""Learn Mode: the eight questions answered for every SDLC stage, and Teach Me at three levels."""

MESSAGES = [
    "AI should increase engineering capability, not silently increase engineering risk.",
    "Before asking what an AI agent can do, verify what it is actually able to reach.",
    "AI proposes. Humans remain accountable.",
]

AI_MAY = ["analyze", "suggest", "generate drafts", "generate tests", "recommend fixes", "summarize", "investigate"]
AI_MAY_NOT = ["merge to main", "access production secrets", "change production infrastructure",
              "bypass security controls", "approve its own output", "grant itself permissions",
              "deploy to production", "perform irreversible operations"]


def _stage(title, agent, happening, doing, why, data, risks, human, metrics):
    return {"title": title, "agent": agent, "what_is_happening": happening, "what_is_the_ai_doing": doing,
            "why_use_ai_here": why, "what_data_does_ai_see": data, "what_can_go_wrong": risks,
            "what_must_a_human_approve": human, "how_do_we_measure_success": metrics}


STAGES = {
    "requirements": _stage(
        "Requirement analysis", "requirement-agent",
        "A one-line business request is turned into something engineers can build and testers can verify.",
        "The AI drafts a user story, acceptance criteria, security requirements, assumptions, edge cases and "
        "open questions, and links each criterion to the written rule it comes from.",
        "A first draft takes seconds instead of a meeting, and the AI reliably remembers rules people forget, "
        "such as the 15 minute token expiry in the security policy.",
        ["The business request", "Retrieved policy and guideline chunks", "Nothing from production"],
        ["It can invent requirements nobody asked for", "It can miss what the business really means",
         "It can sound confident about a rule that does not exist"],
        "A product owner or engineer approves, requests changes or rejects the analysis before any design starts.",
        ["Share of criteria with a citation", "Requirement changes after approval", "Time from request to approved requirement"]),
    "context": _stage(
        "Context engineering (RAG)", "context-agent",
        "The system decides which documents and code the next agents are allowed to read.",
        "It splits documents into chunks, turns them into vectors, finds the chunks closest to the question, "
        "filters out deprecated and hostile content, compresses what is left and fits it into a token budget.",
        "A model only knows your rules if you show them. Retrieval gives it the right pages instead of all pages.",
        ["Context repository documents", "Sample application source", "Document metadata: type, status, trust"],
        ["Wrong chunk retrieved, right-sounding answer produced", "Outdated document treated as current",
         "A retrieved document contains instructions (prompt injection)", "Too much context hides the important line"],
        "Nobody approves each retrieval. Humans own the documents, their metadata and the budget.",
        ["Relevance of selected chunks", "Tokens used versus budget", "Injection attempts quarantined", "Citation coverage"]),
    "architecture": _stage(
        "Architecture proposal", "architecture-agent",
        "Possible designs for the feature are compared before anyone writes code.",
        "The AI proposes three options, from minimal to highly scalable, with complexity, risk, cost, benefits "
        "and effort, names the rules each option would break, and recommends one.",
        "Comparing options is tedious to write and easy to skip. AI makes the trade-offs explicit every time.",
        ["Approved requirement", "Architecture, schema and policy chunks", "Repository file list"],
        ["Over-engineering that looks impressive", "A recommendation that ignores an operational constraint",
         "Proposing technology the organisation has not approved"],
        "A human architect chooses the option. The recommendation is advice.",
        ["Options that comply with policy", "Rework caused by design changes", "Time to an approved design"]),
    "code": _stage(
        "Code generation", "coding-agent",
        "The approved design is implemented on a feature branch.",
        "The AI reads the existing code and the coding standards, creates a branch and commits whole files. "
        "Its output is validated before it is written: paths, syntax and secrets are checked.",
        "Routine implementation is fast for AI, and it applies written standards consistently.",
        ["Approved requirement and architecture", "Coding standards and security policy", "Existing source files"],
        ["Subtle security bugs in plausible code", "Code that works but ignores the architecture",
         "Invented APIs or dependencies", "Changes outside the intended files"],
        "Nothing here is approved yet. The agent cannot write to main; a human reviews the pull request later.",
        ["Evaluation score", "Tests passing on first run", "Review findings per change", "Rework after review"]),
    "tests": _stage(
        "Test generation", "test-agent",
        "The change is tested before a human spends time reviewing it.",
        "The AI writes unit, API, integration, negative and security tests, derives one security test from each "
        "security criterion, and runs everything in a sandbox with a scrubbed environment.",
        "Negative and security tests are the ones people skip under time pressure. AI does not get bored.",
        ["Acceptance criteria", "Changed files", "Security policy and incident history"],
        ["Tests that pass but assert nothing useful", "Tests written to match buggy code",
         "Generated code executing something harmful, which is why it runs in a sandbox"],
        "Humans review test quality in the pull request. An independent reference suite checks behaviour in evaluation.",
        ["Coverage before and after", "Tests per category", "Security criteria with a test", "Failures found before review"]),
    "review": _stage(
        "AI code review", "review-agent",
        "A proposed code change is being reviewed before merge.",
        "Deterministic static rules run first. The AI then adds judgement on correctness, design and security, "
        "with a severity, a suggested fix and a confidence for every finding.",
        "A fast first pass lets human reviewers spend their attention on design and business logic.",
        ["The diff and changed files", "Coding standards and API guidelines", "Static rule findings"],
        ["Hallucinated findings", "Missed vulnerabilities", "Incorrect understanding of business logic",
         "Reviewers trusting the AI instead of reading the diff"],
        "A human engineer decides whether the change can be merged. The Review Agent can only comment.",
        ["PR review time", "Findings confirmed by humans", "False positive rate", "Defects found after merge"]),
    "security": _stage(
        "Security review and capability audit", "security-agent",
        "The change, the context and the agents themselves are checked for security problems.",
        "Scanners look for vulnerabilities and secrets. The capability auditor walks the graph from every agent "
        "through its tools to every action it can reach, including indirect paths through other systems.",
        "Scanning every change and re-auditing permissions on every run is cheap for software and rare for people.",
        ["The diff", "Agent policy files", "The capability topology", "The audit log"],
        ["A new kind of vulnerability no rule covers", "An undocumented link between systems the graph does not know",
         "Treating a passed scan as proof of safety"],
        "A security administrator changes policies. A critical finding blocks the workflow until a human fixes it.",
        ["Critical findings open", "Unexpected capability paths", "Blocked tool calls", "Secrets detected before merge"]),
    "evaluation": _stage(
        "AI evaluation", "evaluation-agent",
        "The quality of the AI's own output is measured against written expectations.",
        "Reusable fixtures ask concrete questions, for example: does the generated code implement expiration? "
        "Evaluators answer by inspecting the output and by running reference tests against it.",
        "Without measurement, a prompt or model change is a guess. Evaluation turns it into a number you can gate on.",
        ["Agent outputs", "Evaluation fixtures", "Generated code on the feature branch"],
        ["Fixtures that are too easy", "Optimising the score instead of the outcome", "Evaluators with their own bugs"],
        "Humans own the fixtures and the 80% threshold. The pipeline enforces it.",
        ["Overall score", "Security score", "Score by category", "Cost and latency per variant"]),
    "pull_request": _stage(
        "Pull request", "coding-agent",
        "The change is packaged with its evidence and offered for human review.",
        "The AI drafts the description: requirement, design decision, files, tests, risks, findings, evaluation "
        "result and deployment impact. The confidence figure is computed from that evidence, not guessed.",
        "Reviewers get the whole story in one place, written consistently, in seconds.",
        ["Diff statistics", "Test, review, security and evaluation results"],
        ["A persuasive description of a bad change", "Reviewers approving on the summary alone"],
        "A human approves, requests changes or rejects. A human clicks MERGE. No AI identity can.",
        ["Time to first review", "Review iterations", "Changes merged without rework"]),
    "cicd": _stage(
        "CI/CD pipeline", "ci-pipeline",
        "An automated pipeline checks the change the same way every time.",
        "AI is not in control here. It contributed the tests and the evaluation; the pipeline is ordinary "
        "automation that enforces gates: tests, coverage, security, evaluation score and policy violations.",
        "Gates make AI-generated change safe to accept at speed, because nothing depends on anyone's mood.",
        ["Repository at the pull request commit", "Results of earlier stages"],
        ["A gate that is too weak to matter", "A pipeline file that an agent is able to edit"],
        "Humans own the pipeline definition (CODEOWNERS). Production needs a Release Manager.",
        ["Pipeline duration", "Gate failures by type", "Lead time for changes"]),
    "deployment": _stage(
        "Deployment", "deployment-advisor",
        "One build is promoted through DEV, TEST and STAGING, then offered for production.",
        "The Deployment Advisor reads the evidence and recommends GO or NO-GO. It requests the deployment; the "
        "policy engine answers REQUIRE_APPROVAL. After approval the pipeline identity deploys.",
        "A consistent readiness check, with reasons, for every release.",
        ["Pipeline results", "Evaluation score", "Security findings", "Environment health"],
        ["A confident GO on incomplete evidence", "Any path that lets an agent deploy by itself"],
        "A Release Manager approves production. Everything in this lab's production is a simulation.",
        ["Deployment frequency", "Change failure rate", "Rollbacks"]),
    "observability": _stage(
        "Observability", "incident-agent",
        "The running system, the AI and the controls are all measured.",
        "AI reads metrics to check a release against its normal range. Every model call records model, prompt "
        "version, tokens, latency and cost; every tool call records its policy decision.",
        "You cannot govern or improve what you do not measure, and AI adds new things that need measuring.",
        ["Application metrics and logs (simulated)", "Agent run and tool call records (real)"],
        ["Dashboards nobody looks at", "Logs that contain secrets", "Measuring activity instead of outcomes"],
        "Humans set thresholds and decide what a signal means.",
        ["Error rate and latency", "AI cost per feature", "Blocked actions", "Injection attempts"]),
    "incident": _stage(
        "Incident response and RCA", "rca-agent",
        "Production is failing. Service must be restored, then the cause understood, then prevented.",
        "The Incident Agent measures impact and gathers logs, metrics and recent changes. The RCA Agent "
        "correlates errors with changes, ranks hypotheses with evidence for and against, and recommends a rollback.",
        "Evidence gathering under pressure is slow and error-prone for people. AI shortens time to a good hypothesis.",
        ["Application logs (secrets redacted)", "Metrics", "Deployment history and diffs", "Past incidents"],
        ["A plausible but wrong root cause", "Mistaking the symptom for the cause", "Acting on production without a human"],
        "The on-call SRE approves the rollback. The AI may recommend it and may not execute it.",
        ["Mean time to restore", "Time to first correct hypothesis", "Repeat incidents"]),
    "governance": _stage(
        "AI governance", "governance-agent",
        "The organisation keeps track of every AI capability it runs.",
        "The Governance Agent summarises usage, cost, approvals and blocked actions from the audit log.",
        "Governance evidence is assembled continuously instead of once a year by hand.",
        ["Audit log", "Agent policies", "Usage metrics"],
        ["Governance as paperwork that does not match reality", "Policies nobody tests"],
        "Owners are accountable for their agents. Security administrators change policies. Operators hold the kill switch.",
        ["Agents with a named owner", "Actions with an audit record", "Cost versus ceiling", "Policy violations"]),
    "productivity": _stage(
        "Productivity and business value", "governance-agent",
        "The value of AI assistance is compared with what it costs.",
        "AI cost is computed from real token counts. The before and after comparison in this lab is simulated "
        "demo data and is labelled as such.",
        "Investment decisions need numbers, and AI spend is unusually easy to measure precisely.",
        ["Agent run records", "Delivery metrics"],
        ["Counting generated lines as productivity", "Claiming a gain that was never measured",
         "Ignoring the cost of review and rework"],
        "Engineering leadership decides what to measure and whether the outcome justifies the spend.",
        ["Cycle time", "DORA metrics", "Cost per feature", "Return on investment"]),
}

QUESTIONS = [
    ("what_is_happening", "What is happening?"),
    ("what_is_the_ai_doing", "What is the AI doing?"),
    ("why_use_ai_here", "Why use AI here?"),
    ("what_data_does_ai_see", "What data does AI see?"),
    ("what_tools_can_ai_use", "What tools can AI use?"),
    ("what_can_go_wrong", "What can go wrong?"),
    ("what_must_a_human_approve", "What must a human approve?"),
    ("how_do_we_measure_success", "How do we measure success?"),
]


def _teach(title, beginner, engineer, architect):
    return {"title": title, "beginner": beginner, "engineer": engineer, "architect": architect}


TEACH = {
    "dashboard": _teach(
        "The big picture",
        "Building software is a chain of steps, from an idea to a running product. This lab shows an AI helping "
        "at every step while people stay in charge of the decisions that matter.",
        "Each stage is an agent with a narrow job, a policy file and a set of tools behind a gateway. Stages hand "
        "artifacts to each other through a persisted state machine with approval gates.",
        "Treat AI in the SDLC as a socio-technical system: capability (agents), control (policy, approvals, "
        "sandbox) and evidence (evaluation, audit) have to be designed together, or you get speed without safety."),
    "journey": _teach(
        "The SDLC journey",
        "Purple steps are done by AI, blue steps by a person, grey steps by automation. Red means something was "
        "stopped by a safety rule.",
        "The workflow is an explicit state machine. A human step is an interrupt: the engine cannot pass it, and "
        "the decision is recorded with who, when and why.",
        "Explicit state and explicit gates are what make an agentic workflow auditable and resumable. Avoid "
        "designs where the model itself decides when a human is needed."),
    "requirements": _teach(
        "Requirement engineering with AI",
        "The AI rewrites a short wish into a clear list of what must be true when the work is done.",
        "The agent retrieves policy first, then drafts criteria that cite rule ids. Ungrounded criteria are a "
        "smell. Conflicts between the request and policy are surfaced, never silently resolved.",
        "Requirements are where AI errors are cheapest to catch. Put a human gate here and measure citation "
        "coverage; every later stage inherits whatever was approved."),
    "context": _teach(
        "Context engineering and RAG",
        "The AI has not read your company's rules. Before it works, the system hands it the few pages that matter.",
        "Chunk, embed, search, filter, rank, compress, budget. Every step can lose the answer, so the lab shows "
        "the trace: what was selected, what was rejected and why.",
        "Context is an attack surface and a cost centre. Retrieved text is data, never instructions. Budget "
        "tokens deliberately: more context raises cost and can lower quality."),
    "architecture": _teach(
        "Architecture with AI",
        "Before building, the AI sketches three ways to do it, cheap to ambitious, and a person picks one.",
        "The agent must name the rules each option breaks. The selected option becomes an input contract for "
        "the coding agent and for evaluation.",
        "Use AI to widen the option space and document trade-offs, not to decide. The architect stays "
        "accountable for fit with the organisation's constraints, which no model fully sees."),
    "code": _teach(
        "AI code generation",
        "The AI writes the code on a separate copy called a branch, so nothing changes until people agree.",
        "Model output is untrusted input: validate paths, parse it, scan it for secrets, then commit to a "
        "feature branch through a tool that refuses main.",
        "Constrain the blast radius structurally: branch and path constraints in policy, plus a tool that "
        "enforces them again. Do not rely on the prompt to keep an agent inside its lane."),
    "tests": _teach(
        "AI test generation",
        "The AI writes checks that try to break the new code, especially in ways an attacker would.",
        "Tests run in a subprocess with a scrubbed environment. Coverage and results are measured, not "
        "reported by the model. An independent reference suite guards against tests that fit the bug.",
        "Generated tests executed by a generated-code runner is arbitrary code execution. Isolate it, give it "
        "no credentials and no network, and audit that path in the capability graph."),
    "pull_request": _teach(
        "Pull requests and human review",
        "A pull request is a proposal to change the product. The AI writes the summary; a person says yes or no.",
        "The description is assembled from measured evidence. Merge is a human-only code path: the gateway "
        "has an invariant that no policy file can override.",
        "Separation of duties still applies. The author, the reviewer and the approver must not be the same "
        "identity, and an AI must never be the approver of AI work."),
    "review": _teach(
        "AI code review",
        "The AI reads the change like a careful colleague and points at things that look wrong.",
        "Deterministic rules first, model judgement second, confidence on every finding. Low-confidence findings "
        "are shown, not hidden: one of them here is a deliberate false positive.",
        "AI review reduces reviewer load, it does not transfer accountability. Track precision of findings; "
        "a noisy reviewer trains people to ignore it."),
    "security": _teach(
        "AI security and capability control",
        "We check what the AI is able to do, not only what it was told to do. Sometimes those differ.",
        "Permissions are transitive. An agent that can edit a pipeline file can deploy, even with deploy denied. "
        "The auditor computes reachability over agent, tool, resource and system links.",
        "Model the estate as a graph and audit paths, not grants. Least privilege, default deny, non-overridable "
        "invariants, human approval on irreversible actions, and a kill switch are the baseline."),
    "evaluation": _teach(
        "AI evaluation",
        "We give the AI's work a test with known right answers, so we get a score instead of an opinion.",
        "Fixtures plus evaluators give a repeatable score per category. Compare prompt versions and models on "
        "accuracy, security, latency, tokens and cost before changing anything in production.",
        "Evaluation is the regression suite for non-deterministic components. Gate releases on it and add a "
        "fixture for every incident, exactly as you would add a test for every bug."),
    "cicd": _teach(
        "CI/CD",
        "Every change goes through the same automatic checks. If a check fails, the change stops.",
        "Lint, tests, AI evaluation, security scan, build, staging. Gates are thresholds on measured values. "
        "The pipeline definition itself is protected from agents.",
        "The pipeline is the enforcement point for AI-generated change. Protect its definition and its "
        "identity as production assets: write access to the pipeline is production access."),
    "deployment": _teach(
        "Deployment",
        "The new version is tried in practice environments first. A person decides when it goes live.",
        "The advisor requests production.deploy and receives REQUIRE_APPROVAL. Approval is consumed once by "
        "the pipeline identity. Rollback is the first response to a bad release.",
        "Keep the deployment identity separate from every developer and agent identity. AI recommends, a "
        "named human approves, automation executes, and all three are recorded."),
    "observability": _teach(
        "Observability",
        "We watch the product, the AI and the safety rules with dashboards, like instruments in a cockpit.",
        "Three views: application (requests, latency, errors), AI (model, prompt version, tokens, cost, "
        "latency) and security (denied tools, injection attempts, unexpected paths).",
        "AI observability belongs next to application observability, with the same rigor. Cost and blocked "
        "actions are first-class signals, not afterthoughts."),
    "incident": _teach(
        "Incidents and root-cause analysis",
        "Something broke. First get it working again, then find out why, then make sure it cannot happen again.",
        "An incident is an unplanned loss of service. MTTR is how long it lasts. The symptom is what you see "
        "(HTTP 500); the root cause is why (a renamed setting with no default). Recent changes come first.",
        "Logs say what happened, metrics say how much, traces say where. Use AI to compress evidence into "
        "ranked hypotheses, and keep the remediation decision with the accountable human."),
    "governance": _teach(
        "AI governance",
        "For every AI helper we write down who owns it, what it may touch and who must approve its actions.",
        "One YAML file per agent is both the enforced policy and the governance record: owner, purpose, data, "
        "tools, approvals, cost ceiling, retention. The audit log proves it was followed.",
        "Governance that is not machine-enforced drifts. Make the policy file the single source of truth for "
        "runtime enforcement, the capability graph and the governance report."),
    "productivity": _teach(
        "Measuring productivity and ROI",
        "We compare how long things took before and after AI help, and what the AI cost.",
        "Measure flow (cycle time, review time), quality (coverage, defects) and stability (DORA). AI cost is "
        "exact: tokens times price. Value is engineer hours saved times a rate you choose.",
        "AI does not automatically improve DORA metrics. It moves the bottleneck to review and verification. "
        "Measure outcomes for your organisation; do not import someone else's numbers."),
    "learn": _teach(
        "How to use the curriculum",
        "Nineteen short lessons, each with a small example and a quiz.",
        "Each lesson pairs a toy example with the real one implemented in this repository.",
        "Use it as onboarding material for teams adopting AI in delivery."),
    "architecture_diagram": _teach(
        "System architecture",
        "A map of the boxes that make up this lab and how they talk to each other.",
        "React UI, FastAPI, a workflow engine, and five services: context engine, agent runtime, policy engine, "
        "evaluation harness and tool gateway. PostgreSQL stores state and audit.",
        "The important line on the diagram is the one every tool call crosses: the gateway. Put policy, "
        "approval, sandboxing and audit on that line and the rest of the system can change freely."),
}

CONTEXT_CONCEPTS = [
    ("Chunking", "Documents are cut into small passages (about 220 tokens here) so the system can fetch one "
                 "relevant passage instead of a whole manual."),
    ("Embeddings", "Each chunk becomes a list of numbers that captures its meaning. Texts about similar things "
                   "get similar numbers, so similarity can be computed."),
    ("Why retrieval matters", "A model cannot follow a rule it was never shown. Retrieval puts your rules, not "
                              "the internet's, in front of it."),
    ("Why too much context can hurt", "Long prompts cost more, run slower, and bury the one line that matters. "
                                      "A token budget forces a choice."),
    ("Hallucination", "A model produces fluent text even when it has no basis for it. Ungrounded answers are "
                      "where invented rules and files come from."),
    ("Why citations matter", "A citation lets a human check the claim in seconds, and lets evaluation measure "
                             "whether answers are grounded."),
]

RCA_CONCEPTS = [
    ("What is an incident?", "An unplanned event that degrades or stops a service customers depend on."),
    ("What is MTTR?", "Mean time to restore: the average time from the start of an incident until service is back."),
    ("What is a root cause?", "The underlying condition that made the failure possible. Removing it prevents recurrence."),
    ("Symptom versus root cause", "The symptom is what you observe: HTTP 500. The root cause is why: a setting was "
                                  "renamed without a default and without updating the deployment manifest."),
    ("Why recent changes matter", "Most incidents follow a change. The latest deployment is the first suspect and "
                                  "rolling it back is usually the fastest fix."),
    ("Why logs, metrics and traces together", "Metrics show that something is wrong and how badly. Logs show what "
                                              "failed. Traces show where in the request path. One alone misleads."),
]

SECURITY_PRINCIPLES = [
    ("Least privilege", "Each agent gets only the tools its task needs. The coding agent has seven, none of them near production."),
    ("Zero trust", "No identity is trusted because of where it runs. Every call is authorised at the gateway."),
    ("Human approval", "Irreversible and production-affecting actions need a named human with the right role."),
    ("Sandbox execution", "Generated code runs in a separate process with a scrubbed environment and a timeout."),
    ("Tool allowlisting", "Only registered tools exist. Anything else is denied as unknown."),
    ("Network allowlisting", "Outbound destinations are an explicit list. In this lab the list is empty."),
    ("Secrets isolation", "Agents have no route to a secret store. Prompts and tool results are redacted."),
    ("Auditability", "Every model call, tool call, policy decision and approval is recorded and searchable."),
    ("Untrusted model output", "LLM output is treated as untrusted input: parsed, validated, tested and reviewed."),
]
