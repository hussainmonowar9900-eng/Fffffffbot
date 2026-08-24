"""Configuration management — reads from environment variables with safe validation."""

import os
import sys
import logging

logger = logging.getLogger(__name__)

# ── Required environment variables ──────────────────────────────────────────
REQUIRED_VARS = ["BOT_TOKEN", "ADMIN_ID"]

# ── Optional environment variables (with defaults) ──────────────────────────
OPTIONAL_DEFAULTS = {
    "API_URL": "",
    "API_KEY": "",
    "MASTER_KEY": "",
    "PAYMENT_API_KEY": "",
    "PAYMENT_SECRET": "",
    "UPI_ID": "",
    "SUPPORT_USERNAME": "SupportTeam",
    "DB_PATH": "reseller_bot.db",
    "API_TIMEOUT": "30",
    "WALLET_MIN_ADD": "10",
    "WALLET_MAX_ADD": "10000",
}

# Never log or expose these
SECRET_VARS = {"BOT_TOKEN", "API_KEY", "MASTER_KEY", "PAYMENT_SECRET", "PAYMENT_API_KEY"}


class ConfigError(Exception):
    """Raised when a required environment variable is missing or invalid."""


class Config:
    """Holds all validated configuration values."""

    def __init__(self):
        self.bot_token = ""
        self.admin_ids: set[int] = set()
        self.api_url = ""
        self.api_key = ""
        self.master_key = ""
        self.payment_api_key = ""
        self.payment_secret = ""
        self.upi_id = ""
        self.support_username = ""
        self.db_path = ""
        self.api_timeout = 30
        self.wallet_min_add = 10
        self.wallet_max_add = 10000

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def _parse_admin_ids(raw: str) -> set[int]:
    """Parse ADMIN_ID which may be a single ID or comma-separated list."""
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            raise ConfigError(
                f"Invalid ADMIN_ID value: '{part}'. "
                "Must be a numeric Telegram user ID or comma-separated list."
            )
    if not ids:
        raise ConfigError("ADMIN_ID is set but contains no valid IDs.")
    return ids


def load_config() -> Config:
    """Load and validate configuration from environment variables.

    Raises ConfigError with a clear message if a required var is missing
    or invalid.  Never prints secret values.
    """
    cfg = Config()

    # ── Required ────────────────────────────────────────────────────────────
    missing: list[str] = []
    for var in REQUIRED_VARS:
        val = os.environ.get(var, "").strip()
        if not val:
            missing.append(var)

    if missing:
        lines = ["CONFIGURATION ERROR:"]
        for var in missing:
            lines.append(f"Missing environment variable: {var}")
        print("\n".join(lines), file=sys.stderr)
        raise ConfigError("; ".join(f"Missing environment variable: {v}" for v in missing))

    cfg.bot_token = os.environ["BOT_TOKEN"].strip()

    raw_admin = os.environ["ADMIN_ID"].strip()
    cfg.admin_ids = _parse_admin_ids(raw_admin)

    # ── Optional ────────────────────────────────────────────────────────────
    for key, default in OPTIONAL_DEFAULTS.items():
        val = os.environ.get(key, default).strip()
        setattr(cfg, key.lower(), val)

    # Type conversions
    try:
        cfg.api_timeout = int(cfg.api_timeout)
    except (ValueError, TypeError):
        cfg.api_timeout = 30

    try:
        cfg.wallet_min_add = int(cfg.wallet_min_add)
    except (ValueError, TypeError):
        cfg.wallet_min_add = 10

    try:
        cfg.wallet_max_add = int(cfg.wallet_max_add)
    except (ValueError, TypeError):
        cfg.wallet_max_add = 10000

    return cfg


def safe_log_value(var_name: str, value: str) -> str:
    """Return a safe representation for logging — masks secrets."""
    if var_name in SECRET_VARS:
        return "***" if value else "(not set)"
    if not value:
        return "(not set)"
    # Truncate long values
    if len(value) > 40:
        return value[:20] + "…" + f"({len(value)} chars)"
    return value
