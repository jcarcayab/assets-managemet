from django.conf import settings
from django.db import models

from security.crypto import decrypt, encrypt


class TOTPDevice(models.Model):
    """Authenticator-app second factor. Unconfirmed until the user proves the app produces valid codes."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp_device")
    secret_encrypted = models.TextField()
    confirmed = models.BooleanField(default=False)
    last_counter = models.BigIntegerField(default=0, help_text="Último paso de 30 s aceptado (evita reutilizar un código).")
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    @property
    def secret(self) -> str:
        return decrypt(self.secret_encrypted)

    @secret.setter
    def secret(self, value: str) -> None:
        self.secret_encrypted = encrypt(value)


class RecoveryCode(models.Model):
    """Single-use backup code, stored as an HMAC (codes are random and high-entropy, so no slow hash needed)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
