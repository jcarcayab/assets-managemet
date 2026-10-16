from django.core.management.base import BaseCommand

from connections.exchange_sync import sync_exchange
from connections.models import ExchangeConnection


class Command(BaseCommand):
    help = "Sync every crypto exchange connection (meant for the daily scheduler)."

    def handle(self, **_):
        for conn in ExchangeConnection.objects.select_related("owner", "account"):
            report = sync_exchange(conn)
            label = f"{conn.owner.username} / {conn}"
            if report["error"]:
                self.stdout.write(self.style.WARNING(f"{label}: {report['error']}"))
            else:
                self.stdout.write(
                    f"{label}: {report['trades']} trades, {report['rewards']} rewards, "
                    f"{report['cash_flows']} flows, {report['adjustments']} adjustments"
                )
