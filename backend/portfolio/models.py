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
    # RESTRICT (not PROTECT): an asset with history can't be deleted on its own, but deleting the user still
    # cascades through accounts and assets together.
    asset = models.ForeignKey(Asset, on_delete=models.RESTRICT, related_name="transactions")
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

    Options can be exercised in parts (EquityExercise). Vested options not yet exercised are valued at intrinsic
    value (FMV − strike); shares (bought, or from exercises) at FMV. Unvested units don't count, and an optional
    liquidity discount reflects that private shares can't be sold at FMV today.
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="equity_grants")
    company = models.CharField(max_length=100)
    grant_type = models.CharField(max_length=10, choices=GrantType.choices, default=GrantType.NSO)
    quantity = models.DecimalField(**QTY)
    strike = models.DecimalField(**QTY, help_text="Strike de la opción, o precio pagado por acción.")
    fmv = models.DecimalField(**QTY, help_text="Valor justo de mercado por acción (manual, p.ej. último 409A).")
    grant_date = models.DateField(null=True, blank=True)
    vesting_start = models.DateField(null=True, blank=True, help_text="Vacío = todo adquirido (vested).")
    vesting_months = models.PositiveSmallIntegerField(default=48)
    cliff_months = models.PositiveSmallIntegerField(default=12)
    expiration_date = models.DateField(null=True, blank=True, help_text="Vencimiento de las opciones (típico: 10 años).")
    post_termination_days = models.PositiveSmallIntegerField(
        default=90, help_text="Días para ejercer si dejas la empresa."
    )
    termination_date = models.DateField(
        null=True, blank=True, help_text="Si dejaste la empresa: el vesting se detiene y empieza el plazo para ejercer."
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
        return self.grant_type != GrantType.SHARES

    def exercised_quantity(self) -> Decimal:
        """Options already turned into shares (uses prefetched `exercises` when available)."""
        if not self.is_option or self.pk is None:
            return Decimal(0)
        return sum((e.quantity for e in self.exercises.all()), Decimal(0))

    @property
    def exercise_deadline(self) -> dt.date | None:
        """Last day to exercise: the expiration date, or the post-termination window if you left (earlier wins)."""
        dates = [d for d in (self.expiration_date,) if d]
        if self.termination_date:
            dates.append(self.termination_date + dt.timedelta(days=self.post_termination_days))
        return min(dates) if dates else None

    def options_lost(self, on: dt.date | None = None) -> bool:
        deadline = self.exercise_deadline
        return bool(deadline and (on or timezone.localdate()) > deadline)

    def open_options(self, on: dt.date | None = None) -> Decimal:
        """Vested options still available to exercise (none once the deadline has passed)."""
        if not self.is_option or self.options_lost(on):
            return Decimal(0)
        return max(self.vested_quantity(on) - self.exercised_quantity(), Decimal(0))

    def shares_held(self, on: dt.date | None = None) -> Decimal:
        return self.exercised_quantity() if self.is_option else self.vested_quantity(on)

    def vested_quantity(self, on: dt.date | None = None) -> Decimal:
        if self.vesting_start is None or self.grant_type == GrantType.SHARES:
            return self.quantity
        on = on or timezone.localdate()
        if self.termination_date:
            on = min(on, self.termination_date)  # vesting stops when you leave
        months = (on.year - self.vesting_start.year) * 12 + on.month - self.vesting_start.month
        if on.day < self.vesting_start.day:
            months -= 1
        if months < self.cliff_months:
            return Decimal(0)
        if not self.vesting_months or months >= self.vesting_months:
            return self.quantity
        return (Decimal(self.quantity) * months / self.vesting_months).quantize(Decimal("0.0001"))

    def next_vest_date(self, on: dt.date | None = None) -> dt.date | None:
        if self.vesting_start is None or self.termination_date or self.vested_quantity(on) >= self.quantity:
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
    def share_value(self) -> Decimal:
        """Value of one share, after the liquidity discount."""
        return self.fmv * (1 - self.liquidity_discount_pct / 100)

    @property
    def per_share_value(self) -> Decimal:
        """Value of one unit of the grant as granted: an option's intrinsic value, or a share."""
        return max(self.share_value - self.strike, Decimal(0)) if self.is_option else self.share_value

    @property
    def shares_cost_basis(self) -> Decimal:
        """Tax basis of the shares held. NSO: FMV at exercise (the spread was already taxed as wages)."""
        if not self.is_option:
            return self.vested_quantity() * self.strike
        if self.grant_type == GrantType.NSO:
            return sum((e.quantity * max(e.fmv, self.strike) for e in self.exercises.all()), Decimal(0))
        return self.exercised_quantity() * self.strike

    @property
    def cost_basis(self) -> Decimal:
        return self.shares_cost_basis  # open options cost nothing until exercised

    @property
    def market_value(self) -> Decimal:
        options = self.open_options() * self.per_share_value if self.is_option else Decimal(0)
        return self.shares_held() * self.share_value + options

    @property
    def exercise_cost(self) -> Decimal:
        """Cash to exercise every vested option still open."""
        return self.open_options() * self.strike


class EquityExercise(models.Model):
    """Options of a grant exercised on one day (a grant can be exercised a bit at a time)."""

    grant = models.ForeignKey(EquityGrant, on_delete=models.CASCADE, related_name="exercises")
    date = models.DateField()
    quantity = models.DecimalField(**QTY)
    fmv = models.DecimalField(**QTY, help_text="FMV por acción el día del ejercicio.")
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["date", "id"]

    def __str__(self):
        return f"{self.grant.company}: {self.quantity} el {self.date}"

    @property
    def cost(self) -> Decimal:
        return self.quantity * self.grant.strike

    @property
    def spread(self) -> Decimal:
        return self.quantity * max(self.fmv - self.grant.strike, Decimal(0))


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


class SpendingCategory(models.TextChoices):
    """Plaid's personal-finance categories (primary level) that count as spending."""

    FOOD_AND_DRINK = "FOOD_AND_DRINK", "Comida y bebida"
    GENERAL_MERCHANDISE = "GENERAL_MERCHANDISE", "Compras"
    RENT_AND_UTILITIES = "RENT_AND_UTILITIES", "Vivienda y servicios"
    TRANSPORTATION = "TRANSPORTATION", "Transporte"
    TRAVEL = "TRAVEL", "Viajes"
    ENTERTAINMENT = "ENTERTAINMENT", "Entretenimiento"
    GENERAL_SERVICES = "GENERAL_SERVICES", "Servicios y suscripciones"
    PERSONAL_CARE = "PERSONAL_CARE", "Cuidado personal"
    MEDICAL = "MEDICAL", "Salud"
    HOME_IMPROVEMENT = "HOME_IMPROVEMENT", "Hogar"
    LOAN_PAYMENTS = "LOAN_PAYMENTS", "Pagos de préstamos"
    GOVERNMENT_AND_NON_PROFIT = "GOVERNMENT_AND_NON_PROFIT", "Gobierno y donaciones"
    BANK_FEES = "BANK_FEES", "Comisiones bancarias"
    OTHER = "OTHER", "Otros"


class BudgetItem(models.Model):
    """A recurring income or expense line of the household budget (net, after taxes for income)."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budget_items")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=BudgetKind.choices, default=BudgetKind.EXPENSE)
    category = models.CharField(max_length=60, blank=True)
    spending_category = models.CharField(
        max_length=30, choices=SpendingCategory.choices, blank=True,
        help_text="Categoría de los movimientos de tus tarjetas con la que se compara este gasto.",
    )
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
    promo_rate_pct = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(Decimal(0))],
        help_text="Tasa durante la promoción (p.ej. 0). Vacío = sin promoción.",
    )
    promo_end_date = models.DateField(null=True, blank=True, help_text="Último día de la tasa promocional.")
    deferred_interest = models.BooleanField(
        default=False,
        help_text="Intereses diferidos: si no se liquida antes del fin, cobran todo el interés de la promoción.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-interest_rate_pct", "-balance"]
        verbose_name_plural = "liabilities"

    def in_promo(self, on: dt.date) -> bool:
        return self.promo_rate_pct is not None and self.promo_end_date is not None and on <= self.promo_end_date

    def current_rate_pct(self, on: dt.date) -> Decimal:
        return self.promo_rate_pct if self.in_promo(on) else self.interest_rate_pct


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
    projection_by_asset_class = models.BooleanField(
        default=True,
        help_text="Monte Carlo con rendimiento y volatilidad según tu asignación por tipo de activo (si no, la tasa única).",
    )
    return_assumptions = models.JSONField(
        default=dict, blank=True,
        help_text="Supuestos propios por tipo de activo: {clase: {return: %, volatility: %}}; vacío = los de por defecto.",
    )

    @classmethod
    def for_user(cls, user) -> "UserSettings":
        obj, _ = cls.objects.get_or_create(owner=user)
        return obj


class CacheVersion(models.Model):
    """A counter bumped whenever cached data changes (shared by the web and scheduler processes)."""

    name = models.CharField(max_length=40, primary_key=True)
    value = models.BigIntegerField(default=0)

    def __str__(self):
        return f"{self.name}={self.value}"
