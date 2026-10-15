from django.contrib import admin

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


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["name", "institution", "account_type", "is_liquid", "archived", "owner"]
    list_filter = ["account_type", "is_liquid", "archived"]


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ["symbol", "name", "asset_class", "price_source", "manual_price", "last_price", "last_price_at"]
    list_filter = ["asset_class", "price_source"]
    search_fields = ["symbol", "name"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["date", "account", "kind", "asset", "quantity", "price", "fees"]
    list_filter = ["kind", "account", "asset"]
    date_hierarchy = "date"


admin.site.register(CashFlow)
admin.site.register(AllocationTarget)
admin.site.register(EquityGrant)
admin.site.register(Snapshot)
admin.site.register(UserSettings)
