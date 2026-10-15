from django.core.management.base import BaseCommand

from portfolio.models import Asset
from portfolio.services.prices import refresh_prices


class Command(BaseCommand):
    help = "Fetch live prices for every asset with a Yahoo/CoinGecko price source (meant for cron)."

    def handle(self, **_):
        result = refresh_prices(Asset.objects.all())
        self.stdout.write(f"updated: {', '.join(result['updated']) or '-'}")
        if result["failed"]:
            self.stdout.write(self.style.WARNING(f"failed: {', '.join(result['failed'])}"))
