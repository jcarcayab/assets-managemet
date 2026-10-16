from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework import status, viewsets
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from portfolio.models import (
    Account,
    AccountType,
    AllocationTarget,
    Asset,
    AssetClass,
    BudgetItem,
    BudgetKind,
    CashFlow,
    CashFlowKind,
    EquityExercise,
    EquityGrant,
    ExposureCategory,
    Frequency,
    GrantType,
    Liability,
    LiabilityKind,
    PriceSource,
    Snapshot,
    TaxTreatment,
    Transaction,
    TransactionKind,
    UserSettings,
)
from portfolio.serializers import (
    AccountSerializer,
    AllocationTargetSerializer,
    AssetSerializer,
    BudgetItemSerializer,
    LiabilitySerializer,
    CashFlowSerializer,
    EquityExerciseSerializer,
    EquityGrantSerializer,
    PositionSerializer,
    SnapshotSerializer,
    TransactionSerializer,
    UserSettingsSerializer,
)
from portfolio.services.allocation import compute_allocation
from portfolio.services.equity import compute_equity
from portfolio.services.exposure import compute_exposure
from portfolio.services.risk import compute_risk
from portfolio.services.taxes import compute_tax_lots
from portfolio.services.history import BENCHMARKS, update_history
from portfolio.services.performance import compute_income, compute_performance
from portfolio.services.planning import compute_budget, compute_debts, contribution_limits, monte_carlo
from portfolio.services.positions import compute_positions, compute_summary
from portfolio.services.prices import refresh_prices
from portfolio.services.snapshots import take_snapshot

# -- CRUD -------------------------------------------------------------------------------------------


class OwnedViewSet(viewsets.ModelViewSet):
    """Scopes every query to the logged-in user. `owner_path` is the lookup from the model to the user."""

    owner_path = "owner"
    filter_params: tuple[str, ...] = ()

    def get_queryset(self):
        qs = self.queryset.filter(**{self.owner_path: self.request.user})
        for name in self.filter_params:
            value = self.request.query_params.get(name)
            if value:
                qs = qs.filter(**{name: value})
        return qs

    def perform_create(self, serializer):
        if self.owner_path == "owner":
            serializer.save(owner=self.request.user)
        else:
            serializer.save()

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except (ProtectedError, RestrictedError):
            return Response(
                {"detail": "No se puede borrar: tiene transacciones asociadas."}, status=status.HTTP_409_CONFLICT
            )


class OptionalPagination(PageNumberPagination):
    """Pages only when the client asks for one (`?page=`); without it the full list comes back as before."""

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500

    def paginate_queryset(self, queryset, request, view=None):
        if self.page_query_param not in request.query_params:
            return None
        return super().paginate_queryset(queryset, request, view)


class AccountViewSet(OwnedViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer


class AssetViewSet(OwnedViewSet):
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    filter_params = ("asset_class",)


class TransactionViewSet(OwnedViewSet):
    queryset = Transaction.objects.select_related("account", "asset", "to_account")
    serializer_class = TransactionSerializer
    pagination_class = OptionalPagination
    owner_path = "account__owner"
    filter_params = ("account", "asset", "kind")


class CashFlowViewSet(OwnedViewSet):
    queryset = CashFlow.objects.select_related("account")
    serializer_class = CashFlowSerializer
    pagination_class = OptionalPagination
    owner_path = "account__owner"
    filter_params = ("account", "kind")


class AllocationTargetViewSet(OwnedViewSet):
    queryset = AllocationTarget.objects.all()
    serializer_class = AllocationTargetSerializer
    owner_path = "account__owner"
    filter_params = ("account",)


class EquityGrantViewSet(OwnedViewSet):
    queryset = EquityGrant.objects.select_related("account")
    serializer_class = EquityGrantSerializer
    owner_path = "account__owner"


class EquityExerciseViewSet(OwnedViewSet):
    queryset = EquityExercise.objects.select_related("grant")
    serializer_class = EquityExerciseSerializer
    owner_path = "grant__account__owner"
    filter_params = ("grant",)


class BudgetItemViewSet(OwnedViewSet):
    queryset = BudgetItem.objects.all()
    serializer_class = BudgetItemSerializer


class LiabilityViewSet(OwnedViewSet):
    queryset = Liability.objects.all()
    serializer_class = LiabilitySerializer


class SnapshotViewSet(OwnedViewSet):
    queryset = Snapshot.objects.all()
    serializer_class = SnapshotSerializer
    http_method_names = ["get", "post", "delete"]

    def create(self, request, *args, **kwargs):
        """POST /snapshots/ stores today's totals (body may include `notes`)."""
        snap = take_snapshot(request.user, notes=request.data.get("notes", ""))
        return Response(SnapshotSerializer(snap).data, status=status.HTTP_201_CREATED)


# -- computed ---------------------------------------------------------------------------------------


@api_view(["GET"])
def positions_view(request):
    include_closed = request.query_params.get("closed") == "1"
    return Response(PositionSerializer(compute_positions(request.user, include_closed), many=True).data)


@api_view(["GET"])
def summary_view(request):
    return Response(compute_summary(request.user))


@api_view(["POST"])
def refresh_prices_view(request):
    result = refresh_prices(Asset.objects.filter(owner=request.user))
    result["history"] = update_history(request.user)
    return Response(result)


@api_view(["GET"])
def performance_view(request):
    account = request.query_params.get("account")
    if account and not Account.objects.filter(owner=request.user, id=account).exists():
        return Response({"detail": "Cuenta no encontrada."}, status=status.HTTP_404_NOT_FOUND)
    benchmark = request.query_params.get("benchmark") or None
    if benchmark and benchmark not in BENCHMARKS:
        return Response({"detail": "Benchmark no soportado."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(compute_performance(request.user, int(account) if account else None, benchmark))


@api_view(["GET"])
def income_view(request):
    return Response(compute_income(request.user))


@api_view(["GET"])
def exposure_view(request):
    return Response(compute_exposure(request.user))


@api_view(["GET"])
def tax_lots_view(request):
    return Response(compute_tax_lots(request.user))


@api_view(["GET"])
def allocation_view(request):
    return Response(compute_allocation(request.user))


@api_view(["GET"])
def risk_view(request):
    return Response(compute_risk(request.user, request.query_params.get("custom")))


@api_view(["GET"])
def equity_summary_view(request):
    return Response(compute_equity(request.user))


@api_view(["GET"])
def budget_view(request):
    return Response(compute_budget(request.user))


@api_view(["GET"])
def debts_view(request):
    return Response(compute_debts(request.user))


@api_view(["GET"])
def monte_carlo_view(request):
    return Response(monte_carlo(request.user, base=request.query_params.get("base", "net_worth_ex_private")))


@api_view(["GET"])
def contribution_limits_view(request):
    return Response(contribution_limits(request.user))


@api_view(["GET", "PATCH"])
def settings_view(request):
    obj = UserSettings.for_user(request.user)
    if request.method == "GET":
        return Response(UserSettingsSerializer(obj).data)
    ser = UserSettingsSerializer(obj, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)


@api_view(["GET"])
def choices_view(request):
    """Enum values for building forms in the frontend."""

    def as_list(enum):
        return [{"value": v, "label": label} for v, label in enum.choices]

    return Response(
        {
            "account_types": as_list(AccountType),
            "asset_classes": as_list(AssetClass),
            "price_sources": as_list(PriceSource),
            "transaction_kinds": as_list(TransactionKind),
            "cash_flow_kinds": as_list(CashFlowKind),
            "tax_treatments": as_list(TaxTreatment),
            "exposure_categories": as_list(ExposureCategory),
            "grant_types": as_list(GrantType),
            "budget_kinds": as_list(BudgetKind),
            "frequencies": as_list(Frequency),
            "liability_kinds": as_list(LiabilityKind),
            "benchmarks": [{"value": k, "label": v} for k, v in BENCHMARKS.items()],
        }
    )
