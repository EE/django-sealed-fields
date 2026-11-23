from django.db import models
from django.test.utils import isolate_apps

from sealed_fields import checks as checks_module
from sealed_fields.checks import check_fields, check_keys
from sealed_fields.fields import SealedTextField


def test_no_two_fields_may_share_a_purpose(monkeypatch):
    """A token moved between them would unseal, which purpose is there to prevent. Every model is
    checked, as the clash may be with one outside the apps asked about."""
    with isolate_apps('sealed_fields') as registry:
        class First(models.Model):
            secret = SealedTextField(purpose='test-secret')

            class Meta:
                app_label = 'sealed_fields'

        class Second(models.Model):
            secret = SealedTextField(purpose='test-secret')

            class Meta:
                app_label = 'sealed_fields'

        monkeypatch.setattr(checks_module, 'apps', registry)
        errors = check_fields(app_configs=[])

    assert [error.id for error in errors] == ['sealed_fields.E001']
    assert 'sealed_fields.First.secret, sealed_fields.Second.secret' in errors[0].msg


def test_a_field_that_is_not_searchable_keys_no_index_or_uniqueness(monkeypatch):
    with isolate_apps('sealed_fields') as registry:
        class Indexed(models.Model):
            unique = SealedTextField(purpose='test-unique', unique=True)
            indexed = SealedTextField(purpose='test-indexed', db_index=True)
            together = SealedTextField(purpose='test-together')
            constrained = SealedTextField(purpose='test-constrained')
            in_index = SealedTextField(purpose='test-in-index')
            searchable = SealedTextField(purpose='test-searchable', searchable=True, unique=True)
            free = SealedTextField(purpose='test-free')
            other = models.IntegerField()

            class Meta:
                app_label = 'sealed_fields'
                unique_together = [('together', 'other')]
                constraints = [models.UniqueConstraint(fields=['other', 'constrained'], name='constrained')]
                indexes = [models.Index(fields=['-in_index'], name='in_index')]

        monkeypatch.setattr(checks_module, 'apps', registry)
        errors = check_fields(app_configs=[])

    assert sorted((error.id, error.obj.name) for error in errors) == [
        ('sealed_fields.E002', name) for name in ('constrained', 'in_index', 'indexed', 'together', 'unique')
    ]


def test_no_key_warns_once_a_field_needs_it(settings, monkeypatch):
    settings.SEALED_FIELDS_KEY = ''
    with isolate_apps('sealed_fields') as registry:
        monkeypatch.setattr(checks_module, 'apps', registry)
        assert check_keys() == []

        class Secret(models.Model):
            secret = SealedTextField(purpose='test-secret')

            class Meta:
                app_label = 'sealed_fields'

        warnings = check_keys()

    assert [(warning.id, warning.is_serious()) for warning in warnings] == [('sealed_fields.W001', False)]
    assert 'sealed_fields.Secret.secret' in warnings[0].msg


def test_no_setting_at_all_counts_as_no_key(settings, monkeypatch):
    del settings.SEALED_FIELDS_KEY
    del settings.SEALED_FIELDS_KEY_FALLBACKS
    with isolate_apps('sealed_fields') as registry:
        monkeypatch.setattr(checks_module, 'apps', registry)

        class Secret(models.Model):
            secret = SealedTextField(purpose='test-secret')

            class Meta:
                app_label = 'sealed_fields'

        assert [warning.id for warning in check_keys()] == ['sealed_fields.W001']


def test_a_short_key_warns_naming_the_setting_it_is_in(settings):
    settings.SEALED_FIELDS_KEY = 'short'
    settings.SEALED_FIELDS_KEY_FALLBACKS = ['a-key-of-enough-length-to-pass-the-check', '']  # '' a stray comma

    warnings = check_keys()

    assert [(warning.id, warning.is_serious(), warning.msg.split(' is shorter')[0]) for warning in warnings] == [
        ('sealed_fields.W002', False, 'SEALED_FIELDS_KEY'),
        ('sealed_fields.W002', False, 'Key 2 of SEALED_FIELDS_KEY_FALLBACKS'),
    ]
