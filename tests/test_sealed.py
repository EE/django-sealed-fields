import copy
import pickle

import pytest
from django.template import Context, Template

from sealed_fields.sealed import Sealed


def test_only_reveal_gives_the_value():
    sealed = Sealed('ABC123')

    assert sealed.reveal() == 'ABC123'
    assert repr(sealed) == '<Sealed>'
    for way_out in (
        str,
        lambda s: f'{s}',
        lambda s: '%s' % s,
        lambda s: 'prefix/' + s,
        lambda s: pickle.dumps({'cached': [s]}),
    ):
        with pytest.raises(TypeError):
            way_out(sealed)


def test_against_text_it_says_only_whether_it_is_blank():
    """What Django asks of field values itself. Anything more would give the value away, or quietly not match."""
    assert Sealed('') == '' and Sealed('A') != '' and Sealed('A') != None  # noqa: E711
    assert Sealed('') in (None, '', [], (), {}) and Sealed('A') not in (None, '', [], (), {})
    for text in ('A', 'B'):
        with pytest.raises(TypeError):
            Sealed('A') == text
        with pytest.raises(TypeError):
            Sealed('A') in [text]


def test_sealed_values_compare_hash_and_copy_by_value():
    assert Sealed('A') == Sealed('A') != Sealed('B')
    assert {(Sealed('A'), Sealed('')): 1}[(Sealed('A'), Sealed(''))] == 1
    assert copy.deepcopy([Sealed('A')]) == [Sealed('A')]


def test_a_template_shows_it_only_through_the_filter():
    context = Context({'code': Sealed('<ABC>'), 'blank': Sealed('')})

    assert Template('{% load sealed_fields %}{{ code|reveal }}').render(context) == '&lt;ABC&gt;'
    assert Template('{% if blank %}shown{% endif %}').render(context) == ''
    with pytest.raises(TypeError):
        Template('{{ code }}').render(context)
