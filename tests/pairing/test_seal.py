import pytest
from django.core.management import CommandError, call_command

from django_sealed_fields.fields import ciphers, encrypt
from django_sealed_fields.pairing.fields import AGREE, DISAGREE, NOT_SEALED_YET, PairedSealedTextField
from django_sealed_fields.pairing.management.commands.seal import UNREADABLE, classify
from django_sealed_fields.sealed import Sealed


OTHER_KEY = 'another-sealing-key-of-enough-length'


def test_seals_the_rows_that_predate_their_sealed_field(Pair):
    Pair.objects.create(plain='P')
    Pair.objects.update(paired=None)
    with pytest.raises(CommandError):
        call_command('seal', check=True)

    call_command('seal', batch_size=1)

    assert Pair.objects.get().paired == Sealed('P')
    call_command('seal', check=True)


def test_a_pair_drifted_apart_is_reported_and_left_for_a_person(Pair):
    """Something wrote one column around the pair; seal can't know which one is right."""
    pair = Pair.objects.create(plain='P')
    Pair.objects.update(plain='Q')

    with pytest.raises(CommandError, match='1 values not sealed yet, not unsealing, or disagreeing'):
        call_command('seal', check=True)
    call_command('seal')
    with pytest.raises(CommandError):
        call_command('seal', check=True)
    assert Pair.objects.filter(pk=pair.pk, plain='Q', paired='P').exists()


def test_a_rotation_leaves_every_pair_agreeing(Pair, settings):
    """reseal knows nothing of pairs, and rewrites only the sealed field of each."""
    Pair.objects.create(plain='P')

    settings.SEALED_FIELDS_KEY_FALLBACKS = [settings.SEALED_FIELDS_KEY]
    settings.SEALED_FIELDS_KEY = OTHER_KEY
    call_command('reseal')
    settings.SEALED_FIELDS_KEY_FALLBACKS = []

    call_command('seal', check=True)
    assert (Pair.objects.get().paired, Pair.objects.get().plain) == (Sealed('P'), 'P')


@pytest.mark.parametrize('searchable', [True, False])
def test_classify(settings, searchable):
    f = PairedSealedTextField(purpose='test', searchable=searchable, plain='plain')
    under_old_key = encrypt(ciphers()[0], 'X', f.purpose, searchable)
    settings.SEALED_FIELDS_KEY_FALLBACKS = [settings.SEALED_FIELDS_KEY]
    settings.SEALED_FIELDS_KEY = OTHER_KEY
    x = encrypt(ciphers()[0], 'X', f.purpose, searchable)

    def outcome(plain, stored):
        return classify(f, plain, stored)

    assert outcome(None, None) == AGREE
    assert outcome('', '') == AGREE
    assert outcome('X', x) == AGREE
    assert outcome('X', under_old_key) == AGREE
    assert outcome('X', None) == NOT_SEALED_YET
    assert outcome('', None) == NOT_SEALED_YET
    assert outcome('X', 'not a token') == UNREADABLE
    assert outcome('X', encrypt(ciphers()[0], 'X', 'other', searchable)) == UNREADABLE
    assert outcome('Y', x) == DISAGREE
    assert outcome('', x) == DISAGREE
    assert outcome(None, x) == DISAGREE
    assert outcome(None, '') == DISAGREE
    assert outcome('X', '') == DISAGREE


def test_sealing_one_pair_leaves_another_that_disagrees_as_it_is(Pair):
    Pair.objects.create(plain='P', other='O')
    Pair.objects.update(paired=None, other='drifted')

    call_command('seal')

    assert Pair.objects.values_list('paired', 'other', 'other_paired').get() == (Sealed('P'), 'drifted', Sealed('O'))
