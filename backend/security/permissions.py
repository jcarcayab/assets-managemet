from django.conf import settings
from rest_framework.permissions import IsAuthenticated

from security.mfa import SESSION_KEY, has_mfa


class MFASatisfied(IsAuthenticated):
    """Default API permission: logged in, and the session passed 2FA when the user has it (or must have it).

    Views that are part of logging in or enrolling set `mfa_exempt = True`.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if getattr(view, "mfa_exempt", False):
            return True
        if has_mfa(request.user):
            if request.session.get(SESSION_KEY):
                return True
            self.message = {"detail": "Esta sesión necesita el segundo factor.", "code": "mfa_required"}
            return False
        if settings.MFA_REQUIRED:
            self.message = {"detail": "Activa la verificación en dos pasos para continuar.", "code": "mfa_setup_required"}
            return False
        return True
