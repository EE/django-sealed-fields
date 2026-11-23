from django.apps import AppConfig
from django.core import checks


class SealedFieldsConfig(AppConfig):
    name = 'django_sealed_fields'
    verbose_name = 'Sealed fields'

    def ready(self):
        from .checks import check_fields, check_keys

        checks.register(check_fields, checks.Tags.models)
        checks.register(check_keys, checks.Tags.security)
