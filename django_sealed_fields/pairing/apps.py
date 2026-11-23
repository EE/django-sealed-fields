from django.apps import AppConfig


class PairingConfig(AppConfig):
    """Moving plain fields into sealed ones. A project that has none to move leaves it out."""

    name = 'django_sealed_fields.pairing'
    label = 'django_sealed_fields_pairing'
    verbose_name = 'Sealed fields: moving in from plain fields'
