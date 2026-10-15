from django.core.management.base import BaseCommand

from connections.models import PlaidItem
from connections.plaid import configured
from connections.sync import sync_item


class Command(BaseCommand):
    help = "Sync every Plaid connection (meant for the daily scheduler)."

    def handle(self, **_):
        if not configured():
            self.stdout.write("Plaid not configured; skipping.")
            return
        for item in PlaidItem.objects.select_related("owner"):
            report = sync_item(item)
            label = f"{item.owner.username} / {item.institution_name or item.item_id}"
            if report["error"]:
                self.stdout.write(self.style.WARNING(f"{label}: {report['error']['code']} {report['error']['message']}"))
            else:
                self.stdout.write(
                    f"{label}: {report['transactions']} tx, {report['cash_flows']} flows, "
                    f"{report['adjustments']} adjustments"
                )
