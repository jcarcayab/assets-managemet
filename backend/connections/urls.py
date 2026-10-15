from django.urls import path

from connections import views

urlpatterns = [
    path("status/", views.StatusView.as_view()),
    path("link-token/", views.LinkTokenView.as_view()),
    path("exchange/", views.ExchangeView.as_view()),
    path("items/", views.ItemListView.as_view()),
    path("items/<int:pk>/", views.ItemView.as_view()),
    path("items/<int:pk>/sync/", views.SyncView.as_view()),
    path("accounts/<int:pk>/", views.AccountView.as_view()),
]
