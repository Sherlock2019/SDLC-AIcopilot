"""Runtime configuration for the Customer Portal API."""
import os

APP_VERSION = "1.4.0"
DB_PATH = os.environ.get("PORTAL_DB_PATH", "portal.db")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "3600"))

# Password reset (SEC-7: tokens expire after 15 minutes).
RESET_TOKEN_TTL_SECONDS = int(os.environ.get("RESET_TOKEN_TTL_SECONDS", str(15 * 60)))
RESET_MAX_REQUESTS_PER_HOUR = int(os.environ.get("RESET_MAX_REQUESTS_PER_HOUR", "5"))
MIN_PASSWORD_LENGTH = 12
