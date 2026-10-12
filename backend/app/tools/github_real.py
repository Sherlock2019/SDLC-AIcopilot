"""MODE B - real GitHub sandbox repository (optional, GITHUB_ENABLED=true).

Uses a fine-grained personal access token with the minimum permissions:
Contents read/write, Pull requests read/write, Actions read. See docs/github-sandbox-setup.md.

Deliberately absent from this client: merge, delete repository, branch protection changes,
secrets, collaborators, organisation management. A human merges on github.com.

Status: follows the documented GitHub REST API. It needs your own sandbox token to be verified;
it is not exercised by the test-suite, which never touches the network.
"""
from __future__ import annotations

import base64

import httpx

from ..config import settings


class GitHubError(RuntimeError):
    pass


class GitHubSandbox:
    def __init__(self, token: str = "", repo: str = "", api: str = ""):
        self.repo = repo or settings.github_repo
        self.api = (api or settings.github_api).rstrip("/")
        token = token or settings.github_token
        if not token or "/" not in self.repo:
            raise GitHubError("Set GITHUB_TOKEN and GITHUB_REPO=owner/name to use the GitHub sandbox.")
        self.client = httpx.Client(timeout=30, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ai-sdlc-champion-lab"})

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self.client.request(method, f"{self.api}/repos/{self.repo}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(f"Could not reach GitHub: {exc}") from None
        if response.status_code >= 400:
            raise GitHubError(f"GitHub returned {response.status_code} for {method} {path}: {response.text[:200]}")
        return response

    # --- read ----------------------------------------------------------------------------------
    def repository(self) -> dict:
        data = self._request("GET", "").json()
        return {"full_name": data["full_name"], "private": data["private"], "default_branch": data["default_branch"]}

    def read_file(self, path: str, ref: str) -> tuple[str, str] | None:
        try:
            data = self._request("GET", f"/contents/{path}", params={"ref": ref}).json()
        except GitHubError as error:
            if "returned 404" in str(error):
                return None
            raise
        return base64.b64decode(data["content"]).decode(), data["sha"]

    def pr_diff(self, number: int) -> str:
        return self._request("GET", f"/pulls/{number}", headers={"Accept": "application/vnd.github.diff"}).text

    def actions_result(self, branch: str) -> dict:
        runs = self._request("GET", "/actions/runs", params={"branch": branch, "per_page": 1}).json()["workflow_runs"]
        if not runs:
            return {"status": "none"}
        return {"status": runs[0]["status"], "conclusion": runs[0]["conclusion"], "url": runs[0]["html_url"]}

    # --- write (feature branches and pull requests only) ---------------------------------------
    def create_branch(self, name: str, base: str) -> None:
        if name == base or name in ("main", "master"):
            raise GitHubError("Refusing to write to the default branch.")
        sha = self._request("GET", f"/git/ref/heads/{base}").json()["object"]["sha"]
        try:
            self._request("POST", "/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})
        except GitHubError as error:
            if "returned 422" not in str(error):  # 422 = branch already exists
                raise

    def commit_file(self, branch: str, path: str, content: str, message: str) -> None:
        if branch in ("main", "master") or path.startswith(".github/"):
            raise GitHubError("Refusing to write to the default branch or to pipeline definitions.")
        existing = self.read_file(path, branch)
        body = {"message": message, "branch": branch, "content": base64.b64encode(content.encode()).decode()}
        if existing:
            if existing[0] == content:
                return
            body["sha"] = existing[1]
        self._request("PUT", f"/contents/{path}", json=body)

    def open_pull_request(self, branch: str, base: str, title: str, body: str) -> dict:
        data = self._request("POST", "/pulls", json={"title": title, "head": branch, "base": base, "body": body}).json()
        return {"number": data["number"], "url": data["html_url"]}

    def add_comment(self, number: int, body: str) -> None:
        self._request("POST", f"/issues/{number}/comments", json={"body": body})


def publish_run(run, pull_request, files: dict[str, str], review_comment: str = "") -> dict:
    """Mirror a run's feature branch into the sandbox repository and open a pull request there."""
    github = GitHubSandbox()
    info = github.repository()
    github.create_branch(pull_request.branch, info["default_branch"])
    for path, content in sorted(files.items()):
        github.commit_file(pull_request.branch, path, content, f"{pull_request.title} ({path})\n\nAI-Generated: true")
    opened = github.open_pull_request(pull_request.branch, info["default_branch"], pull_request.title,
                                      pull_request.description)
    if review_comment:
        github.add_comment(opened["number"], review_comment)
    return {**opened, "repository": info["full_name"], "private": info["private"],
            "merge": "A human merges on github.com. This client has no merge function."}
