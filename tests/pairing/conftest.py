import pytest
from django.db import connection, models
from django.test.utils import isolate_apps

from django_sealed_fields import rows
from django_sealed_fields.pairing.fields import PairedFieldsMixin, PairedSealedTextField


@pytest.fixture
def Pair(transactional_db, monkeypatch):
    """A model with a table for the test, and the only model the commands see.

    Its table is made outside a transaction, which SQLite asks of a schema change.
    Nothing registers it with them: declaring the fields is enough.
    """
    with isolate_apps('django_sealed_fields.pairing') as registry:
        class Pair(PairedFieldsMixin, models.Model):
            plain = models.TextField(null=True)
            paired = PairedSealedTextField(purpose='test-paired', searchable=True, plain='plain')
            other = models.TextField(null=True)
            other_paired = PairedSealedTextField(purpose='test-other-paired', plain='other')

            class Meta:
                app_label = 'django_sealed_fields_pairing'

        with connection.schema_editor() as editor:
            editor.create_model(Pair)
        monkeypatch.setattr(rows, 'apps', registry)
        yield Pair
        with connection.schema_editor() as editor:
            editor.delete_model(Pair)
