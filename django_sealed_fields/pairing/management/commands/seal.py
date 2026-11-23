"""Seal the plain value of each pair not sealed yet, or check every pair with ``--check``.

Declaring a ``PairedSealedTextField`` is all it takes: this finds every one through the app registry.
It writes only the rows that need it, and only their sealed columns, a batch per transaction,
so it can be stopped and run again,
and a pair that disagrees keeps both its values for whoever knows which one is right.
Which key a value is under is ``reseal``'s business.
"""
from collections import Counter

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from ....fields import DecryptionError
from ....rows import rewrite, stored_rows
from ...fields import AGREE, DISAGREE, NOT_SEALED_YET, pair_state, paired_fields


UNREADABLE = 'not unsealing with any key'


def classify(field, plain, stored):
    """How a pair stands, given its ``plain`` value and its sealed column as ``stored``."""
    try:
        return pair_state(plain, field.unsealed(stored))
    except DecryptionError:
        return UNREADABLE


class Command(BaseCommand):
    help = "Seal each pair's plain value into its sealed field, or check every pair with --check."

    def add_arguments(self, parser):
        parser.add_argument(
            '--check', action='store_true',
            help='Write nothing; fail unless every pair agrees.',
        )
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, **options):
        models_with_pairs = [model for model in apps.get_models() if paired_fields(model._meta)]
        if options['check']:
            problems = sum(self.check_model(model, options['batch_size']) for model in models_with_pairs)
            if problems:
                raise CommandError(f'{problems} values not sealed yet, not unsealing, or disagreeing.')
        else:
            for model in models_with_pairs:
                self.write_rows(model, options['batch_size'])

    def write_rows(self, model, batch_size):
        fields = paired_fields(model._meta)

        def filled(row):
            """Each pair on its sealed value, or on its plain one where that is missing."""
            obj = model(pk=row.pk)
            for field in fields:
                value = getattr(row, field.name)
                setattr(obj, field.attname, getattr(row, field.plain) if value is None else value)
            return obj

        rows = model._base_manager.filter(missing_sealed(fields))
        read = [*(field.name for field in fields), *sorted({field.plain for field in fields})]
        # Only the sealed columns are written, so a pair that disagrees keeps both its values.
        rewrite(self.stdout, rows, read, [field.name for field in fields], filled, batch_size)

    def check_model(self, model, batch_size):
        fields = paired_fields(model._meta)
        plains = sorted({field.plain for field in fields})
        counts = {field: Counter() for field in fields}
        for row, tokens in stored_rows(model, fields, *plains, batch_size=batch_size):
            for field, token in tokens.items():
                counts[field][classify(field, getattr(row, field.plain), token)] += 1
        problems = 0
        for field, count in counts.items():
            outcomes = ', '.join(f'{count[outcome]} {outcome}' for outcome in (NOT_SEALED_YET, UNREADABLE, DISAGREE))
            self.stdout.write(f'{model._meta.label}.{field.name}: {count.total()} rows, {outcomes}')
            problems += count.total() - count[AGREE]
        return problems


def missing_sealed(fields):
    condition = Q()
    for field in fields:
        condition |= Q(**{f'{field.name}__isnull': True, f'{field.plain}__isnull': False})
    return condition
