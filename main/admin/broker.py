from django.contrib import admin

from main.models.broker import Broker


@admin.register(Broker)
class BrokerAdmin(admin.ModelAdmin):
    list_display = ('name', 'url',)
