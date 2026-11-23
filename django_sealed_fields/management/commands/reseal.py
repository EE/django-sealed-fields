"""Reseal every sealed field under ``SEALED_FIELDS_KEY``, or check with ``--check`` that every one is.

Declaring a ``SealedTextField`` is all it takes: this finds every one through the app registry.
Resealing rewrites every sealed field in every row, a batch per transaction,
so it can be stopped and run again; it is the middle step of a key rotation.
Run ``--check`` before removing a key from ``SEALED_FIELDS_KEY_FALLBACKS``.
"""
from ...fields import DecryptionError, sealed_fields_of
from ...rows import UNREADABLE, RowsCommand


CURRENT = 'under SEALED_FIELDS_KEY'
OLDER = 'under an older key'


def key_of(field, token):
    """Which key made a stored ``token``; a blank or null one needs none, so counts as current."""
    if not token:
        return CURRENT
    try:
        _value, key = field.opened(token)
    except DecryptionError:
        return UNREADABLE
    return CURRENT if key == 0 else OLDER


class Command(RowsCommand):
    help = 'Reseal every sealed field of every model under SEALED_FIELDS_KEY, or check it with --check.'
    OK, MENDED, STATES = CURRENT, OLDER, (OLDER, UNREADABLE)

    def fields_of(self, opts):
        return sealed_fields_of(opts)

    def state(self, field, row, token):
        return key_of(field, token)

    def to_mend(self, model, fields):
        return model._base_manager.all()

    def mended(self, field, row):
        return getattr(row, field.name)
