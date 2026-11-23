from collections import defaultdict

from django.apps import apps
from django.conf import settings
from django.core import checks

from .fields import MIN_SECRET_LENGTH, keys, sealed_fields_of


def check_keys(app_configs=None, **kwargs):
    """W001: no ``SEALED_FIELDS_KEY``, while some model has sealed fields. W002: a key too short to seal with.

    Only warnings: which part of a project is of use without them, the app can't know.
    """
    # settings asked directly, so no frame here holds the keys as a local
    if not getattr(settings, 'SEALED_FIELDS_KEY', ''):
        users = sorted(
            f'{model._meta.label}.{field.name}'
            for model in apps.get_models() for field in sealed_fields_of(model._meta)
        )
        if not users:
            return []
        return [checks.Warning(
            f'SEALED_FIELDS_KEY is empty, so reading or writing these fails: {", ".join(users)}.',
            id='django_sealed_fields.W001',
        )]
    warnings = []
    if keys().key_is_short():
        warnings.append(checks.Warning(
            f'SEALED_FIELDS_KEY is shorter than {MIN_SECRET_LENGTH} characters, so nothing can be sealed.',
            hint='Move it to SEALED_FIELDS_KEY_FALLBACKS and generate a new SEALED_FIELDS_KEY.',
            id='django_sealed_fields.W002',
        ))
    warnings += [
        checks.Warning(
            f'Key {position} of SEALED_FIELDS_KEY_FALLBACKS is shorter than {MIN_SECRET_LENGTH} characters, '
            'so it can be unsealed with but never become SEALED_FIELDS_KEY.',
            id='django_sealed_fields.W002',
        )
        for position in keys().short_fallbacks()
    ]
    return warnings


def check_fields(app_configs=None, **kwargs):
    """E001: ``purpose`` is what keeps a token from unsealing in another field, so no two fields may share one.
    E002: a field that isn't searchable stores every value differently, so it can't key an index or a uniqueness.

    Purposes are checked across every model, whatever ``app_configs`` are given, because that is
    where a clash would be.
    """
    errors = []
    by_purpose = defaultdict(list)
    for model in apps.get_models():
        for field in sealed_fields_of(model._meta):
            by_purpose[field.purpose].append(field)
            if not field.searchable and field.name in _indexed_names(model._meta):
                errors.append(checks.Error(
                    f'{model._meta.label}.{field.name} is indexed or unique, '
                    'but every value it stores differs, so the index can find nothing.',
                    hint='Make it searchable=True, if every value it can hold is high-entropy.',
                    obj=field,
                    id='django_sealed_fields.E002',
                ))
    for purpose, fields in sorted(by_purpose.items()):
        if len(fields) > 1:
            names = ', '.join(sorted(f'{field.model._meta.label}.{field.name}' for field in fields))
            errors.append(checks.Error(
                f'{names} share the purpose {purpose!r}, so a token moved between them would still unseal.',
                obj=fields[0],
                id='django_sealed_fields.E001',
            ))
    return errors


def _indexed_names(opts):
    """The names of the fields a model indexes or holds unique, alone or with others."""
    names = {field.name for field in opts.local_fields if field.primary_key or field.unique or field.db_index}
    for together in opts.unique_together:
        names.update(together)
    for constraint_or_index in [*opts.constraints, *opts.indexes]:
        # An index names a descending field with a leading '-'.
        names.update(name.lstrip('-') for name in getattr(constraint_or_index, 'fields', ()))
    return names
