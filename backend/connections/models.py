from django.conf import settings
from django.db import models

from portfolio.models import MONEY, Account, Liability
from security.crypto import decrypt, encrypt


class PlaidItem(models.Model):
    """One login at one institution, as connected through Plaid Link."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plaid_items")
    item_id = models.CharField(max_length=100, unique=True)
    access_token_encrypted = models.TextField()
    institution_id = models.CharField(max_length=50, blank=True)
    institution_name = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    needs_reauth = models.BooleanField(default=False, help_text="La institución pide volver a iniciar sesión en Plaid Link.")
    # Plaid Transactions (billed per item): only turned on where bank interest is wanted.
    bank_transactions = models.BooleanField(default=False, help_text="Importar intereses de cuentas bancarias.")
    transactions_cursor = models.TextField(blank=True)
    transactions_error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["institution_name", "id"]

    def __str__(self):
        return self.institution_name or self.item_id

    @property
    def access_token(self) -> str:
        return decrypt(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value: str) -> None:
        self.access_token_encrypted = encrypt(value)


class ExchangeProvider(models.TextChoices):
    COINBASE = "coinbase", "Coinbase"
    KRAKEN = "kraken", "Kraken"


class ExchangeConnection(models.Model):
    """Read-only API credentials for a crypto exchange, mirrored into one portfolio account."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exchange_connections")
    provider = models.CharField(max_length=20, choices=ExchangeProvider.choices)
    label = models.CharField(max_length=60, blank=True)
    api_key_encrypted = models.TextField()
    api_secret_encrypted = models.TextField()
    key_hint = models.CharField(max_length=12, blank=True, help_text="Final de la llave, para reconocerla.")
    account = models.ForeignKey(
        Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="exchange_links",
        help_text="Cuenta del portafolio que refleja el exchange. Vacía = se crea una al sincronizar.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["provider", "id"]

    def __str__(self):
        return self.label or self.get_provider_display()

    @property
    def api_key(self) -> str:
        return decrypt(self.api_key_encrypted)

    @property
    def api_secret(self) -> str:
        return decrypt(self.api_secret_encrypted)

    def set_credentials(self, key: str, secret: str) -> None:
        self.api_key_encrypted = encrypt(key)
        self.api_secret_encrypted = encrypt(secret)
        self.key_hint = key.strip()[-6:]


class PlaidAccount(models.Model):
    """An account inside a Plaid item, mapped to one of our portfolio accounts."""

    item = models.ForeignKey(PlaidItem, on_delete=models.CASCADE, related_name="accounts")
    plaid_account_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    official_name = models.CharField(max_length=200, blank=True)
    mask = models.CharField(max_length=10, blank=True)
    type = models.CharField(max_length=30)
    subtype = models.CharField(max_length=50, blank=True)
    account = models.ForeignKey(
        Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="plaid_links",
        help_text="Cuenta del portafolio que refleja esta cuenta. Vacía = se crea una al sincronizar.",
    )
    liability = models.ForeignKey(
        Liability, on_delete=models.SET_NULL, null=True, blank=True, related_name="plaid_links",
        help_text="Deuda que refleja esta tarjeta o préstamo. Vacía = se crea una al sincronizar.",
    )
    enabled = models.BooleanField(default=True)
    current_balance = models.DecimalField(**MONEY, null=True, blank=True)

    class Meta:
        ordering = ["item", "name"]

    def __str__(self):
        return f"{self.name} ····{self.mask}" if self.mask else self.name
