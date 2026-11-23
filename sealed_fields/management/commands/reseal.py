"""Reseal every sealed field under ``SEALED_FIELDS_KEY``, or check with ``--check`` that every one is.

Declaring a ``SealedTextField`` is all it takes: this finds every one through the app registry.
Resealing rewrites every sealed field in every row, a batch per transaction,
so it can be stopped and run again; it is the middle step of a key rotation.
Run ``--check`` before removing a key from ``SEALED_FIELDS_KEY_FALLBACKS``.
"""
from collections import Counter

from cryptography.exceptions import InvalidTag
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from ...fields import ciphers, decrypt, sealed_fields_of
from ...rows import rewrite, stored_rows


def under_sealing_key(field, token):
    """Whether a stored ``token`` is blank, null, or made by ``SEALED_FIELDS_KEY``."""
    if not token:
        return True
    try:
        decrypt(ciphers()[0], token, field.purpose, field.searchable)
    except (InvalidTag, ValueError):
        return False
    return True


class Command(BaseCommand):
    help = 'Reseal every sealed field of every model under SEALED_FIELDS_KEY, or check it with --check.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--check', action='store_true',
            help='Write nothing; fail unless every value is under SEALED_FIELDS_KEY.',
        )
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, **options):
        models_with_fields = [model for model in apps.get_models() if sealed_fields_of(model._meta)]
        if options['check']:
            problems = sum(self.check_model(model, options['batch_size']) for model in models_with_fields)
            if problems:
                raise CommandError(f'{problems} values not under SEALED_FIELDS_KEY.')
        else:
            for model in models_with_fields:
                self.write_rows(model, options['batch_size'])

    def write_rows(self, model, batch_size):
        fields = sealed_fields_of(model._meta)

        def rewritten(row):
            obj = model(pk=row.pk)
            for field in fields:
                setattr(obj, field.attname, getattr(row, field.name))
            return obj

        names = [field.name for field in fields]
        rewrite(self.stdout, model._base_manager.all(), names, names, rewritten, batch_size)

    def check_model(self, model, batch_size):
        fields = sealed_fields_of(model._meta)
        total = 0
        old = Counter()
        for _row, tokens in stored_rows(model, fields, batch_size=batch_size):
            total += 1
            old.update(field for field, token in tokens.items() if not under_sealing_key(field, token))
        for field in fields:
            self.stdout.write(
                f'{model._meta.label}.{field.name}: {total} rows, {old[field]} not under SEALED_FIELDS_KEY',
            )
        return old.total()
