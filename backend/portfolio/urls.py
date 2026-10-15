from django.urls import include, path
from rest_framework.routers import DefaultRouter

from portfolio import views

router = DefaultRouter(trailing_slash=True)
router.register("accounts", views.AccountViewSet)
router.register("assets", views.AssetViewSet)
router.register("transactions", views.TransactionViewSet)
router.register("cash-flows", views.CashFlowViewSet)
router.register("targets", views.AllocationTargetViewSet)
router.register("equity-grants", views.EquityGrantViewSet)
router.register("snapshots", views.SnapshotViewSet)

urlpatterns = [
    path("auth/session/", views.session),
    path("auth/login/", views.login_view),
    path("auth/logout/", views.logout_view),
    path("positions/", views.positions_view),
    path("summary/", views.summary_view),
    path("performance/", views.performance_view),
    path("income/", views.income_view),
    path("exposure/", views.exposure_view),
    path("prices/refresh/", views.refresh_prices_view),
    path("settings/", views.settings_view),
    path("choices/", views.choices_view),
    path("", include(router.urls)),
]
