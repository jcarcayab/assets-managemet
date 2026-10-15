import datetime as dt
from unittest import mock

import pyotp
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from security.crypto import decrypt, encrypt
from security.models import TOTPDevice

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-test-password"
T0 = timezone.now()


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("alice", password=PASSWORD, is_staff=True, is_superuser=True)


def at(steps: int):
    """Pretend the clock is `steps` 30-second windows after T0."""
    return mock.patch("security.mfa.timezone.now", return_value=T0 + dt.timedelta(seconds=30 * steps))


def code(secret: str, steps: int) -> str:
    return pyotp.TOTP(secret).at(T0 + dt.timedelta(seconds=30 * steps))


def enroll(client: APIClient) -> tuple[str, list[str]]:
    with at(0):
        secret = client.post("/api/auth/2fa/setup/").json()["secret"]
        resp = client.post("/api/auth/2fa/confirm/", {"code": code(secret, 0)}, format="json")
    return secret, resp.json()["recovery_codes"]


def password_step(client: APIClient) -> str:
    resp = client.post("/api/auth/login/", {"username": "alice", "password": PASSWORD}, format="json")
    assert resp.json()["mfa_required"] is True
    return resp.json()["mfa_token"]


def second_step(client: APIClient, value: str, token: str | None = None):
    token = token or password_step(client)
    return client.post("/api/auth/login/mfa/", {"mfa_token": token, "code": value}, format="json")


@pytest.fixture
def enrolled(user):
    client = APIClient()
    client.login(username="alice", password=PASSWORD)
    secret, codes = enroll(client)
    client.post("/api/auth/logout/")
    return secret, codes


def test_secrets_are_encrypted_at_rest(user):
    assert decrypt(encrypt("hello")) == "hello"
    client = APIClient()
    client.login(username="alice", password=PASSWORD)
    with at(0):
        setup = client.post("/api/auth/2fa/setup/").json()
    device = TOTPDevice.objects.get(user=user)
    assert setup["secret"] not in device.secret_encrypted
    assert setup["qr_svg"].startswith("<svg")
    assert setup["otpauth_uri"].startswith("otpauth://totp/Patrimonio:alice")


def test_enrollment_requires_a_valid_code(user):
    client = APIClient()
    client.login(username="alice", password=PASSWORD)
    with at(0):
        client.post("/api/auth/2fa/setup/")
        assert client.post("/api/auth/2fa/confirm/", {"code": "000000"}, format="json").status_code == 400
    _, codes = enroll(client)
    assert len(codes) == 10
    assert client.get("/api/auth/2fa/").json()["enabled"] is True


def test_login_needs_the_second_step(enrolled):
    secret, _ = enrolled
    client = APIClient()
    token = password_step(client)
    assert client.get("/api/summary/").status_code == 403  # the password alone opens no session
    with at(1):
        assert second_step(client, "123456", token).status_code == 400
        ok = second_step(client, code(secret, 1), token)
    assert ok.status_code == 200
    assert ok.json()["user"]["mfa_enabled"] is True
    assert client.get("/api/summary/").status_code == 200


def test_a_code_cannot_be_reused(enrolled):
    secret, _ = enrolled
    with at(1):
        assert second_step(APIClient(), code(secret, 1)).status_code == 200
        assert second_step(APIClient(), code(secret, 1)).status_code == 400


def test_recovery_code_works_once(enrolled):
    _, codes = enrolled
    assert second_step(APIClient(), codes[0].upper()).status_code == 200
    assert second_step(APIClient(), codes[0]).status_code == 400


def test_mfa_token_expires(enrolled):
    secret, _ = enrolled
    client = APIClient()
    token = password_step(client)
    later = timezone.now().timestamp() + 600
    with at(1), mock.patch("django.core.signing.time.time", return_value=later):
        assert second_step(client, code(secret, 1), token).status_code == 400


def test_old_session_without_second_factor_is_rejected(user, enrolled):
    client = APIClient()
    client.force_login(user)  # e.g. a session opened before 2FA was enabled
    resp = client.get("/api/summary/")
    assert resp.status_code == 403
    assert resp.json()["code"] == "mfa_required"
    assert client.get("/api/auth/session/").json()["user"] is None


def test_mandatory_2fa_forces_enrollment(user, settings):
    settings.MFA_REQUIRED = True
    client = APIClient()
    client.login(username="alice", password=PASSWORD)
    assert client.get("/api/auth/session/").json()["mfa_setup_required"] is True
    blocked = client.get("/api/summary/")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "mfa_setup_required"
    enroll(client)
    assert client.get("/api/summary/").status_code == 200
    assert client.post("/api/auth/2fa/disable/", {"password": PASSWORD}, format="json").status_code == 400


def test_disable_needs_password_and_code(user, enrolled):
    secret, _ = enrolled
    client = APIClient()
    with at(1):
        second_step(client, code(secret, 1))
    with at(2):
        wrong = {"password": "wrong", "code": code(secret, 2)}
        assert client.post("/api/auth/2fa/disable/", wrong, format="json").status_code == 400
        right = {"password": PASSWORD, "code": code(secret, 2)}
        assert client.post("/api/auth/2fa/disable/", right, format="json").status_code == 204
    assert not TOTPDevice.objects.filter(user=user).exists()


def test_admin_requires_the_second_factor(user, enrolled):
    secret, _ = enrolled
    client = APIClient()
    client.force_login(user)
    resp = client.get("/admin/")
    assert resp.status_code == 302  # a session without 2FA is sent to log in again
    login_page = client.get(resp.url)
    assert login_page.status_code == 302
    assert login_page.url.startswith("/?next=")

    client = APIClient()
    with at(1):
        second_step(client, code(secret, 1))
    assert client.get("/admin/").status_code == 200


def test_admin_login_next_cannot_redirect_offsite(user):
    client = APIClient()
    client.force_login(user)
    resp = client.get("/admin/login/?next=https://evil.example.com/")
    assert resp.status_code == 302
    assert resp.url == "/admin/"
