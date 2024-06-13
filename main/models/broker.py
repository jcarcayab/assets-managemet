from django.db import models


class Broker(models.Model):
    name = models.CharField(max_length=100, unique=True,null=False,blank=False)
    url = models.URLField(max_length=200)

    def __str__(self):
        return self.name