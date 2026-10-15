"""TOTP second factor: enrollment, verification (with replay protection) and recovery codes."""

import hashlib
import hmac
import io
import secrets

import pyotp
import segno
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from security.models import RecoveryCode, TOTPDevice

ISSUER = "Patrimonio"
RECOVERY_CODES = 10
SESSION_KEY = "mfa_verified"


def confirmed_device(user) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def has_mfa(user) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def begin_setup(user) -> dict:
    """Create (or replace) an unconfirmed device and return what the authenticator app needs."""
    secret = pyotp.random_base32()
    device, _ = TOTPDevice.objects.update_or_create(user=user, defaults={"confirmed": False, "last_counter": 0})
    device.secret = secret
    device.save()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.get_username(), issuer_name=ISSUER)
    svg = io.BytesIO()
    segno.make(uri, error="m").save(svg, kind="svg", scale=5, border=2, dark="#0f172a", light="#ffffff", xmldecl=False)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": svg.getvalue().decode()}


def _matching_counter(device: TOTPDevice, code: str) -> int | None:
    """Counter of the 30 s step whose code matches, allowing one step of clock drift either way."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != 6:
        return None
    totp = pyotp.TOTP(device.secret)
    current = totp.timecode(timezone.now())
    for counter in (current - 1, current, current + 1):
        if hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None


def verify_totp(device: TOTPDevice, code: str) -> bool:
    counter = _matching_counter(device, code)
    if counter is None or counter <= device.last_counter:
        return False  # wrong, or a code that was already used
    device.last_counter = counter
    device.save(update_fields=["last_counter"])
    return True


def _hash(code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").lower()
    return hmac.new(settings.SECRET_KEY.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(user) -> list[str]:
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODES)]
    with transaction.atomic():
        RecoveryCode.objects.filter(user=user).delete()
        RecoveryCode.objects.bulk_create(RecoveryCode(user=user, code_hash=_hash(c)) for c in codes)
    return codes


def use_recovery_code(user, code: str) -> bool:
    updated = RecoveryCode.objects.filter(user=user, code_hash=_hash(code), used_at__isnull=True).update(
        used_at=timezone.now()
    )
    return updated == 1


def recovery_codes_left(user) -> int:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


def verify_second_factor(user, code: str) -> bool:
    """A TOTP code from the app, or one of the single-use recovery codes."""
    device = confirmed_device(user)
    if device is None:
        return False
    return verify_totp(device, code) or use_recovery_code(user, code)


def confirm_setup(user, code: str) -> list[str] | None:
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if device is None or not verify_totp(device, code):
        return None
    device.confirmed = True
    device.confirmed_at = timezone.now()
    device.save(update_fields=["confirmed", "confirmed_at"])
    return new_recovery_codes(user)


def disable(user) -> None:
    TOTPDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()


def session_ok(request) -> bool:
    """False when the user has 2FA but this session never passed it, or 2FA is mandatory and not set up."""
    user = request.user
    if not user.is_authenticated:
        return False
    if has_mfa(user):
        return bool(request.session.get(SESSION_KEY))
    return not settings.MFA_REQUIRED
