from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from portfolio.models import Asset
from portfolio.services.history import update_history
from portfolio.services.prices import refresh_prices


class Command(BaseCommand):
    help = "Fetch live prices and daily price history for every user's assets and benchmarks (meant for cron)."

    def handle(self, **_):
        result = refresh_prices(Asset.objects.all())
        self.stdout.write(f"updated: {', '.join(result['updated']) or '-'}")
        if result["failed"]:
            self.stdout.write(self.style.WARNING(f"failed: {', '.join(result['failed'])}"))
        for user in get_user_model().objects.filter(assets__isnull=False).distinct():
            history = update_history(user)
            self.stdout.write(f"{user.username}: {history['saved']} daily closes stored")
            if history["failed"]:
                self.stdout.write(self.style.WARNING(f"  no history: {', '.join(history['failed'])}"))
