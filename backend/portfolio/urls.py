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
router.register("budget-items", views.BudgetItemViewSet)
router.register("liabilities", views.LiabilityViewSet)

urlpatterns = [
    path("positions/", views.positions_view),
    path("summary/", views.summary_view),
    path("performance/", views.performance_view),
    path("income/", views.income_view),
    path("exposure/", views.exposure_view),
    path("tax-lots/", views.tax_lots_view),
    path("allocation/", views.allocation_view),
    path("risk/", views.risk_view),
    path("equity/", views.equity_summary_view),
    path("budget/", views.budget_view),
    path("debts/", views.debts_view),
    path("monte-carlo/", views.monte_carlo_view),
    path("prices/refresh/", views.refresh_prices_view),
    path("settings/", views.settings_view),
    path("choices/", views.choices_view),
    path("", include(router.urls)),
]
