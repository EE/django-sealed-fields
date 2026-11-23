A command reporting on one row, as `gc_inspect` does in django-gc,
would answer "why doesn't this row load?" without a shell holding the key:
for each sealed field of the row, whether it is blank, which key unseals it, if any,
and for a pair, its `pair_state` — never the value itself.

Error reporters send the locals of every frame, and a frame inside this app may hold a revealed value
(`unsealed`, the lookups, `seal`'s rows).
Projects using it filter those frames out themselves, by module name, in their Sentry `before_send` or scrubber.
An optional `django_sealed_fields.sentry` module offering that filter would save each project writing its own;
it would drop only this package's frame locals, not guess at names a value goes by in the project's code.

The package is not on PyPI yet, so the README asks for a commit of this repository.
`.github/workflows/pypi.yml` publishes a tag once PyPI trusts it:
a pending trusted publisher for `django-sealed-fields` naming this repository, `pypi.yml` and the environment `pypi`,
and that environment created in the repository's settings.
Then pushing `v0.1.0` publishes, and the README's install section becomes `pip install django-sealed-fields`.
