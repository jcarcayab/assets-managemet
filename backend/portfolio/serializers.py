from decimal import Decimal

from rest_framework import serializers

from portfolio.models import (
    Account,
    AllocationTarget,
    Asset,
    BudgetItem,
    CashFlow,
    EquityGrant,
    ExposureCategory,
    Liability,
    Snapshot,
    Transaction,
    TransactionKind,
    UserSettings,
)


def clean_category_weights(value):
    """{category: pct} with known categories, non-negative, summing to 100 (or empty)."""
    if not value:
        return {}
    if not isinstance(value, dict):
        raise serializers.ValidationError("Debe ser un objeto {categoría: %}.")
    valid = dict(ExposureCategory.choices)
    cleaned = {}
    for key, pct in value.items():
        if key not in valid:
            raise serializers.ValidationError(f"Categoría desconocida: {key}")
        try:
            pct = float(pct or 0)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError(f"{key}: debe ser un número.") from exc
        if pct < 0:
            raise serializers.ValidationError(f"{key}: no puede ser negativo.")
        if pct:
            cleaned[key] = pct
    if cleaned and abs(sum(cleaned.values()) - 100) > 0.5:
        raise serializers.ValidationError(f"Los porcentajes deben sumar 100 (suman {sum(cleaned.values()):g}).")
    return cleaned


class OwnedQuerysetField(serializers.PrimaryKeyRelatedField):
    """FK field that only accepts objects owned by the requesting user."""

    def get_queryset(self):
        return self.queryset.filter(owner=self.context["request"].user)


class AccountSerializer(serializers.ModelSerializer):
    account_type_label = serializers.CharField(source="get_account_type_display", read_only=True)
    tax_treatment_label = serializers.CharField(source="get_tax_treatment_display", read_only=True)

    class Meta:
        model = Account
        fields = [
            "id", "name", "institution", "account_type", "account_type_label", "is_liquid",
            "tax_treatment", "tax_treatment_label", "notes", "archived",
        ]


class AssetSerializer(serializers.ModelSerializer):
    asset_class_label = serializers.CharField(source="get_asset_class_display", read_only=True)
    price = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)

    class Meta:
        model = Asset
        fields = [
            "id", "symbol", "name", "asset_class", "asset_class_label", "price_source", "source_id",
            "manual_price", "last_price", "last_price_at", "price", "underlying", "sector", "exposures",
        ]
        read_only_fields = ["last_price", "last_price_at"]

    def validate_symbol(self, value):
        return value.strip().upper()

    def validate_exposures(self, value):
        return clean_category_weights(value)


class TransactionSerializer(serializers.ModelSerializer):
    account = OwnedQuerysetField(queryset=Account.objects.all())
    asset = OwnedQuerysetField(queryset=Asset.objects.all())
    to_account = OwnedQuerysetField(queryset=Account.objects.all(), required=False, allow_null=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    to_account_name = serializers.CharField(source="to_account.name", read_only=True, default=None)
    asset_symbol = serializers.CharField(source="asset.symbol", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    total = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id", "account", "account_name", "asset", "asset_symbol", "kind", "kind_label", "date", "quantity",
            "price", "fees", "amount", "to_account", "to_account_name", "total", "external_id", "notes",
        ]

    # Which fields each kind needs to be > 0.
    REQUIRED = {
        TransactionKind.BUY: ["quantity"],
        TransactionKind.SELL: ["quantity"],
        TransactionKind.STAKING: ["quantity"],
        TransactionKind.DIVIDEND: ["amount"],
        TransactionKind.INTEREST: ["amount"],
        TransactionKind.FEE: ["amount"],
        TransactionKind.SPLIT: ["quantity"],
        TransactionKind.TRANSFER: ["quantity"],
    }

    def validate(self, attrs):
        merged = {**({} if self.instance is None else self._current()), **attrs}
        kind = merged.get("kind", TransactionKind.BUY)
        errors = {}
        for name in self.REQUIRED.get(kind, []):
            if not merged.get(name):
                errors[name] = "Requerido y mayor que 0 para este tipo."
        if kind == TransactionKind.TRANSFER:
            dest = merged.get("to_account")
            if dest is None:
                errors["to_account"] = "Indica la cuenta destino."
            elif dest == merged.get("account"):
                errors["to_account"] = "La cuenta destino debe ser distinta."
        elif merged.get("to_account") is not None:
            attrs["to_account"] = None
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def _current(self):
        i = self.instance
        return {
            "kind": i.kind, "quantity": i.quantity, "amount": i.amount, "account": i.account,
            "to_account": i.to_account,
        }


class CashFlowSerializer(serializers.ModelSerializer):
    account = OwnedQuerysetField(queryset=Account.objects.all())
    account_name = serializers.CharField(source="account.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = CashFlow
        fields = ["id", "account", "account_name", "kind", "kind_label", "date", "amount", "notes"]


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
    grant_type_label = serializers.CharField(source="get_grant_type_display", read_only=True)
    cost_basis = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)
    market_value = serializers.DecimalField(max_digits=28, decimal_places=10, read_only=True)

    class Meta:
        model = EquityGrant
        fields = [
            "id", "account", "company", "grant_type", "grant_type_label", "quantity", "strike", "fmv", "exercised",
            "grant_date", "vesting_start", "vesting_months", "cliff_months", "expiration_date",
            "post_termination_days", "liquidity_discount_pct", "sector", "notes", "cost_basis", "market_value",
        ]

    def validate(self, attrs):
        cliff = attrs.get("cliff_months", getattr(self.instance, "cliff_months", 0))
        months = attrs.get("vesting_months", getattr(self.instance, "vesting_months", 0))
        if cliff > months:
            raise serializers.ValidationError({"cliff_months": "El cliff no puede ser mayor que el vesting total."})
        return attrs


class BudgetItemSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    monthly = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = BudgetItem
        fields = ["id", "name", "kind", "kind_label", "category", "amount", "frequency", "monthly", "essential", "notes"]


class LiabilitySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Liability
        fields = [
            "id", "name", "kind", "kind_label", "balance", "interest_rate_pct", "minimum_payment", "updated_at", "notes",
        ]
        read_only_fields = ["updated_at"]


class SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Snapshot
        fields = ["id", "date", "net_worth", "net_worth_ex_private", "liquid", "cost", "unrealized", "breakdown", "notes"]


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        exclude = ["id", "owner"]

    def validate_target_allocation(self, value):
        return clean_category_weights(value)

    def validate_benchmark(self, value):
        from portfolio.services.history import BENCHMARKS

        if value not in BENCHMARKS:
            raise serializers.ValidationError("Benchmark no soportado.")
        return value


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
    income = serializers.DecimalField(max_digits=28, decimal_places=2)
    weight_in_account = serializers.DecimalField(max_digits=12, decimal_places=4, allow_null=True)
    target_pct = serializers.DecimalField(max_digits=12, decimal_places=4, allow_null=True)
    target_value = serializers.DecimalField(max_digits=28, decimal_places=2, allow_null=True)
    rebalance = serializers.DecimalField(max_digits=28, decimal_places=2, allow_null=True)
    extra = serializers.SerializerMethodField()

    def get_extra(self, obj):
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in obj.extra.items()}
