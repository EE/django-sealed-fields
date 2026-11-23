import pytest
from cryptography.exceptions import InvalidTag
from django.core.exceptions import FieldError, ImproperlyConfigured, ValidationError
from django.db.models import F

from sealed_fields.fields import SealedTextField, _Keys, ciphers, decrypt, encrypt, sealing_cipher
from sealed_fields.sealed import Sealed


OTHER_KEY = 'another-sealing-key-of-enough-length'


def field(searchable, purpose='test'):
    return SealedTextField(purpose=purpose, searchable=searchable)


def test_a_searchable_value_seals_alike_and_any_other_differently():
    cipher = ciphers()[0]

    assert encrypt(cipher, 'X', 'test', searchable=True) == encrypt(cipher, 'X', 'test', searchable=True)
    assert encrypt(cipher, 'X', 'test', searchable=False) != encrypt(cipher, 'X', 'test', searchable=False)


def test_the_token_format_stays_put(settings):
    """Tokens already stored must keep unsealing: the key derivation and both layouts are frozen."""
    settings.SEALED_FIELDS_KEY = 'a-fixed-key-for-the-format-test-only'

    assert field(searchable=True).tokens('X') == ['UoLNSlwNicj7XRa5m9_qG6Q=']
    assert field(searchable=False).unsealed('issPxaY_JbupNLU39rxNEUVZyNWZrMRWxkw-qKkLTvV5') == 'X'


@pytest.mark.parametrize('searchable', [True, False])
def test_a_token_does_not_unseal_for_another_purpose(searchable):
    cipher = ciphers()[0]
    token = encrypt(cipher, 'X', 'test', searchable)

    with pytest.raises(InvalidTag):
        decrypt(cipher, token, 'other', searchable)


def test_a_lookup_finds_a_value_under_every_key(settings):
    settings.SEALED_FIELDS_KEY_FALLBACKS = [settings.SEALED_FIELDS_KEY]
    settings.SEALED_FIELDS_KEY = OTHER_KEY
    new, old = ciphers()

    assert field(searchable=True).tokens('X') == [
        encrypt(new, 'X', 'test', searchable=True),
        encrypt(old, 'X', 'test', searchable=True),
    ]


def test_a_lookup_prepares_its_value_the_way_a_save_does():
    assert field(searchable=True).tokens(123456) == field(searchable=True).tokens('123456')


def test_a_field_is_asked_only_for_what_it_stores_the_same_way_each_time(Record):
    """Blank and null in any field, anything else only in a searchable one; refused by filter(), not later."""
    Record.objects.create(searchable='S', standalone='')
    Record.objects.create(searchable='T', standalone='X')

    assert Record.objects.get(standalone='').searchable == Sealed('S')
    assert Record.objects.filter(standalone__in=['', None]).count() == 1
    assert Record.objects.exclude(standalone='').get().searchable == Sealed('T')
    assert Record.objects.get(searchable__in=['T', 'U']).standalone == Sealed('X')
    with pytest.raises(FieldError, match='not searchable'):
        Record.objects.filter(standalone='X')
    with pytest.raises(FieldError, match='not searchable'):
        Record.objects.filter(standalone__in=['', 'X'])
    with pytest.raises(FieldError, match='only be compared with values'):
        Record.objects.filter(searchable=F('standalone'))
    for lookup in ('iexact', 'contains', 'startswith', 'gt', 'lower'):
        with pytest.raises(FieldError):
            Record.objects.filter(**{f'searchable__{lookup}': 'S'})


def test_without_a_key_nothing_is_read_or_written_whatever_the_fallbacks(settings):
    settings.SEALED_FIELDS_KEY_FALLBACKS = [settings.SEALED_FIELDS_KEY]
    settings.SEALED_FIELDS_KEY = ''

    with pytest.raises(ImproperlyConfigured):
        ciphers()
    with pytest.raises(ImproperlyConfigured):
        sealing_cipher()


def test_a_short_key_never_seals_but_is_read_until_rotated_away(settings):
    settings.SEALED_FIELDS_KEY = 'short'
    f = field(searchable=True)
    # A value from before the key fell short, as when MIN_SECRET_LENGTH goes up.
    old_token = encrypt(ciphers()[0], 'X', f.purpose, searchable=True)

    with pytest.raises(ImproperlyConfigured):
        f.get_prep_value('X')
    assert f.from_db_value(old_token, None, None) == Sealed('X')

    settings.SEALED_FIELDS_KEY = OTHER_KEY
    settings.SEALED_FIELDS_KEY_FALLBACKS = ['short']

    assert old_token in f.tokens('X')
    assert f.get_prep_value('X') == encrypt(ciphers()[0], 'X', f.purpose, searchable=True)


def test_the_keys_print_as_a_count_and_nothing_more():
    """What an error reporter sends of a frame holding them, Sentry's among them."""
    from sentry_sdk.serializer import serialize

    keys = _Keys(OTHER_KEY, ['yet-another-sealing-key-of-enough-length'])

    assert repr(keys) == '<2 sealing keys>'
    assert 'sealing-key' not in str(serialize({'keys': keys}))


def test_the_attribute_holds_a_sealed_whatever_it_is_given(Record):
    record = Record(searchable='S', standalone=123)
    assert (record.searchable, record.standalone) == (Sealed('S'), Sealed('123'))

    record.standalone = Sealed('')
    record.save()
    record = Record.objects.get(searchable=Sealed('S'))

    assert record.standalone == Sealed('')
    assert Record.objects.values_list('searchable', flat=True).get() == Sealed('S')
    record.searchable = None
    assert record.searchable is None


def test_model_validation_compares_sealed_values_only_as_far_as_blankness(Record):
    """Django asks a field value whether it is blank, and looks it up to check uniqueness."""
    Record.objects.create(searchable='S')

    with pytest.raises(ValidationError) as e:
        Record(searchable='S').full_clean()
    assert [error.code for error in e.value.error_dict['searchable']] == ['unique']
    Record(searchable='T', standalone='').full_clean()
    Record(searchable=Sealed('U')).full_clean()
