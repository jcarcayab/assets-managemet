from django.urls import path

from connections import views

urlpatterns = [
    path("", views.ExchangeConnectionListView.as_view()),
    path("<int:pk>/", views.ExchangeConnectionView.as_view()),
    path("<int:pk>/sync/", views.ExchangeConnectionSyncView.as_view()),
]
