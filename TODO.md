A command reporting on one row, as `gc_inspect` does in django-gc,
would answer "why doesn't this row load?" without a shell holding the key:
for each sealed field of the row, whether it is blank, which key unseals it, if any,
and for a pair, its `pair_state` — never the value itself.

The package is not on PyPI, so the README asks for a commit of this repository.
Publishing takes a workflow with trusted publishing, as django-ticks has,
and a PyPI project set up to trust it;
the README's install section then becomes `pip install django-sealed-fields`.
