---
type: guide
status: current
owner: Platform Engineering
---
# Deployment

## Environments

| Environment | Purpose | Who can deploy |
|-------------|---------|----------------|
| DEV | Every merged commit | Pipeline, automatically |
| TEST | Integration and AI evaluation suite | Pipeline, automatically |
| STAGING | Production-like verification | Pipeline, after all quality gates pass |
| PRODUCTION | Customers | Pipeline, only after a named Release Manager approves |

## Promotion flow (DEP-1)

Source -> lint -> tests -> AI evaluation -> security scan -> build image -> STAGING ->
human approval -> PRODUCTION. An artifact is built once and promoted unchanged.

## Quality gates (DEP-2)

All tests pass, coverage above 80 percent, no CRITICAL security finding, AI evaluation score
above 80 percent, no policy violation.

## Identities (DEP-3)

The deployment identity belongs to the pipeline. No developer and no AI agent holds a
production credential. An agent may recommend a deployment or a rollback; it cannot perform one.

## Configuration changes (DEP-4)

A change that adds, renames or removes an environment variable must update the deployment
manifest in the same pull request, and the service must validate required settings at start-up.

## Rollback (DEP-5)

Rollback redeploys the previous image. It is the default first response to a failed release:
restore service first, find the root cause second, automate prevention third. A production
rollback needs approval from the on-call SRE.

## Health checks (DEP-6)

`GET /health` must return `200` with the expected version within 30 seconds of a deployment,
otherwise the pipeline marks the release failed.
