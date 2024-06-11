from django.test import TestCase

from main.models import Broker
from .base import print_test_case_result

class BrokersTestCase(TestCase):

    def setUp(self):
        Broker.objects.create(name='Broker')

    @print_test_case_result
    def test_create_broker(self):
        broker = Broker.objects.create(name='Broker')

        self.assertEqual(broker.name, 'Broker')
        self.assertEqual(broker.key, 'broker')
