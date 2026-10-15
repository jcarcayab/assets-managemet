from django.urls import path

from security import views

urlpatterns = [
    path("session/", views.session),
    path("login/", views.login_view),
    path("login/mfa/", views.login_mfa_view),
    path("logout/", views.LogoutView.as_view()),
    path("2fa/", views.StatusView.as_view()),
    path("2fa/setup/", views.SetupView.as_view()),
    path("2fa/confirm/", views.ConfirmView.as_view()),
    path("2fa/disable/", views.DisableView.as_view()),
    path("2fa/recovery-codes/", views.RecoveryCodesView.as_view()),
]
