from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security"
    verbose_name = "Seguridad"

    def ready(self):
        from security.admin_guard import protect_admin_site

        protect_admin_site()
