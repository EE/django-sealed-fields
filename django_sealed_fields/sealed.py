class Sealed:
    """A value that gives itself up only to ``reveal()``.

    A sealed field's attribute holds one, so every place a value leaves the application says so.
    Every other way out raises ``TypeError`` rather than giving a quiet wrong answer:
    ``str()``, formatting, ``+``, ``==`` against text,
    and pickling, since a pickle in a cache or a queue would hold the text.

    It gives only what is no secret: ``repr`` is ``<Sealed>``,
    ``bool()`` and ``==`` against ``''`` say whether it is blank,
    and ``==`` against ``None`` is false, as Django asks of field values when validating.
    """

    __slots__ = ('_value',)

    def __init__(self, value):
        if not isinstance(value, str):
            raise TypeError(f'A Sealed holds text, not {type(value).__name__}.')
        self._value = value

    def reveal(self):
        return self._value

    def __repr__(self):
        return '<Sealed>'

    def __str__(self):
        raise TypeError('A Sealed gives its value only to reveal().')

    def __format__(self, format_spec):
        raise TypeError('A Sealed gives its value only to reveal().')

    def __bool__(self):
        return bool(self._value)

    def __eq__(self, other):
        if isinstance(other, Sealed):
            return self._value == other._value
        if other is None:
            return False
        if isinstance(other, str):
            if other:
                raise TypeError('A Sealed is compared with text only through reveal().')
            return not self._value
        return NotImplemented

    def __hash__(self):
        # As the value's, since a blank Sealed equals ''.
        return hash(self._value)

    def __reduce__(self):
        raise TypeError('A Sealed is not pickled: the pickle would hold its value as text.')

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def reveal(value):
    """``value`` revealed if it is ``Sealed``, and as it is if not."""
    return value.reveal() if isinstance(value, Sealed) else value
