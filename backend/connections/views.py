from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from connections.exchange_data import ExchangeError
from connections.exchange_sync import client_for as exchange_client_for
from connections.exchange_sync import sync_exchange
from connections.models import ExchangeConnection, ExchangeProvider, PlaidAccount, PlaidItem
from connections.plaid import LINK_PRODUCTS, PlaidError, configured, get_client
from connections.sync import link_item, sync_item
from portfolio.models import Account, Liability


class PlaidThrottle(UserRateThrottle):
    rate = "30/hour"  # every call costs a Plaid request


class PlaidAccountSerializer(serializers.ModelSerializer):
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.all(), allow_null=True, required=False)
    account_name = serializers.CharField(source="account.name", read_only=True, default=None)
    liability = serializers.PrimaryKeyRelatedField(queryset=Liability.objects.all(), allow_null=True, required=False)
    liability_name = serializers.CharField(source="liability.name", read_only=True, default=None)

    class Meta:
        model = PlaidAccount
        fields = [
            "id", "name", "official_name", "mask", "type", "subtype", "current_balance", "account", "account_name",
            "liability", "liability_name", "enabled",
        ]
        read_only_fields = ["name", "official_name", "mask", "type", "subtype", "current_balance"]

    def validate_account(self, value):
        if value is not None and value.owner_id != self.context["request"].user.id:
            raise serializers.ValidationError("Cuenta no encontrada.")
        return value

    def validate_liability(self, value):
        if value is not None and value.owner_id != self.context["request"].user.id:
            raise serializers.ValidationError("Deuda no encontrada.")
        return value


class PlaidItemSerializer(serializers.ModelSerializer):
    accounts = PlaidAccountSerializer(many=True, read_only=True)

    class Meta:
        model = PlaidItem
        fields = ["id", "institution_name", "created_at", "last_synced_at", "last_error", "needs_reauth", "accounts"]


def plaid_error(exc: PlaidError) -> Response:
    return Response({"detail": exc.message or exc.code, "code": exc.code}, status=status.HTTP_502_BAD_GATEWAY)


class PlaidAPIView(APIView):
    """Views that talk to Plaid; they answer 503 until PLAID_CLIENT_ID / PLAID_SECRET are configured."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.client = get_client() if configured() else None

    def not_configured(self):
        return Response(
            {"detail": "Plaid no está configurado (PLAID_CLIENT_ID / PLAID_SECRET).", "code": "plaid_not_configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    def item(self, request, pk) -> PlaidItem:
        return get_object_or_404(PlaidItem, pk=pk, owner=request.user)


class StatusView(APIView):
    def get(self, request):
        return Response({"configured": configured(), "env": settings.PLAID_ENV})


class LinkTokenView(PlaidAPIView):
    """Token for Plaid Link. With `item`, opens Link in update mode to re-authenticate that connection."""

    throttle_classes = [PlaidThrottle]

    def post(self, request):
        if not self.client:
            return self.not_configured()
        item_id = request.data.get("item")
        access_token = self.item(request, item_id).access_token if item_id else None
        kind = request.data.get("kind", "investments")
        if kind not in LINK_PRODUCTS:
            return Response({"detail": f"Tipo de conexión desconocido: {kind}"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response({"link_token": self.client.create_link_token(request.user.id, access_token, kind=kind)})
        except PlaidError as exc:
            return plaid_error(exc)


class ExchangeView(PlaidAPIView):
    """Called after Link's onSuccess: stores the connection (token encrypted) and lists its accounts."""

    throttle_classes = [PlaidThrottle]

    def post(self, request):
        if not self.client:
            return self.not_configured()
        public_token = request.data.get("public_token")
        if not public_token:
            return Response({"detail": "Falta public_token."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            item = link_item(request.user, public_token, self.client)
        except PlaidError as exc:
            return plaid_error(exc)
        return Response(PlaidItemSerializer(item, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ItemListView(APIView):
    def get(self, request):
        items = PlaidItem.objects.filter(owner=request.user).prefetch_related("accounts__account", "accounts__liability")
        return Response(PlaidItemSerializer(items, many=True, context={"request": request}).data)


class ItemView(PlaidAPIView):
    def delete(self, request, pk):
        """Disconnect: revoke the token at Plaid and forget it. Imported accounts and history stay."""
        item = self.item(request, pk)
        if self.client:
            try:
                self.client.remove_item(item.access_token)
            except PlaidError as exc:
                if exc.code != "ITEM_NOT_FOUND":
                    return plaid_error(exc)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SyncView(PlaidAPIView):
    throttle_classes = [PlaidThrottle]

    def post(self, request, pk):
        if not self.client:
            return self.not_configured()
        report = sync_item(self.item(request, pk), self.client)
        return Response(report, status=status.HTTP_502_BAD_GATEWAY if report["error"] else status.HTTP_200_OK)


class ExchangeSerializer(serializers.ModelSerializer):
    provider_label = serializers.CharField(source="get_provider_display", read_only=True)
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.all(), allow_null=True, required=False)
    account_name = serializers.CharField(source="account.name", read_only=True, default=None)

    class Meta:
        model = ExchangeConnection
        fields = [
            "id", "provider", "provider_label", "label", "key_hint", "account", "account_name", "created_at",
            "last_synced_at", "last_error",
        ]
        read_only_fields = ["provider", "key_hint", "created_at", "last_synced_at", "last_error"]

    def validate_account(self, value):
        if value is not None and value.owner_id != self.context["request"].user.id:
            raise serializers.ValidationError("Cuenta no encontrada.")
        return value


class ExchangeConnectionListView(APIView):
    throttle_classes = [PlaidThrottle]

    def get(self, request):
        conns = ExchangeConnection.objects.filter(owner=request.user).select_related("account")
        return Response(ExchangeSerializer(conns, many=True, context={"request": request}).data)

    def post(self, request):
        """Store read-only credentials after checking them against the exchange. They're never returned."""
        provider = request.data.get("provider")
        key, secret = (request.data.get("api_key") or "").strip(), (request.data.get("api_secret") or "").strip()
        if provider not in ExchangeProvider.values or not key or not secret:
            return Response({"detail": "Indica exchange, API key y secreto."}, status=status.HTTP_400_BAD_REQUEST)
        conn = ExchangeConnection(owner=request.user, provider=provider, label=(request.data.get("label") or "")[:60])
        conn.set_credentials(key, secret)
        try:
            exchange_client_for(conn).check()
        except ExchangeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        conn.save()
        return Response(ExchangeSerializer(conn, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ExchangeConnectionView(APIView):
    def conn(self, request, pk) -> ExchangeConnection:
        return get_object_or_404(ExchangeConnection, pk=pk, owner=request.user)

    def patch(self, request, pk):
        ser = ExchangeSerializer(self.conn(request, pk), data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def delete(self, request, pk):
        """Forget the credentials. The account and its history stay."""
        self.conn(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExchangeConnectionSyncView(APIView):
    throttle_classes = [PlaidThrottle]

    def post(self, request, pk):
        conn = get_object_or_404(ExchangeConnection, pk=pk, owner=request.user)
        report = sync_exchange(conn)
        return Response(report, status=status.HTTP_502_BAD_GATEWAY if report["error"] else status.HTTP_200_OK)


class AccountView(APIView):
    """Choose which portfolio account a Plaid account feeds, or switch it off."""

    def patch(self, request, pk):
        pa = get_object_or_404(PlaidAccount, pk=pk, item__owner=request.user)
        ser = PlaidAccountSerializer(pa, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)
