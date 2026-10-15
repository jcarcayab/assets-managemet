from django.contrib import admin

from security.models import TOTPDevice


@admin.register(TOTPDevice)
class TOTPDeviceAdmin(admin.ModelAdmin):
    """Deleting a device resets 2FA for a user who lost their phone and recovery codes. The secret is never shown."""

    list_display = ["user", "confirmed", "confirmed_at", "created_at"]
    fields = ["user", "confirmed", "confirmed_at", "created_at"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False
