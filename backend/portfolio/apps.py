from django.apps import AppConfig


class PortfolioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "portfolio"
    verbose_name = "Portafolio"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from portfolio.models import Account, Transaction
        from portfolio.services.positions import bump_ledger_version

        # Anything that changes what the ledger replays invalidates the cached replay.
        for model in (Transaction, Account):
            post_save.connect(bump_ledger_version, sender=model, dispatch_uid=f"ledger-version-save-{model.__name__}")
            post_delete.connect(bump_ledger_version, sender=model, dispatch_uid=f"ledger-version-delete-{model.__name__}")
