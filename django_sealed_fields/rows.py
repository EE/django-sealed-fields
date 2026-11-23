"""What the commands share: checking every stored value, and rewriting rows in batches."""
from collections import Counter

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.db.models.functions import Cast


UNREADABLE = 'not unsealing with any key'


class RowsCommand(BaseCommand):
    """A command that mends stored values in one state, or with ``--check`` counts them all.

    A value is ``OK``, in the state ``MENDED`` that the command rewrites,
    or in a state it can't rewrite, which needs a person:
    ``--check`` names the row of each of those, by its pk and never by a value.
    A command says which fields it covers, what state a value is in,
    which rows it rewrites, and what it writes there.
    """

    OK = MENDED = None
    STATES = ()  # every state but OK, in the order --check reports them

    def fields_of(self, opts):
        raise NotImplementedError

    def others(self, fields):
        """The columns read besides the fields, by ``state`` and ``mended``."""
        return ()

    def state(self, field, row, token):
        raise NotImplementedError

    def to_mend(self, model, fields):
        raise NotImplementedError

    def mended(self, field, row):
        raise NotImplementedError

    def add_arguments(self, parser):
        parser.add_argument(
            '--check', action='store_true', help=f'Write nothing; fail unless every value is {self.OK}.',
        )
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, check, batch_size, **options):
        models_with_fields = [model for model in apps.get_models() if self.fields_of(model._meta)]
        if check:
            problems = sum(self.check_model(model, batch_size) for model in models_with_fields)
            if problems:
                raise CommandError(f'{problems} values not {self.OK}.')
        else:
            for model in models_with_fields:
                self.write_rows(model, batch_size)

    def check_model(self, model, batch_size):
        fields = self.fields_of(model._meta)
        counts = {field: Counter() for field in fields}
        for row, tokens in stored_rows(model, fields, 'pk', *self.others(fields), batch_size=batch_size):
            for field, token in tokens.items():
                state = self.state(field, row, token)
                counts[field][state] += 1
                if state not in (self.OK, self.MENDED):
                    self.stdout.write(f'{model._meta.label}.{field.name}: the row with pk {row.pk!r} is {state}')
        for field, count in counts.items():
            states = ', '.join(f'{count[state]} {state}' for state in self.STATES)
            self.stdout.write(f'{model._meta.label}.{field.name}: {count.total()} rows, {states}')
        return sum(count.total() - count[self.OK] for count in counts.values())

    def write_rows(self, model, batch_size):
        fields = self.fields_of(model._meta)

        def rebuilt(row):
            obj = model(pk=row.pk)
            for field in fields:
                setattr(obj, field.attname, self.mended(field, row))
            return obj

        names = [field.name for field in fields]
        # Only the fields are written, so a pair that disagrees keeps both its values.
        rewrite(self.stdout, self.to_mend(model, fields), [*names, *self.others(fields)], names, rebuilt, batch_size)


def stored_rows(model, fields, *others, batch_size):
    """Each row of ``model``, as ``(row, tokens)``: ``row`` has the ``others`` as they load, and
    ``tokens`` each of ``fields`` as stored rather than unsealed, its column cast to plain text.
    """
    stored = {f'stored_{field.name}': Cast(field.name, models.TextField()) for field in fields}
    rows = model._base_manager.order_by().annotate(**stored).values_list(*others, *stored, named=True)
    for row in rows.iterator(chunk_size=batch_size):
        yield row, {field: getattr(row, f'stored_{field.name}') for field in fields}


def rewrite(stdout, rows, read, written, rebuilt, batch_size):
    """Write the ``written`` fields of ``rows`` again, a locked batch per transaction.

    Rows are read as values of the ``read`` fields, not as instances, so a pair that disagrees
    doesn't stop it, though a token no key decrypts does. ``rebuilt(row)`` gives the instance to
    write back. Stopping it and running it again is safe.
    """
    model = rows.model
    rows = rows.order_by('pk')
    done = 0
    last_pk = None
    while True:
        with transaction.atomic():
            batch = rows if last_pk is None else rows.filter(pk__gt=last_pk)
            batch = list(batch.select_for_update().values_list('pk', *read, named=True)[:batch_size])
            if not batch:
                break
            model._base_manager.bulk_update([rebuilt(row) for row in batch], written)
        done += len(batch)
        last_pk = batch[-1].pk
        stdout.write(f'{model._meta.label}: {done} rows written')
    stdout.write(f'{model._meta.label}: done, {done} rows written')
