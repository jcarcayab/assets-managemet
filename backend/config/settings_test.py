import os

# Forced, not defaulted: load_dotenv never overrides variables that are already set, so this keeps a
# developer's .env (DATABASE_URL, DEBUG=0, …) out of the test run.
os.environ["DEBUG"] = "1"
os.environ["DATABASE_URL"] = "sqlite://:memory:"

from config.settings import *  # noqa: E402,F403

# Settings that settings.py reads from the environment/.env and that tests turn on per test when needed.
MFA_REQUIRED = False
FIELD_ENCRYPTION_KEY = ""
PLAID_CLIENT_ID = PLAID_SECRET = PLAID_REDIRECT_URI = ""
PLAID_ENV = "sandbox"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {**STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}  # noqa: F405
# The throttle cache persists across tests in one process; keep login limits out of the way.
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"login": "10000/min", "mfa": "10000/min"}}  # noqa: F405
