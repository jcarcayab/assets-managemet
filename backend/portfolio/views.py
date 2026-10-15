from django.contrib.auth import authenticate, login, logout
from django.db.models.deletion import ProtectedError
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from portfolio.models import (
    Account,
    AccountType,
    AllocationTarget,
    Asset,
    AssetClass,
    CashFlow,
    EquityGrant,
    PriceSource,
    Snapshot,
    Transaction,
    TransactionKind,
    UserSettings,
)
from portfolio.serializers import (
    AccountSerializer,
    AllocationTargetSerializer,
    AssetSerializer,
    CashFlowSerializer,
    EquityGrantSerializer,
    PositionSerializer,
    SnapshotSerializer,
    TransactionSerializer,
    UserSettingsSerializer,
)
from portfolio.services.positions import compute_positions, compute_summary
from portfolio.services.prices import refresh_prices
from portfolio.services.snapshots import take_snapshot

# -- auth -------------------------------------------------------------------------------------------


def _me(user):
    return {"id": user.id, "username": user.username}


class LoginThrottle(ScopedRateThrottle):
    scope = "login"


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def session(request):
    """Sets the CSRF cookie and reports whether the user is logged in."""
    user = request.user if request.user.is_authenticated else None
    return Response({"user": _me(user) if user else None})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login_view(request):
    user = authenticate(request, username=request.data.get("username"), password=request.data.get("password"))
    if user is None:
        return Response({"detail": "Usuario o contraseña incorrectos."}, status=status.HTTP_400_BAD_REQUEST)
    login(request, user)
    return Response({"user": _me(user)})


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


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
        except ProtectedError:
            return Response(
                {"detail": "No se puede borrar: tiene transacciones asociadas."}, status=status.HTTP_409_CONFLICT
            )


class AccountViewSet(OwnedViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer


class AssetViewSet(OwnedViewSet):
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    filter_params = ("asset_class",)


class TransactionViewSet(OwnedViewSet):
    queryset = Transaction.objects.select_related("account", "asset")
    serializer_class = TransactionSerializer
    owner_path = "account__owner"
    filter_params = ("account", "asset", "kind")


class CashFlowViewSet(OwnedViewSet):
    queryset = CashFlow.objects.select_related("account")
    serializer_class = CashFlowSerializer
    owner_path = "account__owner"
    filter_params = ("account",)


class AllocationTargetViewSet(OwnedViewSet):
    queryset = AllocationTarget.objects.all()
    serializer_class = AllocationTargetSerializer
    owner_path = "account__owner"
    filter_params = ("account",)


class EquityGrantViewSet(OwnedViewSet):
    queryset = EquityGrant.objects.select_related("account")
    serializer_class = EquityGrantSerializer
    owner_path = "account__owner"


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
    return Response(refresh_prices(Asset.objects.filter(owner=request.user)))


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
        }
    )
