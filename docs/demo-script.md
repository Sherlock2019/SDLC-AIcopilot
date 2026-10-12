# Ten-minute demo script

For presenting to a jury of AI practitioners. Times are targets. Sign in as **Dana** (default),
Learn Mode on. Reset first from the Dashboard if the lab has been used.

## Opening (30 seconds)

"Most AI-in-engineering demos show a model writing code. This one shows the system around the
model: what it is allowed to touch, how we know its output is good, and who is accountable. Three
sentences drive the design." Point at the three quotes on the Dashboard.

Say this early, because experts will ask: "The model here is a deterministic mock, so this runs
with no API key. Everything else is computed live: policy decisions, git, test execution, scans,
retrieval, evaluation, the capability graph."

## 1. Requirement to approved design (2 minutes)

1. Click **START GUIDED DEMO**, then **Run this step**.
2. On **Requirements**, show that each acceptance criterion cites a rule and a retrieved source, and the orange card: the request said sessions "may optionally" be invalidated, policy SEC-12 says mandatory, and the agent surfaced the conflict instead of choosing.
3. **Approve**. Run context retrieval. On **Context Engine**, show selected against rejected chunks, the budget bar, and the quarantined hostile document.
4. Run architecture. Three options with trade-offs. Switch user to **Alex** and try to approve: refused, wrong role. Switch to **Priya** (architect) and approve option B. Switch back to Dana.

Point: approvals are role-based and enforced by the server, not by the UI.

## 2. Code, tests, review (2 minutes)

1. Run code generation. Show the diff, the output-validation checks, and "Commits on main by AI: 0".
2. Run tests. These are **really executed**: 3 tests to 32, coverage 89% to 99%, in a subprocess with five environment variables.
3. Run review. Open the low-confidence finding: it is a deliberate false positive, with the reviewer note explaining why.

## 3. The capability auditor (3 minutes, the centrepiece)

1. Run the security step. **It blocks.**
2. Open **Security**. "This agent's policy denies production deploy, merge and secrets. It would pass a permissions review. Here is what it can reach." Trace the red path on the graph.
3. Read the finding: `Coding Agent -> GitHub MCP -> github.workflow.write -> pipeline definitions -> edited CI workflow -> production.deploy`.
4. Open the **Red team** tab, run it: transitive access is VULNERABLE, everything else BLOCKED.
5. Back on the first tab, **APPLY RECOMMENDED POLICY**. The path disappears. Run red team again: 9 of 9 blocked. Retry the step.

Point: the policy engine approved every individual call. Only the graph saw the path.

## 4. Evaluation and delivery (1.5 minutes)

1. Run evaluation: 26 fixtures. On **Evaluation**, click **Run comparison**: prompt v1 scores about 31%, v2 100%; the smaller model is cheaper and misses session invalidation.
2. Run PR and CI. Show the gates. Approve, then click **MERGE** as a human.
3. Run staging. Show that the Deployment Advisor's request to deploy returned REQUIRE_APPROVAL and was not executed. Approve as Dana or Sam. Deploy.

## 5. Incident and RCA (1.5 minutes)

1. Run monitoring, then **SIMULATE INCIDENT**.
2. Run triage and RCA. Show the ranked hypotheses with evidence for and against, and the suspect release scored by time proximity and file overlap. "That ranking is code. The model only writes the narrative."
3. Approve the rollback. Service restored. Run the RCA document step: it is added to the context index, so the next retrieval finds it.

## Closing (30 seconds)

Open **Productivity**. "These before/after numbers are simulated and labelled. This panel is
measured: what this feature cost in tokens, how many actions were blocked, how many decisions were
human." Then **Governance -> Audit timeline** and search `production`.

## Things to try if asked

- **Kill switch** (top bar): every tool call returns TOOL EXECUTION DISABLED BY OPERATOR.
- **Dry run**: shows the planned tool calls with real policy verdicts, including a merge attempt shown as DENY.
- **New run with prompt v1** (Journey page): the security gate stops it on SQL injection and token logging.
- **Architecture Diagram -> What is real and what is simplified**: the honest list.

## Likely questions

| Question | Short answer |
|---|---|
| Why not a real LLM? | Reproducibility and zero setup. Adapters exist for eight providers; they need your keys and are not verified in CI. |
| Is the sandbox secure? | It is process isolation with a scrubbed environment. Network is not blocked, and the auditor reports that as an accepted risk. |
| Why not LangGraph? | The native engine persists to the lab's database with no dependency. The same steps compile to a LangGraph graph, tested with interrupts. |
| Is pgvector used? | No. Embeddings are in memory. The vector store is an interface with pgvector as the documented swap-in. |
| How do you know the graph is complete? | You do not. It is as complete as the topology file, which is why that file is reviewed like code. |
