"""Row handling the commands share: reading tokens as stored, and rewriting rows in batches."""
from django.db import models, transaction
from django.db.models.functions import Cast


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
