"""Seal the plain value of each pair not sealed yet, or check every pair with ``--check``.

Declaring a ``PairedSealedTextField`` is all it takes: this finds every one through the app registry.
It writes only the rows that need it, and only their sealed columns, a batch per transaction,
so it can be stopped and run again,
and a pair that disagrees keeps both its values for whoever knows which one is right.
Which key a value is under is ``reseal``'s business.
"""
from django.db.models import Q

from ....fields import DecryptionError
from ....rows import UNREADABLE, RowsCommand
from ...fields import AGREE, DISAGREE, NOT_SEALED_YET, pair_state, paired_fields


def classify(field, plain, stored):
    """How a pair stands, given its ``plain`` value and its sealed column as ``stored``."""
    try:
        return pair_state(plain, field.unsealed(stored))
    except DecryptionError:
        return UNREADABLE


class Command(RowsCommand):
    help = "Seal each pair's plain value into its sealed field, or check every pair with --check."
    OK, MENDED, STATES = AGREE, NOT_SEALED_YET, (NOT_SEALED_YET, UNREADABLE, DISAGREE)

    def fields_of(self, opts):
        return paired_fields(opts)

    def others(self, fields):
        return sorted({field.plain for field in fields})

    def state(self, field, row, token):
        return classify(field, getattr(row, field.plain), token)

    def to_mend(self, model, fields):
        missing = Q()
        for field in fields:
            missing |= Q(**{f'{field.name}__isnull': True, f'{field.plain}__isnull': False})
        return model._base_manager.filter(missing)

    def mended(self, field, row):
        """The sealed value where there is one, the plain one where it is missing."""
        value = getattr(row, field.name)
        return getattr(row, field.plain) if value is None else value
