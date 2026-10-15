import os

os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")

from config.settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
