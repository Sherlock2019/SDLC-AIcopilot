# Security architecture

> Treat LLM output as **untrusted input**.

The lab assumes that a model can be wrong, can be manipulated, and can be replaced by a different
model tomorrow. Safety therefore never depends on the model behaving well. It depends on code the
model cannot change.

## The one line every action crosses

```
Agent request -> kill switch -> policy check -> permission check -> approval check
              -> (dry run?) -> tool execution -> output screening -> audit log
```

Implemented in `backend/app/core/gateway.py`. No agent holds a reference to a tool. Agents hold a
gateway.

## Principles and where they live

| Principle | Implementation |
|-----------|----------------|
| Least privilege | One YAML policy per agent in `policies/agents/`. Default deny. |
| Zero trust | Every call is authorised at the gateway, whoever makes it. Unknown identities and unknown tools are denied. |
| Human approval | `REQUIRE_APPROVAL` decisions need an approval decided by a known human holding the required role. Approvals are single-use and bound to one action and one run. |
| Invariants | `policies/global.yaml` lists actions no AI agent can ever be granted (merge, secrets, IAM, policy changes, approvals). A policy file that allows `*` still cannot grant them. Covered by `tests/test_policy_critical.py`. |
| Separation of duties | An agent may *request* a production deployment or rollback. Only the pipeline identity executes it, and only with a human approval. An agent holding a valid approval is still refused. |
| Sandbox execution | Generated code runs in a subprocess on a clean `git archive` export, with a scrubbed environment and a timeout (`tools/sandbox.py`). |
| Tool allowlisting | Tools exist only if registered and described in `policies/topology.yaml`. |
| Network allowlisting | `network_allowlist` in the global policy is empty; `network.fetch` is denied for every agent. |
| Secrets isolation | No agent can call `secrets.read`. Prompts are redacted before they are sent; tool results are redacted before they are returned. |
| Auditability | Every model call, tool call, decision, approval and blocked step is a row in `audit_logs`. |
| Untrusted model output | Strict JSON parsing, per-task contracts, path and syntax validation, secret scan, tests, evaluation, human review. |
| Untrusted context | Retrieved documents are wrapped as data. Chunks that look like instructions are quarantined before they reach a prompt. |

## Capability and escape-path analysis

A permissions review answers "what was this agent granted?". The auditor in
`backend/app/core/capability.py` answers "what can this agent reach?" by walking

```
AGENT -> MCP SERVER -> TOOL -> API -> RESOURCE -> ACTION -> SYSTEM -> ACTION ...
```

over the grants in the policy files plus the links between systems in `policies/topology.yaml`.
The demo configuration `policies/scenarios/unsafe-coding-agent.yaml` explicitly denies
`production.deploy`, and the auditor still finds:

```
CRITICAL  UNEXPECTED TRANSITIVE ACCESS
Coding Agent -> GitHub MCP server -> github.workflow.write -> pipeline definitions
             -> CI workflow edited on a branch -> production.deploy
```

The workflow's security stage refuses to continue while such a path exists.

## Known limits (stated, not hidden)

- **The sandbox is process isolation, not a container.** Network egress from generated code is not
  blocked. The sandbox holds no credentials, and the auditor reports this path for every agent that
  can run tests as an accepted risk. Production use needs `--network none` or gVisor.
- **Injection and secret detection are pattern based.** They are tripwires. The actual protection is
  that injected text cannot raise permissions.
- **The topology file is hand-written.** The auditor is only as complete as the links declared in it.
  In a real estate those links should be discovered from IAM, repository and pipeline configuration.
- **Identity is a header.** The demo trusts `X-User`. A deployment needs real authentication (OIDC)
  in front of the API.
