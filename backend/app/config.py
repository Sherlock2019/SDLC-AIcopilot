"""Settings. Everything has a default so the lab runs with no .env file and no API keys."""
import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("LAB_ROOT") or Path(__file__).resolve().parents[2])


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.mock_ai = _bool("MOCK_AI", True)
        self.ai_provider = (os.environ.get("AI_PROVIDER") or "mock").lower()
        self.ai_model = os.environ.get("AI_MODEL", "")
        self.data_dir = Path(os.environ.get("LAB_DATA_DIR") or REPO_ROOT / "backend" / "data")
        self.database_url = os.environ.get("DATABASE_URL") or f"sqlite:///{self.data_dir / 'lab.db'}"

        self.github_enabled = _bool("GITHUB_ENABLED", False)
        self.github_token = os.environ.get("GITHUB_TOKEN", "")
        self.github_repo = os.environ.get("GITHUB_REPO", "")
        self.github_api = os.environ.get("GITHUB_API_URL", "https://api.github.com")

        # Real-provider pricing is configuration, not code: prices change, the lab should not guess.
        self.price_in_per_mtok = float(os.environ.get("AI_PRICE_IN_PER_MTOK") or 0)
        self.price_out_per_mtok = float(os.environ.get("AI_PRICE_OUT_PER_MTOK") or 0)

        self.context_dir = REPO_ROOT / "context_repo"
        self.sample_app_dir = REPO_ROOT / "sample_app"
        self.policies_dir = REPO_ROOT / "policies"
        self.frontend_dist = Path(os.environ.get("FRONTEND_DIST") or REPO_ROOT / "frontend" / "dist")
        self.cors_origins = [o for o in (os.environ.get("CORS_ORIGINS") or "*").split(",") if o]

    @property
    def effective_provider(self) -> str:
        return "mock" if self.mock_ai else self.ai_provider

    @property
    def github_mode(self) -> str:
        if self.github_enabled and self.github_token and self.github_repo:
            return "github-sandbox"
        return "local-mock-git"


settings = Settings()
