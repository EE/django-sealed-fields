import pytest
from django.db import connection, models
from django.test.utils import isolate_apps

from django_sealed_fields import rows
from django_sealed_fields.fields import SealedTextField


@pytest.fixture
def Record(transactional_db, monkeypatch):
    """A model with a table for the test, and the only model the command sees.

    Its table is made outside a transaction, which SQLite asks of a schema change.
    Nothing registers it with the command: declaring the fields is enough.
    """
    with isolate_apps('django_sealed_fields') as registry:
        class Record(models.Model):
            searchable = SealedTextField(
                purpose='test-searchable', searchable=True, unique=True, null=True, blank=True,
            )
            standalone = SealedTextField(purpose='test-standalone', null=True, blank=True)

            class Meta:
                app_label = 'django_sealed_fields'

        with connection.schema_editor() as editor:
            editor.create_model(Record)
        monkeypatch.setattr(rows, 'apps', registry)
        yield Record
        with connection.schema_editor() as editor:
            editor.delete_model(Record)
