"""Runtime settings, read from environment variables or a local `.env` file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, optional quotes, existing env wins."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    db_path: Path
    cache_days: int
    sharesight_client_id: str | None = None
    sharesight_client_secret: str | None = None

    @property
    def sharesight_configured(self) -> bool:
        return bool(self.sharesight_client_id and self.sharesight_client_secret)


class ConfigError(RuntimeError):
    pass


def get_settings() -> Settings:
    _load_dotenv(PROJECT_ROOT / ".env")
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent or "@" not in user_agent or "example.com" in user_agent:
        raise ConfigError(
            "SEC_USER_AGENT is not set. Copy .env.example to .env and put your "
            "name/app and a contact email in it (SEC requires this)."
        )
    db = Path(os.environ.get("STOCK_METRICS_DB", "data/stock_metrics.db"))
    if not db.is_absolute():
        db = PROJECT_ROOT / db
    return Settings(
        sec_user_agent=user_agent,
        db_path=db,
        cache_days=int(os.environ.get("STOCK_METRICS_CACHE_DAYS", "7")),
        sharesight_client_id=os.environ.get("SHARESIGHT_CLIENT_ID", "").strip() or None,
        sharesight_client_secret=os.environ.get("SHARESIGHT_CLIENT_SECRET", "").strip() or None,
    )
