"""MODE A - local mock git.

A real git repository created from sample_app/ inside the lab's data directory. Branches,
commits and diffs are real; nothing leaves the machine. `main` is write-protected here as well
as in the policy engine: defence in depth, the tool refuses even if the policy were wrong.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}


class GitError(RuntimeError):
    pass


class LocalGit:
    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    def ensure(cls, path: Path, seed_dir: Path) -> "LocalGit":
        repo = cls(path)
        if (repo.path / ".git").exists():
            return repo
        if repo.path.exists():
            shutil.rmtree(repo.path)
        shutil.copytree(seed_dir, repo.path, ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", "*.pyc", "*.db", ".coverage", "htmlcov"))
        (repo.path / ".gitignore").write_text("__pycache__/\n*.pyc\n*.db\n.coverage\ncoverage.json\njunit.xml\n.pytest_cache/\n")
        repo._git("init", "-q", "-b", "main")
        repo._commit_all("Customer Portal API v1.3.2 (health, login, profile)", "Customer Identity Team",
                         "identity-team@example.invalid")
        return repo

    # --- plumbing ------------------------------------------------------------------------------
    def _git(self, *args: str, check: bool = True, author: tuple[str, str] | None = None) -> str:
        name, email = author or ("AI-SDLC Lab", "lab@example.invalid")
        command = ["git", "-c", f"user.name={name}", "-c", f"user.email={email}", "-c", "commit.gpgsign=false",
                   "-c", "core.autocrlf=false", "-c", "advice.detachedHead=false", *args]
        proc = subprocess.run(command, cwd=self.path, capture_output=True, text=True, timeout=60)
        if check and proc.returncode != 0:
            raise GitError(proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout

    def _commit_all(self, message: str, name: str, email: str) -> str:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message, "--allow-empty", author=(name, email))
        return self.head()

    def _safe(self, relative: str) -> Path:
        target = (self.path / relative).resolve()
        if self.path.resolve() not in target.parents or ".git" in Path(relative).parts:
            raise GitError(f"Path '{relative}' escapes the repository.")
        return target

    # --- read ----------------------------------------------------------------------------------
    def head(self, ref: str = "HEAD") -> str:
        return self._git("rev-parse", "--short", ref).strip()

    def branches(self) -> list[str]:
        return [b.strip() for b in self._git("branch", "--format=%(refname:short)").splitlines() if b.strip()]

    def exists(self, ref: str) -> bool:
        return subprocess.run(["git", "rev-parse", "--verify", "-q", ref], cwd=self.path,
                              capture_output=True).returncode == 0

    def ls(self, ref: str = "main") -> list[str]:
        return [line for line in self._git("ls-tree", "-r", "--name-only", ref).splitlines() if line]

    def read(self, path: str, ref: str = "main") -> str:
        return self._git("show", f"{ref}:{path}")

    def read_all(self, ref: str = "main", suffix: str = ".py") -> dict[str, str]:
        return {p: self.read(p, ref) for p in self.ls(ref) if p.endswith(suffix)}

    def search(self, query: str, ref: str = "main") -> list[dict]:
        out = self._git("grep", "-n", "-I", "-i", "-F", query, ref, check=False)
        hits = []
        for line in out.splitlines()[:50]:
            parts = line.split(":", 3)
            if len(parts) == 4:
                hits.append({"path": parts[1], "line": int(parts[2]), "text": parts[3].strip()})
        return hits

    def log(self, ref: str = "main", limit: int = 20, first_parent: bool = False) -> list[dict]:
        out = self._git("log", ref, f"-{limit}", *(["--first-parent"] if first_parent else []),
                        "--date=iso-strict", "--pretty=format:%h%x1f%an%x1f%ad%x1f%s")
        return [dict(zip(("sha", "author", "date", "subject"), line.split("\x1f"))) for line in out.splitlines()]

    def diff(self, base: str = "main", head: str = "HEAD") -> str:
        return self._git("diff", "--no-color", f"{base}...{head}")

    def diff_stats(self, base: str = "main", head: str = "HEAD") -> list[dict]:
        status = {}
        for line in self._git("diff", "--name-status", f"{base}...{head}").splitlines():
            code, _, path = line.partition("\t")
            status[path] = {"A": "added", "M": "modified", "D": "deleted"}.get(code[:1], "modified")
        stats = []
        for line in self._git("diff", "--numstat", f"{base}...{head}").splitlines():
            added, deleted, path = line.split("\t")
            stats.append({"path": path, "status": status.get(path, "modified"),
                          "additions": int(added) if added.isdigit() else 0,
                          "deletions": int(deleted) if deleted.isdigit() else 0})
        return stats

    def export(self, ref: str, destination: Path) -> Path:
        """Write a clean copy of `ref` to `destination` (used by the sandbox, never the working tree)."""
        proc = subprocess.run(["git", "archive", "--format=tar", ref], cwd=self.path, capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise GitError(proc.stderr.decode().strip())
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
            archive.extractall(destination)
        return destination

    # --- write ---------------------------------------------------------------------------------
    def create_branch(self, name: str, base: str = "main") -> str:
        if name in PROTECTED_BRANCHES:
            raise GitError(f"'{name}' is a protected branch.")
        if not self.exists(name):
            self._git("branch", name, base)
        return name

    def checkout(self, ref: str) -> None:
        self._git("checkout", "-q", ref)

    def write_files(self, branch: str, files: dict[str, str], message: str, author: str) -> str:
        """Commit files to a feature branch. Writing to main is refused unconditionally."""
        if branch in PROTECTED_BRANCHES:
            raise GitError("Direct commits to main are not possible. Open a pull request.")
        self.checkout(branch)
        try:
            for relative, content in files.items():
                target = self._safe(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            return self._commit_all(f"{message}\n\nAI-Generated: true\nAgent: {author}", author,
                                    f"{author}@agents.example.invalid")
        finally:
            self.checkout("main")

    def merge(self, branch: str, user_name: str, message: str) -> str:
        """Merge a feature branch into main. Only reachable through a human-only code path."""
        self.checkout("main")
        self._git("merge", "--no-ff", "-q", "-m", message, branch, author=(user_name, "human@example.invalid"))
        return self.head()
