"""Make /admin honor 2FA: its own login form only checks the password, so send users to the app's login
(which does the second step) and refuse admin access to sessions that skipped it."""

from urllib.parse import quote

from django.contrib import admin
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from security.mfa import session_ok


def safe_next(request, default: str = "/admin/") -> str:
    target = request.GET.get("next") or default
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return default
    return target


def _login_redirect(request, extra_context=None):
    target = safe_next(request)
    if request.user.is_authenticated and request.user.is_staff and session_ok(request):
        return redirect(target)
    return redirect(f"/?next={quote(target)}")


def protect_admin_site():
    site = admin.site
    original = site.has_permission

    def has_permission(request):
        return original(request) and session_ok(request)

    site.has_permission = has_permission
    site.login = _login_redirect
