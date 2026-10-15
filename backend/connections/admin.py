from django.contrib import admin

from connections.models import PlaidAccount, PlaidItem


class PlaidAccountInline(admin.TabularInline):
    model = PlaidAccount
    fields = ["name", "mask", "type", "subtype", "account", "enabled", "current_balance"]
    readonly_fields = ["name", "mask", "type", "subtype", "current_balance"]
    extra = 0


@admin.register(PlaidItem)
class PlaidItemAdmin(admin.ModelAdmin):
    """The access token is never displayed."""

    list_display = ["institution_name", "owner", "last_synced_at", "needs_reauth", "last_error"]
    fields = ["owner", "institution_name", "item_id", "created_at", "last_synced_at", "needs_reauth", "last_error"]
    readonly_fields = fields
    inlines = [PlaidAccountInline]

    def has_add_permission(self, request):
        return False
