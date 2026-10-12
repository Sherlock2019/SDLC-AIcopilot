"""Runtime configuration for the Customer Portal API."""
import os

APP_VERSION = "1.3.2"
DB_PATH = os.environ.get("PORTAL_DB_PATH", "portal.db")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "3600"))
