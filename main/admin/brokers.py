from django.contrib import admin
from ..models import Broker

@admin.register(Broker)
class BrokerAdmin(admin.ModelAdmin):
    list_display = ('name', 'url',)
