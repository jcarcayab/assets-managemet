from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

QTY = {"max_digits": 28, "decimal_places": 10}
MONEY = {"max_digits": 18, "decimal_places": 2}


class AccountType(models.TextChoices):
    BROKERAGE = "brokerage", "Broker"
    ROTH_IRA = "roth_ira", "Roth IRA"
    TRADITIONAL_IRA = "traditional_ira", "IRA tradicional"
    K401 = "401k", "401k"
    HSA = "hsa", "HSA"
    CRYPTO = "crypto", "Crypto"
    BANK = "bank", "Banco / Efectivo"
    LOAN = "loan", "Préstamo"
    PHYSICAL = "physical", "Físico"
    PRIVATE_EQUITY = "private_equity", "Equity privada"
    REAL_ESTATE = "real_estate", "Inmueble"
    OTHER = "other", "Otro"


class AssetClass(models.TextChoices):
    STOCK = "stock", "Acciones/ETF"
    BOND = "bond", "Bonos"
    CRYPTO = "crypto", "Crypto"
    METAL = "metal", "Metales"
    CASH = "cash", "Efectivo"
    DEBT = "debt", "Deuda"
    PRIVATE_EQUITY = "private_equity", "Equity privada"
    REAL_ESTATE = "real_estate", "Inmueble"
    OTHER = "other", "Otro"


class PriceSource(models.TextChoices):
    YAHOO = "yahoo", "Yahoo Finance"
    COINGECKO = "coingecko", "CoinGecko"
    MANUAL = "manual", "Manual"


class Account(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField(max_length=100)
    institution = models.CharField(max_length=100, blank=True)
    account_type = models.CharField(max_length=20, choices=AccountType.choices, default=AccountType.BROKERAGE)
    is_liquid = models.BooleanField(default=True, help_text="Accesible sin penalización (no retiro).")
    notes = models.TextField(blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_account_name_per_owner")]

    def __str__(self):
        return self.name


class Asset(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assets")
    symbol = models.CharField(max_length=30)
    name = models.CharField(max_length=150, blank=True)
    asset_class = models.CharField(max_length=20, choices=AssetClass.choices, default=AssetClass.STOCK)
    price_source = models.CharField(max_length=20, choices=PriceSource.choices, default=PriceSource.YAHOO)
    source_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="ID en la fuente de precios (p.ej. 'GC=F' en Yahoo, 'solana' en CoinGecko). Vacío = símbolo.",
    )
    manual_price = models.DecimalField(
        **QTY, null=True, blank=True, help_text="Si se define, tiene prioridad sobre el precio en vivo."
    )
    last_price = models.DecimalField(**QTY, null=True, blank=True)
    last_price_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["symbol"]
        constraints = [models.UniqueConstraint(fields=["owner", "symbol"], name="uniq_asset_symbol_per_owner")]

    def __str__(self):
        return self.symbol

    @property
    def lookup_id(self) -> str:
        return self.source_id or self.symbol

    @property
    def price(self) -> Decimal:
        if self.manual_price is not None:
            return self.manual_price
        return self.last_price if self.last_price is not None else Decimal(0)

    @property
    def sign(self) -> int:
        """Debt is stored as a positive balance but subtracts from net worth."""
        return -1 if self.asset_class == AssetClass.DEBT else 1


class TransactionKind(models.TextChoices):
    BUY = "buy", "Compra"
    SELL = "sell", "Venta"


class Transaction(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="transactions")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=10, choices=TransactionKind.choices, default=TransactionKind.BUY)
    date = models.DateField()
    quantity = models.DecimalField(**QTY, validators=[MinValueValidator(Decimal(0))])
    price = models.DecimalField(**QTY, validators=[MinValueValidator(Decimal(0))])
    fees = models.DecimalField(**QTY, default=Decimal(0), validators=[MinValueValidator(Decimal(0))])
    external_id = models.CharField(max_length=100, blank=True, help_text="Order ID del exchange/broker.")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["account", "asset", "date"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.asset} @ {self.price}"

    @property
    def total(self) -> Decimal:
        gross = self.quantity * self.price
        return gross + self.fees if self.kind == TransactionKind.BUY else gross - self.fees


class CashFlow(models.Model):
    """Money moved into (+) or out of (-) an account from outside. Used for return vs. deposits."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="cash_flows")
    date = models.DateField()
    amount = models.DecimalField(**MONEY, help_text="Positivo = depósito, negativo = retiro.")
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "-id"]


class AllocationTarget(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="targets")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="targets")
    target_pct = models.DecimalField(max_digits=6, decimal_places=3, help_text="0–100")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "asset"], name="uniq_target_per_position")]


class EquityGrant(models.Model):
    """Private company stock options. Unexercised options are valued at intrinsic value (FMV − strike)."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="equity_grants")
    company = models.CharField(max_length=100)
    quantity = models.DecimalField(**QTY)
    strike = models.DecimalField(**QTY)
    fmv = models.DecimalField(**QTY, help_text="Valor justo de mercado por acción (manual).")
    exercised = models.BooleanField(default=False)
    grant_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["company"]

    def __str__(self):
        return f"{self.company} ({self.quantity})"

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.strike if self.exercised else Decimal(0)

    @property
    def market_value(self) -> Decimal:
        per_share = self.fmv if self.exercised else max(self.fmv - self.strike, Decimal(0))
        return self.quantity * per_share


class Snapshot(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField()
    net_worth = models.DecimalField(**MONEY)
    net_worth_ex_private = models.DecimalField(**MONEY, null=True, blank=True)
    liquid = models.DecimalField(**MONEY, null=True, blank=True)
    cost = models.DecimalField(**MONEY, null=True, blank=True)
    unrealized = models.DecimalField(**MONEY, null=True, blank=True)
    breakdown = models.JSONField(default=dict, blank=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["owner", "date"], name="uniq_snapshot_per_day")]


class UserSettings(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portfolio_settings")
    take_profit_1_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(10))
    take_profit_2_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(20))
    stop_loss_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(-5))
    current_age = models.PositiveSmallIntegerField(default=35)
    retirement_age = models.PositiveSmallIntegerField(default=61)
    annual_return_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("3.8"))
    annual_contribution = models.DecimalField(**MONEY, default=Decimal(0))
    withdrawal_rate_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(4))
    inflation_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(3))

    @classmethod
    def for_user(cls, user) -> "UserSettings":
        obj, _ = cls.objects.get_or_create(owner=user)
        return obj
