"""A sealed field paired with the plain field it replaces, until that one is dropped.

The migration half of the app: a model declaring only ``SealedTextField`` never meets anything here,
and once the last pair is gone this app leaves ``INSTALLED_APPS``.

A ``PairedSealedTextField`` names a ``plain`` field of its model, and the pair holds one value,
as text in the plain field's attribute and as a ``Sealed`` in the sealed one's.
Setting either attribute sets both, building an instance gives both the same value,
every save writes both columns, and loading a row applies ``pair_state``.
``QuerySet.update()``, ``bulk_update()`` naming one field of a pair, and raw SQL go around all of it.
The model must use ``PairedFieldsMixin``, which a system check enforces (``sealed_fields_pairing.E001``).

The pair is kept in step both ways so that code writing the plain field needs no change while the pair exists.
Keeping it one way, copying the sealed value to the plain field on save,
would drop the attribute descriptors and the ``class_prepared`` hook,
but would make every writer move to the sealed field in the deploy that adds it,
and the next save of the row would quietly undo a write that went to the plain field instead.
"""
from functools import cache

from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.db.models.query_utils import DeferredAttribute
from django.db.models.signals import class_prepared

from ..fields import SealedTextField, sealed_fields_of
from ..sealed import reveal


class PairMismatchError(Exception):
    pass


AGREE = 'agreeing'
NOT_SEALED_YET = 'not sealed yet'
DISAGREE = 'disagreeing'


def pair_state(plain, sealed):
    """How a pair stands, given its plain value and its sealed one revealed.

    The one rule: loading acts on it, and ``seal --check`` counts it.
    A sealed column may lag behind its plain one, never lead it.
    """
    if sealed is None:
        return AGREE if plain is None else NOT_SEALED_YET
    return AGREE if plain == sealed else DISAGREE


class PairedSealedTextField(SealedTextField):
    def __init__(self, *args, plain, **kwargs):
        self.plain = plain
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['plain'] = self.plain
        return name, path, args, kwargs

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        if not issubclass(self.model, PairedFieldsMixin):
            errors.append(checks.Error(
                f'{self.model._meta.label} does not use PairedFieldsMixin.',
                hint='Without it, building, loading and save(update_fields=...) can split the pair.',
                obj=self,
                id='sealed_fields_pairing.E001',
            ))
        return errors


def _held(field, value):
    """``value`` as ``field``'s attribute holds it."""
    return field.sealed(value) if isinstance(field, SealedTextField) else reveal(value)


class _PairedAttribute(DeferredAttribute):
    """The attribute of either field of a pair: setting it sets both."""

    def __init__(self, field, partner):
        super().__init__(field)
        self.partner = partner

    def __set__(self, instance, value):
        instance.__dict__[self.field.attname] = _held(self.field, value)
        instance.__dict__[self.partner.attname] = _held(self.partner, value)


def paired_fields(opts):
    """The sealed fields of a model that keep a plain field in step with them."""
    return [field for field in sealed_fields_of(opts) if isinstance(field, PairedSealedTextField)]


@cache
def pairs(opts):
    """``(plain, sealed)`` for each pair of fields of a model."""
    return tuple((opts.get_field(field.plain), field) for field in paired_fields(opts))


def _pair_attributes(sender, **kwargs):
    """Give both fields of each pair the attribute that sets both, once the model has all its fields."""
    for field in sender._meta.local_fields:
        if not isinstance(field, PairedSealedTextField):
            continue
        plain = next((other for other in sender._meta.local_fields if other.name == field.plain), None)
        if plain is None or plain is field:
            raise ImproperlyConfigured(
                f'{sender.__name__}.{field.name} pairs with {field.plain!r}, which is no other field of the model.',
            )
        setattr(sender, plain.attname, _PairedAttribute(plain, field))
        setattr(sender, field.attname, _PairedAttribute(field, plain))


class_prepared.connect(_pair_attributes)


class PairedFieldsMixin:
    """Keep each pair one value where the attributes can't: building, loading, and saving some fields."""

    def __init__(self, *args, **kwargs):
        # Django sets every field when building an instance, a default for any not given,
        # so give both fields of a pair the same one. Positional values are a whole row,
        # as from_db passes it, and agree already.
        if not args:
            for plain, sealed in pairs(self._meta):
                given = [name for name in (plain.attname, sealed.attname) if name in kwargs]
                if len(given) == 2 and reveal(kwargs[plain.attname]) != reveal(kwargs[sealed.attname]):
                    raise ValueError(
                        f'{type(self).__name__}: {plain.name} and {sealed.name} were given different values.',
                    )
                value = kwargs[given[0]] if given else plain.get_default()
                kwargs[plain.attname] = kwargs[sealed.attname] = value
        super().__init__(*args, **kwargs)

    @classmethod
    def from_db(cls, db, field_names, values, **kwargs):
        values = list(values)
        position = {name: i for i, name in enumerate(field_names)}
        pk = dict(zip(field_names, values)).get(cls._meta.pk.attname)
        for plain, sealed in pairs(cls._meta):
            if plain.attname not in position or sealed.attname not in position:
                continue
            plain_value = values[position[plain.attname]]
            state = pair_state(plain_value, reveal(values[position[sealed.attname]]))
            if state == NOT_SEALED_YET:
                # The plain column holds the value, and the instance sets both from it.
                values[position[sealed.attname]] = plain_value
            elif state == DISAGREE:
                # Neither value: they are secrets, and this message may reach an error report.
                raise PairMismatchError(
                    f'{cls._meta.label}.{plain.name} and {sealed.name} disagree in the row with pk {pk!r}. '
                    '`seal --check` lists such rows.',
                )
        return super().from_db(db, field_names, values, **kwargs)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            update_fields = set(update_fields)
            for plain, sealed in pairs(self._meta):
                pair = {plain.name, sealed.name}
                if pair & update_fields:
                    update_fields |= pair
            kwargs['update_fields'] = update_fields
        return super().save(*args, **kwargs)
