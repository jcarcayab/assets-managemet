from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from portfolio.models import Asset
from portfolio.services.prices import refresh_prices
from portfolio.services.snapshots import take_snapshot


class Command(BaseCommand):
    help = "Refresh prices and store today's net-worth snapshot for every user with accounts (meant for cron)."

    def add_arguments(self, parser):
        parser.add_argument("--no-refresh", action="store_true", help="Skip fetching live prices first")

    def handle(self, no_refresh, **_):
        if not no_refresh:
            refresh_prices(Asset.objects.all())
        for user in get_user_model().objects.filter(accounts__isnull=False).distinct():
            snap = take_snapshot(user)
            self.stdout.write(f"{user.username}: {snap.date} net worth {snap.net_worth}")
