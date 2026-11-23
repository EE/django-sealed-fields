"""Text fields sealed at rest with AES-SIV (RFC 5297); the README says why, this module how.

A token is the URL-safe base64 of the AES-SIV output, under a key derived with HKDF,
with the field's ``purpose`` as associated data:

- searchable: ``siv(value, [purpose])``, the same token for the same value;
- otherwise: ``nonce || siv(value, [purpose, nonce])``, with a random 16-byte nonce.

``''`` and ``None`` are stored as themselves.
The attribute holds a ``Sealed`` (or ``None``), whether the value was loaded or assigned.
"""
import base64
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESSIV
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django import forms
from django.conf import settings
from django.core.exceptions import EmptyResultSet, FieldError, ImproperlyConfigured
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models.query_utils import DeferredAttribute
from django.utils.functional import cached_property

from .sealed import Sealed, reveal


# Room for a random secret, not a password: HKDF below adds no work factor.
MIN_SECRET_LENGTH = 32
NONCE_LENGTH = 16
# Part of the token format: every stored token was made under a key derived with it,
# so changing it leaves every one of them unreadable.
HKDF_INFO = b'encrypted fields'


class DecryptionError(Exception):
    pass


class _Keys:
    """The keys, as nothing that prints its holder can show them.

    Error reporters send a frame's locals, and a log line may hold anything;
    both print an object like this by its ``repr``, which gives only a count.
    No frame here holds a key, or one derived from it, as a local of its own,
    so keeping the keys out of reports asks nothing of the reporter.

    The sealing key comes first, then the fallbacks.
    Without a sealing key there are no keys at all:
    the fallbacks are there to finish a rotation, not to run on.
    """

    __slots__ = ('_secrets',)

    def __init__(self, key, fallbacks):
        self._secrets = (key, *fallbacks) if key else ()

    def __eq__(self, other):
        return isinstance(other, _Keys) and self._secrets == other._secrets

    def __hash__(self):
        return hash(self._secrets)

    def __repr__(self):
        return f'<{len(self._secrets)} sealing keys>'

    def __len__(self):
        return len(self._secrets)

    def key_is_short(self):
        """Whether the sealing key is too short to seal with."""
        return bool(self._secrets) and len(self._secrets[0]) < MIN_SECRET_LENGTH

    def short_fallbacks(self):
        """The positions, from 1, of the fallbacks too short to ever seal with."""
        return [i for i in range(1, len(self._secrets)) if len(self._secrets[i]) < MIN_SECRET_LENGTH]

    def derive(self, i):
        hkdf = HKDF(algorithm=hashes.SHA256(), length=64, salt=None, info=HKDF_INFO)
        return hkdf.derive(self._secrets[i].encode())


def keys():
    return _Keys(
        getattr(settings, 'SEALED_FIELDS_KEY', ''),
        getattr(settings, 'SEALED_FIELDS_KEY_FALLBACKS', []),
    )


@lru_cache
def _ciphers(keys):
    if not keys:
        raise ImproperlyConfigured('SEALED_FIELDS_KEY is empty.')
    return [AESSIV(keys.derive(i)) for i in range(len(keys))]


def ciphers():
    """One cipher per key, the sealing one first and then the fallbacks, for reading."""
    return _ciphers(keys())


def sealing_cipher():
    """The cipher of ``SEALED_FIELDS_KEY``, if it is long enough to seal with."""
    if keys().key_is_short():
        raise ImproperlyConfigured(
            f'SEALED_FIELDS_KEY is shorter than {MIN_SECRET_LENGTH} characters, '
            'so nothing is sealed with it.',
        )
    return ciphers()[0]


def encrypt(cipher, value, purpose, searchable):
    if searchable:
        sealed = cipher.encrypt(value.encode(), [purpose.encode()])
    else:
        nonce = os.urandom(NONCE_LENGTH)
        sealed = nonce + cipher.encrypt(value.encode(), [purpose.encode(), nonce])
    return base64.urlsafe_b64encode(sealed).decode()


def decrypt(cipher, token, purpose, searchable):
    """The value ``token`` holds.

    Raises ``InvalidTag`` if ``cipher`` didn't make it for ``purpose``, and ``ValueError`` if it
    isn't a token at all.
    """
    sealed = base64.urlsafe_b64decode(token)
    if searchable:
        return cipher.decrypt(sealed, [purpose.encode()]).decode()
    nonce, sealed = sealed[:NONCE_LENGTH], sealed[NONCE_LENGTH:]
    return cipher.decrypt(sealed, [purpose.encode(), nonce]).decode()


class _SealedAttribute(DeferredAttribute):
    """A sealed field's attribute: whatever it is set to, it holds a ``Sealed``."""

    def __set__(self, instance, value):
        instance.__dict__[self.field.attname] = self.field.sealed(value)


class SealedFormField(forms.CharField):
    """A form field for a sealed field: it shows the value, and compares it, revealed."""

    def prepare_value(self, value):
        return reveal(value)

    def has_changed(self, initial, data):
        return super().has_changed(reveal(initial), data)


class SealedTextField(models.TextField):
    descriptor_class = _SealedAttribute

    def __init__(self, *args, purpose, searchable=False, **kwargs):
        self.purpose = purpose
        self.searchable = searchable
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['purpose'] = self.purpose
        if self.searchable:
            kwargs['searchable'] = True
        return name, path, args, kwargs

    @cached_property
    def validators(self):
        if self.max_length is None:
            return super().validators
        return [*super().validators, MaxLengthValidator(self.max_length)]

    def formfield(self, **kwargs):
        return super().formfield(**{'form_class': SealedFormField, **kwargs})

    def sealed(self, value):
        """``value`` as the attribute holds it."""
        if value is None or isinstance(value, Sealed):
            return value
        return Sealed(self.to_python(value))

    def to_python(self, value):
        if isinstance(value, Sealed):
            return value.reveal()
        return super().to_python(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return encrypt(sealing_cipher(), value, self.purpose, self.searchable)

    def from_db_value(self, value, expression, connection):
        return self.sealed(self.unsealed(value))

    def unsealed(self, stored):
        """The value a column holds: blank or null as it is, a token from whichever key made it."""
        return self.opened(stored)[0] if stored else stored

    def opened(self, token):
        """``(value, key)``: what ``token`` holds, and the position in ``ciphers()`` of the key that made it."""
        for key, cipher in enumerate(ciphers()):
            try:
                return decrypt(cipher, token, self.purpose, self.searchable), key
            except (InvalidTag, ValueError):
                continue
        raise DecryptionError(f'{self} holds a value no key tried decrypts.')

    def tokens(self, value):
        """Every way ``value`` can be stored in this field: itself if blank, else a token per key.

        This is what lookups compare the column with,
        so a field answers for exactly the values it stores the same way every time:
        blank and null in any field, and anything else only in a searchable one.
        """
        value = self.to_python(value)
        if not value:
            return [value]
        if not self.searchable:
            raise FieldError(f'{self} is not searchable, so it can be asked only for a blank value or null.')
        return [encrypt(cipher, value, self.purpose, searchable=True) for cipher in ciphers()]

    def get_lookup(self, lookup_name):
        if lookup_name in ('isnull', 'exact', 'in'):
            return super().get_lookup(lookup_name)
        return None

    def get_transform(self, lookup_name):
        return None


class _SealedLookup(models.Lookup):
    """Match any way any of the values can be stored."""

    def plain_values(self):
        raise NotImplementedError

    def get_prep_lookup(self):
        # Here rather than in as_sql, so a value the field can't answer for is refused by filter().
        if hasattr(self.rhs, 'resolve_expression'):
            raise FieldError(f'A sealed field can only be compared with values, not {self.rhs!r}.')
        field = self.lhs.output_field
        return list(dict.fromkeys(stored for value in self.plain_values() for stored in field.tokens(value)))

    def as_sql(self, compiler, connection):
        if not self.rhs:
            raise EmptyResultSet
        lhs_sql, lhs_params = self.process_lhs(compiler, connection)
        placeholders = ', '.join(['%s'] * len(self.rhs))
        return f'{lhs_sql} IN ({placeholders})', [*lhs_params, *self.rhs]


@SealedTextField.register_lookup
class SealedExact(_SealedLookup):
    lookup_name = 'exact'

    def plain_values(self):
        return [self.rhs]


@SealedTextField.register_lookup
class SealedIn(_SealedLookup):
    lookup_name = 'in'

    def plain_values(self):
        return [value for value in self.rhs if value is not None]


def sealed_fields_of(opts):
    return [field for field in opts.concrete_fields if isinstance(field, SealedTextField)]
