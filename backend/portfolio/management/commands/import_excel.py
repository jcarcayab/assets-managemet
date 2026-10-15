from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from portfolio.services.excel_import import LegacyImporter


class Command(BaseCommand):
    help = "Import accounts, positions, trades and history from the legacy StockMarket_organizado.xlsx"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--user", required=True, help="Username that will own the imported data")
        parser.add_argument("--reset", action="store_true", help="Delete the user's existing portfolio data first")

    def handle(self, path, user, reset, **_):
        User = get_user_model()
        try:
            owner = User.objects.get(username=user)
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{user}' not found. Create it with `manage.py createsuperuser`.") from exc

        report = LegacyImporter(path, owner).run(reset=reset)
        for name in ("accounts", "assets", "transactions", "cash_flows", "targets", "equity_grants", "snapshots"):
            self.stdout.write(f"{name:>14}: {getattr(report, name)}")
        for w in report.warnings:
            self.stdout.write(self.style.WARNING(w))
        self.stdout.write(self.style.SUCCESS("Import done. Run `manage.py refresh_prices` to load live prices."))
