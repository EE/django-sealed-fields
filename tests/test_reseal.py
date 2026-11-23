import pytest
from django.core.management import CommandError, call_command

from django_sealed_fields.sealed import Sealed


OTHER_KEY = 'another-sealing-key-of-enough-length'


def test_a_rotation_reseals_every_sealed_field(Record, settings):
    Record.objects.create(searchable='S', standalone='T')
    Record.objects.create()

    settings.SEALED_FIELDS_KEY_FALLBACKS = [settings.SEALED_FIELDS_KEY]
    settings.SEALED_FIELDS_KEY = OTHER_KEY
    with pytest.raises(CommandError, match='2 values not under SEALED_FIELDS_KEY'):
        call_command('reseal', check=True)
    call_command('reseal', batch_size=1)
    call_command('reseal', check=True)
    settings.SEALED_FIELDS_KEY_FALLBACKS = []

    record = Record.objects.get(searchable='S')
    assert record.standalone == Sealed('T')
    assert Record.objects.filter(searchable__isnull=True, standalone__isnull=True).exists()
