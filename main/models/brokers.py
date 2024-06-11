from django.db import models


class Broker(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=255)

    def __str__(self):
        return self.name

    @property
    def key(self):
        return self.name.lower()