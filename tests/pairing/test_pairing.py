"""A sealed field paired with a plain one: one value, two columns."""
import pytest
from django.db import connection, models
from django.test.utils import isolate_apps

from django_sealed_fields.pairing.fields import PairedFieldsMixin, PairedSealedTextField, PairMismatchError
from django_sealed_fields.sealed import Sealed


def columns(Pair, pk):
    """The plain value as stored, and whether the sealed one is there."""
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT plain, paired FROM {Pair._meta.db_table} WHERE id = %s', [pk])
        plain, token = cursor.fetchone()
    return plain, token is not None


def test_setting_either_field_sets_both_as_each_holds_it(Pair):
    pair = Pair()

    pair.paired = 'E'
    assert (pair.paired, pair.plain) == (Sealed('E'), 'E')
    pair.plain = 'P'
    assert (pair.paired, pair.plain) == (Sealed('P'), 'P')
    pair.plain = Sealed('Q')
    assert (pair.paired, pair.plain) == (Sealed('Q'), 'Q')
    pair.paired = None
    assert pair.plain is None


def test_building_an_instance_with_either_field_gives_both_its_value(Pair):
    assert Pair(paired='E').plain == 'E'
    assert Pair(plain='P').paired == Sealed('P')
    assert Pair(plain='P', paired=Sealed('P')).plain == 'P'
    with pytest.raises(ValueError, match='plain and paired were given different values'):
        Pair(plain='P', paired='E')


@isolate_apps('django_sealed_fields.pairing')
def test_without_either_field_both_take_the_plain_ones_default():
    """Which a blank NOT NULL plain column needs: '' rather than the sealed field's None."""
    class Blank(PairedFieldsMixin, models.Model):
        secret = models.CharField(max_length=10, blank=True)
        secret_sealed = PairedSealedTextField(purpose='test-blank', plain='secret', null=True)

        class Meta:
            app_label = 'django_sealed_fields_pairing'

    assert (Blank().secret, Blank().secret_sealed) == ('', Sealed(''))


def test_every_save_writes_both_columns(Pair):
    pair = Pair.objects.create(paired='E')
    assert columns(Pair, pair.pk) == ('E', True)

    pair.paired = 'F'
    pair.save(update_fields=['paired'])
    assert columns(Pair, pair.pk) == ('F', True)

    Pair.objects.bulk_create([Pair(paired='G')])
    assert columns(Pair, Pair.objects.get(paired='G').pk) == ('G', True)


def test_a_row_from_before_the_sealed_field_loads_from_its_plain_column(Pair):
    """Between deploying the field and sealing the rows written before it."""
    pair = Pair.objects.create(plain='P')
    Pair.objects.update(paired=None)

    pair = Pair.objects.get(pk=pair.pk)
    assert (pair.paired, pair.plain) == (Sealed('P'), 'P')
    pair.save()
    assert columns(Pair, pair.pk) == ('P', True)


@pytest.mark.parametrize('split', [
    "UPDATE {table} SET plain = 'stale'",
    'UPDATE {table} SET plain = NULL',
])
def test_a_row_whose_columns_disagree_does_not_load(Pair, split):
    pair = Pair.objects.create(paired='SECRET-VALUE')
    with connection.cursor() as cursor:
        cursor.execute(split.format(table=Pair._meta.db_table))

    with pytest.raises(PairMismatchError, match=f'Pair.plain and paired disagree in the row with pk {pair.pk}') as e:
        Pair.objects.get()
    assert 'SECRET-VALUE' not in str(e.value) and 'stale' not in str(e.value)
    with pytest.raises(PairMismatchError):
        pair.refresh_from_db()


def test_a_deferred_field_loads_its_pair_with_it(Pair):
    Pair.objects.create(paired='E')

    pair = Pair.objects.only('id').get()
    assert 'paired' in pair.get_deferred_fields()
    assert (pair.paired, pair.plain) == (Sealed('E'), 'E')


@isolate_apps('django_sealed_fields.pairing')
def test_the_fields_of_a_pair_may_come_in_either_order():
    class Backwards(PairedFieldsMixin, models.Model):
        secret_sealed = PairedSealedTextField(purpose='test-backwards', plain='secret', null=True)
        secret = models.TextField()

        class Meta:
            app_label = 'django_sealed_fields_pairing'

    backwards = Backwards(secret='S')
    assert backwards.secret_sealed == Sealed('S')
    backwards.secret_sealed = 'E'
    assert backwards.secret == 'E'


@isolate_apps('django_sealed_fields.pairing')
def test_a_model_with_pairs_must_use_the_mixin():
    class Unpaired(models.Model):
        secret = models.CharField(max_length=10)
        secret_sealed = PairedSealedTextField(purpose='test-secret', plain='secret', null=True)

        class Meta:
            app_label = 'django_sealed_fields_pairing'

    class Paired(PairedFieldsMixin, models.Model):
        secret = models.CharField(max_length=10)
        secret_sealed = PairedSealedTextField(purpose='test-other-secret', plain='secret', null=True)

        class Meta:
            app_label = 'django_sealed_fields_pairing'

    def pairing_errors(model):
        return [
            (error.id, error.obj) for error in model.check()
            if error.id.startswith('django_sealed_fields_pairing.')
        ]

    assert pairing_errors(Unpaired) == [
        ('django_sealed_fields_pairing.E001', Unpaired._meta.get_field('secret_sealed')),
    ]
    assert pairing_errors(Paired) == []
