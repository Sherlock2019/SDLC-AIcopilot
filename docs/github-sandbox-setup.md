# Setting up a safe GitHub sandbox repository

The lab runs completely without GitHub (MODE A, local mock git). This guide is for MODE B:
mirroring a run's feature branch into a real repository and opening a real pull request, so that
GitHub Actions runs the real pipeline.

You do **not** need a second GitHub account. One dedicated repository in your existing account is enough.

## 1. Create the repository

1. Create a new repository named `ai-sdlc-champion-sandbox`.
2. Make it **private**.
3. Initialise it with a README so that `main` exists.
4. Copy the contents of `sample_app/` and `.github/workflows/ai-sdlc-ci.yml` from this project into it and commit.

Keep it clean:

- No real secrets, in the repository or in its Actions secrets.
- No production integrations, no deployment keys, no cloud credentials.
- Nothing else lives in this repository.

## 2. Protect `main`

Settings -> Branches -> add a rule for `main`:

- Require a pull request before merging, with at least one approval.
- Require status checks to pass (select `ai-sdlc-ci`).
- Do not allow bypassing these settings.

Add a `CODEOWNERS` file so pipeline changes always need you:

```
/.github/workflows/  @your-username
```

This is the control that the lab's capability auditor asks for: write access to pipeline
definitions is production access.

## 3. Create a fine-grained personal access token

Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens -> Generate new token.

- **Repository access:** Only select repositories -> `ai-sdlc-champion-sandbox`
- **Expiration:** 7 days is plenty for a demo
- **Repository permissions (minimum only):**

| Permission | Access |
|------------|--------|
| Contents | Read and write |
| Pull requests | Read and write |
| Actions | Read-only |
| Metadata | Read-only (added automatically) |

Do **not** grant: Administration, Secrets, Workflows, Environments, or any organisation permission.
Leaving out the *Workflows* permission means GitHub itself refuses a push that touches
`.github/workflows/`, which backs up the lab's own path constraint.

## 4. Configure the lab

Create `.env` next to `docker-compose.yml` (it is git-ignored):

```
GITHUB_ENABLED=true
GITHUB_TOKEN=<your fine-grained token>
GITHUB_REPO=your-username/ai-sdlc-champion-sandbox
```

Restart with `docker compose up`. The top bar shows **GitHub sandbox**. On the Pull Requests
page, after the AI has opened its pull request, click **Open this PR in ...**.

## What the integration can and cannot do

| The lab's GitHub client can | It has no code for |
|-----------------------------|--------------------|
| Read the repository | Merging a pull request |
| Create a feature branch | Deleting a repository |
| Commit files to that branch | Changing branch protection or repository security |
| Open a pull request | Managing collaborators or organisation permissions |
| Read a pull request diff | Writing to `main` or to `.github/` (refused in code) |
| Add the AI review as a comment | Reading or writing Actions secrets |
| Read the GitHub Actions result | |

**You** click Merge on github.com.

## Later: GitHub App or OAuth

A personal token is right for a single-user demo. For a team, replace it with a GitHub App:
installation tokens are short-lived, scoped per repository, and actions are attributed to the app
rather than to a person. `backend/app/tools/github_real.py` isolates every call behind one class,
so only the token source changes.

## Status

The client follows the documented GitHub REST API but is not exercised by the automated tests,
which never touch the network. Verify it against your sandbox before a live demo, and revoke the
token afterwards.
