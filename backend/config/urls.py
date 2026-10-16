from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include, path, re_path
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def spa_index(request):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        raise Http404("Frontend not built. Run `npm run build` in frontend/ or use the Vite dev server.")
    return FileResponse(index.open("rb"), content_type="text/html")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("security.urls")),
    path("api/plaid/", include("connections.urls")),
    path("api/exchanges/", include("connections.exchange_urls")),
    path("api/", include("portfolio.urls")),
    re_path(r"^(?!api/|admin/|static/).*$", spa_index),
]
