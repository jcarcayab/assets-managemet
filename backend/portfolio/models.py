import calendar
import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

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


class TaxTreatment(models.TextChoices):
    TAXABLE = "taxable", "Gravable"
    TAX_DEFERRED = "tax_deferred", "Impuesto diferido (401k / IRA)"
    TAX_FREE = "tax_free", "Libre de impuestos (Roth / HSA)"


DEFAULT_TAX_TREATMENT = {
    AccountType.ROTH_IRA: TaxTreatment.TAX_FREE,
    AccountType.HSA: TaxTreatment.TAX_FREE,
    AccountType.K401: TaxTreatment.TAX_DEFERRED,
    AccountType.TRADITIONAL_IRA: TaxTreatment.TAX_DEFERRED,
}


class ExposureCategory(models.TextChoices):
    US_EQUITY = "us_equity", "Renta variable EE.UU."
    INTL_EQUITY = "intl_equity", "Renta variable internacional"
    BONDS = "bonds", "Bonos"
    CASH = "cash", "Efectivo"
    CRYPTO = "crypto", "Crypto"
    COMMODITIES = "commodities", "Metales / materias primas"
    REAL_ESTATE = "real_estate", "Inmobiliario"
    PRIVATE_EQUITY = "private_equity", "Equity privada"
    OTHER = "other", "Otro"


DEFAULT_EXPOSURE = {
    "stock": ExposureCategory.US_EQUITY,
    "bond": ExposureCategory.BONDS,
    "crypto": ExposureCategory.CRYPTO,
    "metal": ExposureCategory.COMMODITIES,
    "cash": ExposureCategory.CASH,
    "private_equity": ExposureCategory.PRIVATE_EQUITY,
    "real_estate": ExposureCategory.REAL_ESTATE,
    "other": ExposureCategory.OTHER,
}


class Account(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField(max_length=100)
    institution = models.CharField(max_length=100, blank=True)
    account_type = models.CharField(max_length=20, choices=AccountType.choices, default=AccountType.BROKERAGE)
    is_liquid = models.BooleanField(default=True, help_text="Accesible sin penalización (no retiro).")
    tax_treatment = models.CharField(
        max_length=20, choices=TaxTreatment.choices, blank=True,
        help_text="Vacío = según el tipo de cuenta (Roth/HSA libre, 401k/IRA diferido, resto gravable).",
    )
    notes = models.TextField(blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_account_name_per_owner")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.tax_treatment:
            self.tax_treatment = DEFAULT_TAX_TREATMENT.get(self.account_type, TaxTreatment.TAXABLE)
        super().save(*args, **kwargs)


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
    underlying = models.CharField(
        max_length=100, blank=True,
        help_text="Índice o emisor subyacente (p.ej. 'S&P 500'). Agrupa fondos que replican lo mismo.",
    )
    sector = models.CharField(max_length=60, blank=True, help_text="Sector de riesgo (p.ej. 'Crypto', 'Tecnología').")
    exposures = models.JSONField(
        default=dict, blank=True,
        help_text="Desglose por categoría en % (p.ej. fondo target date). Vacío = 100% según la clase.",
    )

    class Meta:
        ordering = ["symbol"]
        constraints = [models.UniqueConstraint(fields=["owner", "symbol"], name="uniq_asset_symbol_per_owner")]

    def __str__(self):
        return self.symbol

    @property
    def lookup_id(self) -> str:
        return self.source_id or self.symbol

    @property
    def history_symbol(self) -> str | None:
        """Yahoo ticker used for daily price history (Yahoo has deeper free crypto history than CoinGecko)."""
        if self.price_source == PriceSource.YAHOO:
            return self.lookup_id
        if self.price_source == PriceSource.COINGECKO:
            return f"{self.symbol}-USD"
        return None

    def exposure_breakdown(self) -> dict[str, Decimal]:
        if self.exposures:
            return {k: Decimal(str(v)) for k, v in self.exposures.items() if v}
        category = DEFAULT_EXPOSURE.get(self.asset_class)
        return {category: Decimal(100)} if category else {}

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
    DIVIDEND = "dividend", "Dividendo"
    INTEREST = "interest", "Interés"
    STAKING = "staking", "Staking / recompensa"
    FEE = "fee", "Comisión"
    SPLIT = "split", "Split"
    TRANSFER = "transfer", "Transferencia entre cuentas"


# Kinds that move cash in/out of the account's USD balance via `amount`.
CASH_KINDS = {TransactionKind.DIVIDEND, TransactionKind.INTEREST, TransactionKind.FEE}
INCOME_KINDS = {TransactionKind.DIVIDEND, TransactionKind.INTEREST, TransactionKind.STAKING}


class Transaction(models.Model):
    """One ledger entry. Field meaning depends on `kind`:

    - buy / sell / staking: `quantity` units at `price` (staking: fair value at receipt = cost basis).
    - dividend / interest / fee: `amount` in USD, credited/debited to the account's cash (USD) position.
    - split: `quantity` is the ratio (2 = 2-for-1).
    - transfer: `quantity` units move to `to_account` keeping their cost basis; `price` = market price that day.
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="transactions")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=10, choices=TransactionKind.choices, default=TransactionKind.BUY)
    date = models.DateField()
    quantity = models.DecimalField(**QTY, default=Decimal(0), validators=[MinValueValidator(Decimal(0))])
    price = models.DecimalField(**QTY, default=Decimal(0), validators=[MinValueValidator(Decimal(0))])
    fees = models.DecimalField(**QTY, default=Decimal(0), validators=[MinValueValidator(Decimal(0))])
    amount = models.DecimalField(
        **QTY, default=Decimal(0), validators=[MinValueValidator(Decimal(0))],
        help_text="Monto en USD para dividendos, intereses y comisiones.",
    )
    to_account = models.ForeignKey(
        Account, on_delete=models.CASCADE, null=True, blank=True, related_name="transfers_in",
        help_text="Cuenta destino (solo transferencias).",
    )
    external_id = models.CharField(max_length=100, blank=True, help_text="Order ID del exchange/broker.")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["account", "asset", "date"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.asset} {self.date}"

    @property
    def total(self) -> Decimal:
        if self.kind in CASH_KINDS:
            return self.amount
        if self.kind == TransactionKind.SPLIT:
            return Decimal(0)
        gross = self.quantity * self.price
        if self.kind == TransactionKind.BUY:
            return gross + self.fees
        if self.kind == TransactionKind.SELL:
            return gross - self.fees
        return gross


class CashFlowKind(models.TextChoices):
    DEPOSIT = "deposit", "Depósito"
    WITHDRAWAL = "withdrawal", "Retiro"
    EMPLOYER = "employer", "Aporte del empleador"


class CashFlow(models.Model):
    """Money moved into (+) or out of (-) an account from outside. Used for return vs. deposits."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="cash_flows")
    kind = models.CharField(max_length=12, choices=CashFlowKind.choices, default=CashFlowKind.DEPOSIT)
    date = models.DateField()
    amount = models.DecimalField(**MONEY, help_text="Positivo = entra a la cuenta, negativo = sale.")
    notes = models.CharField(max_length=200, blank=True)
    external_id = models.CharField(max_length=100, blank=True, db_index=True, help_text="ID del origen (p.ej. Plaid).")

    class Meta:
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        # The sign always follows the kind, whatever the user typed.
        self.amount = -abs(self.amount) if self.kind == CashFlowKind.WITHDRAWAL else abs(self.amount)
        super().save(*args, **kwargs)


class PriceHistory(models.Model):
    """Daily closes, shared across users (keyed by Yahoo ticker). Used for performance and benchmarks."""

    symbol = models.CharField(max_length=30)
    date = models.DateField()
    close = models.DecimalField(**QTY)

    class Meta:
        ordering = ["symbol", "date"]
        constraints = [models.UniqueConstraint(fields=["symbol", "date"], name="uniq_price_per_day")]


class AllocationTarget(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="targets")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="targets")
    target_pct = models.DecimalField(max_digits=6, decimal_places=3, help_text="0–100")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "asset"], name="uniq_target_per_position")]


class GrantType(models.TextChoices):
    NSO = "nso", "Opciones NSO"
    ISO = "iso", "Opciones ISO"
    SHARES = "shares", "Acciones (ya compradas)"


def add_months(d: dt.date, months: int) -> dt.date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


class EquityGrant(models.Model):
    """Private company equity.

    Options are valued at intrinsic value (FMV − strike) × vested options until exercised; exercised options and
    shares at FMV. Only the vested part counts, and an optional liquidity discount reflects that private shares
    can't be sold at FMV today.
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="equity_grants")
    company = models.CharField(max_length=100)
    grant_type = models.CharField(max_length=10, choices=GrantType.choices, default=GrantType.NSO)
    quantity = models.DecimalField(**QTY)
    strike = models.DecimalField(**QTY, help_text="Strike de la opción, o precio pagado por acción.")
    fmv = models.DecimalField(**QTY, help_text="Valor justo de mercado por acción (manual, p.ej. último 409A).")
    exercised = models.BooleanField(default=False)
    grant_date = models.DateField(null=True, blank=True)
    vesting_start = models.DateField(null=True, blank=True, help_text="Vacío = todo adquirido (vested).")
    vesting_months = models.PositiveSmallIntegerField(default=48)
    cliff_months = models.PositiveSmallIntegerField(default=12)
    expiration_date = models.DateField(null=True, blank=True, help_text="Vencimiento de las opciones (típico: 10 años).")
    post_termination_days = models.PositiveSmallIntegerField(
        default=90, help_text="Días para ejercer si dejas la empresa."
    )
    liquidity_discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal(0),
        validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))],
        help_text="Descuento sobre el FMV por no poder vender (0–100).",
    )
    sector = models.CharField(
        max_length=60, blank=True, help_text="Sector de la empresa, para medir concentración con otros activos."
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["company"]

    def __str__(self):
        return f"{self.company} ({self.quantity})"

    @property
    def is_option(self) -> bool:
        return self.grant_type != GrantType.SHARES and not self.exercised

    def vested_quantity(self, on: dt.date | None = None) -> Decimal:
        if self.vesting_start is None or self.grant_type == GrantType.SHARES or self.exercised:
            return self.quantity
        on = on or timezone.localdate()
        months = (on.year - self.vesting_start.year) * 12 + on.month - self.vesting_start.month
        if on.day < self.vesting_start.day:
            months -= 1
        if months < self.cliff_months:
            return Decimal(0)
        if not self.vesting_months or months >= self.vesting_months:
            return self.quantity
        return (Decimal(self.quantity) * months / self.vesting_months).quantize(Decimal("0.0001"))

    def next_vest_date(self, on: dt.date | None = None) -> dt.date | None:
        if self.vesting_start is None or self.vested_quantity(on) >= self.quantity:
            return None
        on = on or timezone.localdate()
        months = max(self.cliff_months, 1)
        while add_months(self.vesting_start, months) <= on:
            months += 1
        return add_months(self.vesting_start, months)

    @property
    def fully_vested_date(self) -> dt.date | None:
        return add_months(self.vesting_start, self.vesting_months) if self.vesting_start else None

    @property
    def per_share_value(self) -> Decimal:
        """Value per vested unit, after the liquidity discount."""
        fmv = self.fmv * (1 - self.liquidity_discount_pct / 100)
        return max(fmv - self.strike, Decimal(0)) if self.is_option else fmv

    @property
    def cost_basis(self) -> Decimal:
        return Decimal(0) if self.is_option else self.vested_quantity() * self.strike

    @property
    def market_value(self) -> Decimal:
        return self.vested_quantity() * self.per_share_value

    @property
    def exercise_cost(self) -> Decimal:
        return self.vested_quantity() * self.strike if self.is_option else Decimal(0)


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


class BudgetKind(models.TextChoices):
    INCOME = "income", "Ingreso"
    EXPENSE = "expense", "Gasto"


class Frequency(models.TextChoices):
    MONTHLY = "monthly", "Mensual"
    ANNUAL = "annual", "Anual"


class BudgetItem(models.Model):
    """A recurring income or expense line of the household budget (net, after taxes for income)."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budget_items")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=BudgetKind.choices, default=BudgetKind.EXPENSE)
    category = models.CharField(max_length=60, blank=True)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal(0))])
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY)
    essential = models.BooleanField(default=True, help_text="Gasto que seguirías pagando sin ingresos (fondo de emergencia).")
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["kind", "-amount"]

    @property
    def monthly(self) -> Decimal:
        return self.amount / 12 if self.frequency == Frequency.ANNUAL else self.amount


class LiabilityKind(models.TextChoices):
    MORTGAGE = "mortgage", "Hipoteca"
    CREDIT_CARD = "credit_card", "Tarjeta de crédito"
    STUDENT = "student", "Préstamo estudiantil"
    AUTO = "auto", "Préstamo de auto"
    PERSONAL = "personal", "Préstamo personal"
    OTHER = "other", "Otro"


class Liability(models.Model):
    """Money owed. Subtracts from net worth; the balance is updated by hand."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="liabilities")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=LiabilityKind.choices, default=LiabilityKind.OTHER)
    balance = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal(0))])
    interest_rate_pct = models.DecimalField(
        max_digits=6, decimal_places=3, default=Decimal(0), validators=[MinValueValidator(Decimal(0))],
        help_text="Tasa anual (APR).",
    )
    minimum_payment = models.DecimalField(**MONEY, default=Decimal(0), help_text="Pago mínimo mensual.")
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-interest_rate_pct", "-balance"]
        verbose_name_plural = "liabilities"


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
    benchmark = models.CharField(max_length=20, default="SPY", help_text="Ticker de Yahoo para comparar rendimiento.")
    concentration_limit_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(20))
    capital_gains_tax_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal(15), help_text="Sobre ganancias no realizadas en cuentas gravables."
    )
    retirement_tax_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal(22), help_text="Tasa esperada al retirar de 401k / IRA tradicional."
    )
    ordinary_income_tax_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal(24),
        help_text="Ganancias de corto plazo (<1 año) y spread de opciones NSO.",
    )
    target_allocation = models.JSONField(
        default=dict, blank=True, help_text="Asignación objetivo del hogar por categoría de exposición, en %."
    )
    rebalance_threshold_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal(5), help_text="Desviación (puntos %) que dispara rebalanceo."
    )
    emergency_fund_months = models.PositiveSmallIntegerField(default=6, help_text="Meses de gastos esenciales objetivo.")
    expected_volatility_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal(15), help_text="Volatilidad anual esperada para Monte Carlo."
    )
    employer_match_annual = models.DecimalField(**MONEY, default=Decimal(0), help_text="Aporte anual del empleador.")
    social_security_annual = models.DecimalField(
        **MONEY, default=Decimal(0), help_text="Beneficio anual estimado de Seguro Social (en dólares de hoy)."
    )
    social_security_age = models.PositiveSmallIntegerField(default=67)
    life_expectancy = models.PositiveSmallIntegerField(default=95)

    @classmethod
    def for_user(cls, user) -> "UserSettings":
        obj, _ = cls.objects.get_or_create(owner=user)
        return obj
