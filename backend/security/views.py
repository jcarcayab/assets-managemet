from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core import signing
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from security import mfa

MFA_TOKEN_SALT = "security.mfa-login"
MFA_TOKEN_MAX_AGE = 300  # seconds to type the code after the password step


class LoginThrottle(ScopedRateThrottle):
    scope = "login"


class MFAThrottle(ScopedRateThrottle):
    scope = "mfa"


def _me(user):
    return {"id": user.id, "username": user.username, "mfa_enabled": mfa.has_mfa(user)}


def _session_payload(request):
    user = request.user if request.user.is_authenticated else None
    if user and mfa.has_mfa(user) and not request.session.get(mfa.SESSION_KEY):
        # A session from before 2FA was enabled elsewhere: make the user log in again.
        logout(request)
        user = None
    return {
        "user": _me(user) if user else None,
        "mfa_setup_required": bool(user and settings.MFA_REQUIRED and not mfa.has_mfa(user)),
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def session(request):
    """Sets the CSRF cookie and reports who is logged in."""
    return Response(_session_payload(request))


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login_view(request):
    user = authenticate(request, username=request.data.get("username"), password=request.data.get("password"))
    if user is None:
        return Response({"detail": "Usuario o contraseña incorrectos."}, status=status.HTTP_400_BAD_REQUEST)
    if mfa.has_mfa(user):
        # Password is right but no session yet: the client comes back with a code and this short-lived token.
        token = signing.dumps({"uid": user.pk}, salt=MFA_TOKEN_SALT)
        return Response({"mfa_required": True, "mfa_token": token})
    login(request, user)
    return Response(_session_payload(request))


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([MFAThrottle])
def login_mfa_view(request):
    User = get_user_model()
    try:
        data = signing.loads(request.data.get("mfa_token", ""), salt=MFA_TOKEN_SALT, max_age=MFA_TOKEN_MAX_AGE)
        user = User.objects.get(pk=data["uid"], is_active=True)
    except (signing.BadSignature, User.DoesNotExist, KeyError, TypeError):
        return Response({"detail": "El login expiró. Vuelve a escribir tu contraseña."}, status=status.HTTP_400_BAD_REQUEST)
    if not mfa.verify_second_factor(user, str(request.data.get("code", ""))):
        return Response({"detail": "Código incorrecto."}, status=status.HTTP_400_BAD_REQUEST)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[mfa.SESSION_KEY] = True
    return Response({**_session_payload(request), "recovery_codes_left": mfa.recovery_codes_left(user)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    mfa_exempt = True

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatusView(APIView):
    mfa_exempt = True

    def get(self, request):
        device = mfa.confirmed_device(request.user)
        return Response(
            {
                "enabled": device is not None,
                "confirmed_at": device.confirmed_at if device else None,
                "recovery_codes_left": mfa.recovery_codes_left(request.user) if device else 0,
                "required": settings.MFA_REQUIRED,
            }
        )


class SetupView(APIView):
    """Start enrollment. Exempt so users forced to enroll can reach it; refuses once 2FA is active."""

    mfa_exempt = True
    throttle_classes = [MFAThrottle]

    def post(self, request):
        if mfa.has_mfa(request.user):
            return Response({"detail": "La verificación en dos pasos ya está activa."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(mfa.begin_setup(request.user))


class ConfirmView(APIView):
    mfa_exempt = True
    throttle_classes = [MFAThrottle]

    def post(self, request):
        if mfa.has_mfa(request.user):
            return Response({"detail": "La verificación en dos pasos ya está activa."}, status=status.HTTP_400_BAD_REQUEST)
        codes = mfa.confirm_setup(request.user, str(request.data.get("code", "")))
        if codes is None:
            return Response(
                {"detail": "Código incorrecto. Revisa que la hora del teléfono sea automática."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.session[mfa.SESSION_KEY] = True  # this session just proved the second factor
        return Response({"recovery_codes": codes})


class DisableView(APIView):
    throttle_classes = [MFAThrottle]

    def post(self, request):
        if settings.MFA_REQUIRED:
            return Response({"detail": "La verificación en dos pasos es obligatoria."}, status=status.HTTP_400_BAD_REQUEST)
        if not request.user.check_password(request.data.get("password", "")):
            return Response({"detail": "Contraseña incorrecta."}, status=status.HTTP_400_BAD_REQUEST)
        if not mfa.verify_second_factor(request.user, str(request.data.get("code", ""))):
            return Response({"detail": "Código incorrecto."}, status=status.HTTP_400_BAD_REQUEST)
        mfa.disable(request.user)
        request.session.pop(mfa.SESSION_KEY, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RecoveryCodesView(APIView):
    """Replace all recovery codes (requires a current code from the app)."""

    throttle_classes = [MFAThrottle]

    def post(self, request):
        device = mfa.confirmed_device(request.user)
        if device is None or not mfa.verify_totp(device, str(request.data.get("code", ""))):
            return Response({"detail": "Código incorrecto."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"recovery_codes": mfa.new_recovery_codes(request.user)})
