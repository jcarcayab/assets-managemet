from decimal import Decimal

from rest_framework import serializers

from portfolio.models import (
    Account,
    AllocationTarget,
    Asset,
    CashFlow,
    EquityGrant,
    Snapshot,
    Transaction,
    UserSettings,
)


class OwnedQuerysetField(serializers.PrimaryKeyRelatedField):
    """FK field that only accepts objects owned by the requesting user."""

    def get_queryset(self):
        return self.queryset.filter(owner=self.context["request"].user)


class AccountSerializer(serializers.ModelSerializer):
    account_type_label = serializers.CharField(source="get_account_type_display", read_only=True)

    class Meta:
        model = Account
        fields = ["id", "name", "institution", "account_type", "account_type_label", "is_liquid", "notes", "archived"]


class AssetSerializer(serializers.ModelSerializer):
    asset_class_label = serializers.CharField(source="get_asset_class_display", read_only=True)
    price = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)

    class Meta:
        model = Asset
        fields = [
            "id", "symbol", "name", "asset_class", "asset_class_label", "price_source", "source_id",
            "manual_price", "last_price", "last_price_at", "price",
        ]
        read_only_fields = ["last_price", "last_price_at"]

    def validate_symbol(self, value):
        return value.strip().upper()


class TransactionSerializer(serializers.ModelSerializer):
    account = OwnedQuerysetField(queryset=Account.objects.all())
    asset = OwnedQuerysetField(queryset=Asset.objects.all())
    account_name = serializers.CharField(source="account.name", read_only=True)
    asset_symbol = serializers.CharField(source="asset.symbol", read_only=True)
    total = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id", "account", "account_name", "asset", "asset_symbol", "kind", "date", "quantity", "price",
            "fees", "total", "external_id", "notes",
        ]


class CashFlowSerializer(serializers.ModelSerializer):
    account = OwnedQuerysetField(queryset=Account.objects.all())
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = CashFlow
        fields = ["id", "account", "account_name", "date", "amount", "notes"]


class AllocationTargetSerializer(serializers.ModelSerializer):
    account = OwnedQuerysetField(queryset=Account.objects.all())
    asset = OwnedQuerysetField(queryset=Asset.objects.all())

    class Meta:
        model = AllocationTarget
        fields = ["id", "account", "asset", "target_pct"]

    def validate_target_pct(self, value):
        if not 0 <= value <= 100:
            raise serializers.ValidationError("Debe estar entre 0 y 100.")
        return value


class EquityGrantSerializer(serializers.ModelSerializer):
    account = OwnedQuerysetField(queryset=Account.objects.all())
    cost_basis = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)
    market_value = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)

    class Meta:
        model = EquityGrant
        fields = [
            "id", "account", "company", "quantity", "strike", "fmv", "exercised", "grant_date", "notes",
            "cost_basis", "market_value",
        ]


class SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Snapshot
        fields = ["id", "date", "net_worth", "net_worth_ex_private", "liquid", "cost", "unrealized", "breakdown", "notes"]


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        exclude = ["id", "owner"]


class PositionSerializer(serializers.Serializer):
    """Read-only view of services.positions.Position."""

    account_id = serializers.IntegerField(source="account.id")
    account_name = serializers.CharField(source="account.name")
    asset_id = serializers.IntegerField(source="asset.id", allow_null=True, default=None)
    symbol = serializers.CharField()
    name = serializers.CharField()
    asset_class = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=28, decimal_places=10)
    avg_cost = serializers.DecimalField(max_digits=28, decimal_places=10)
    cost_basis = serializers.DecimalField(max_digits=28, decimal_places=2)
    price = serializers.DecimalField(max_digits=28, decimal_places=10)
    market_value = serializers.DecimalField(max_digits=28, decimal_places=2)
    unrealized = serializers.DecimalField(max_digits=28, decimal_places=2)
    unrealized_pct = serializers.DecimalField(max_digits=12, decimal_places=4, allow_null=True)
    realized = serializers.DecimalField(max_digits=28, decimal_places=2)
    weight_in_account = serializers.DecimalField(max_digits=12, decimal_places=4, allow_null=True)
    target_pct = serializers.DecimalField(max_digits=12, decimal_places=4, allow_null=True)
    target_value = serializers.DecimalField(max_digits=28, decimal_places=2, allow_null=True)
    rebalance = serializers.DecimalField(max_digits=28, decimal_places=2, allow_null=True)
    extra = serializers.SerializerMethodField()

    def get_extra(self, obj):
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in obj.extra.items()}
