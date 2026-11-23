# django-sealed-fields

Encrypting a column does not stop the people who run the application from reading it:
the application has to decrypt the column to use it,
so whoever can deploy code or open a shell next to its configuration can read every value.
What encryption changes is that the database alone stops being enough.
A dump on a laptop, a backup, a read-only SQL login, a replica or an SQL injection
yields ciphertext without the key.

This app gives Django text fields sealed that way,
and keeps them sealed inside the application too:
a value leaves only where code says `reveal()`.

```python
from django_sealed_fields.fields import SealedTextField


class Invitation(models.Model):
    code = SealedTextField(purpose='invitation-code', searchable=True, unique=True)
    pin = SealedTextField(purpose='invitation-pin', blank=True)
```

```python
>>> invitation = Invitation.objects.get(code='9F3K-22QX-L7WD')
>>> invitation.code
<Sealed>
>>> f'Your code is {invitation.code}'
TypeError: A Sealed gives its value only to reveal().
>>> invitation.code.reveal()
'9F3K-22QX-L7WD'
```

## The idea

- **A sealed value leaves on purpose or not at all.**
  The attribute holds a `Sealed`, whether the instance was loaded or the value assigned.
  `str()`, formatting, `+`, `==` against text and pickling raise `TypeError`,
  so a value cannot slip into a log line, an error report, a cache or a task queue.
  `reveal()`, and the `reveal` template filter, are the ways out,
  and a search for `reveal` finds every place a value leaves the application.
- **Declaring a field is the only registration.**
  The system checks and the commands find every sealed field through Django's app registry,
  so a key rotation cannot miss one.
- **Every claim about the stored data can be checked.**
  `reseal --check` says whether every value is under the current key,
  `seal --check` whether every plain column has been moved into its sealed one.
  Each step of a rotation or a move ends with one of them,
  and each names, by pk, the rows that don't load and need a person.
- **What it cannot answer, it refuses.**
  A lookup the stored values cannot answer raises `FieldError` from `filter()` rather than matching nothing,
  an index that could find nothing fails the system checks,
  and a value no key unseals stops the page that loads it rather than reading as empty.

## Install

It is not on PyPI yet; depend on a commit of this repository:

```
django-sealed-fields @ git+https://github.com/EE/django-sealed-fields.git@<sha>
```

Add `'django_sealed_fields'` to `INSTALLED_APPS`, and give it a key:

```python
SEALED_FIELDS_KEY = env.str('SEALED_FIELDS_KEY', default='')
SEALED_FIELDS_KEY_FALLBACKS = env.list('SEALED_FIELDS_KEY_FALLBACKS', default=[])
```

A key is a random string of at least 32 characters, kept apart from `SECRET_KEY`.
The length check counts characters, not entropy, so generate it, never make one up:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

**Losing the key loses every sealed value**, and a database backup is useless without it.
Keep a copy outside the place the application runs.

## Declaring fields

`SealedTextField(purpose=..., searchable=False, ...)` takes the options of a `TextField`.

`purpose` is a fixed string, unique across the project,
bound into every token as associated data,
so a token copied into another column does not unseal there.
A system check (`django_sealed_fields.E001`) refuses two fields sharing one.
It is not the column name, so renaming a field changes nothing.

`searchable=True` seals deterministically: the same value gives the same token in that field,
so equal values are visible as equal, as through any index on them.
Every other field puts a random nonce in front, so equal values look different.
`''` is stored as `''` and `None` as `NULL` in any field,
so a blank `NOT NULL` column stays as it was.

A lookup compares what is stored,
so a field answers `exact`, `in` and `isnull` for the values it stores the same way every time:
blank and null in any field, and any value in a searchable one.
`filter(code=...)` and `UniqueConstraint` work as they are, and the database never needs the key.
Anything else raises `FieldError`,
and an index or a unique constraint on a field that isn't searchable fails a system check (`django_sealed_fields.E002`).
In the admin, name the lookup: `search_fields = ['code__exact']`,
since a bare name searches with `icontains` and `=code` with `iexact`.

`purpose` and `searchable` are part of every token the field has stored:
changing either leaves the column unreadable,
so treat it as a new field and move the values into it.

Tokens are keyed, so a dump alone allows no dictionary attack.
Someone who can both put values into a searchable column and read a dump can, though:
insert a guess, see whether its token matches another row.
So **a column outsiders can put values into is searchable only if every value in it is high-entropy,
and a PIN never is**: a searchable four-digit PIN falls to ten thousand inserted rows.

`max_length` is checked by validation, as on a `CharField`, and limits nothing in the database.

In a form the field shows its value revealed,
so give it only to a form whose every viewer may see it.

## Reading a value

```python
send_mail(subject, f'Your code is {invitation.code.reveal()}', ...)
```

```django
{% load django_sealed_fields %}
{{ invitation.code|reveal }}
```

`bool()` and `== ''` say whether a value is blank,
and two `Sealed` compare by value, which is all Django's own validation asks of them.
Lookups and assignments take text or a `Sealed` alike.

## Rotating a key

Every key, `SEALED_FIELDS_KEY` and the fallbacks, is tried when unsealing and when looking up;
only `SEALED_FIELDS_KEY` seals.
Processes don't pick up a configuration change all at once,
so a rotation takes three changes, each of which every process can live with next to the one before:

1. Set `SEALED_FIELDS_KEY_FALLBACKS=<new>`.
   Everything can now read the new key, and everything still writes with the old one.
2. In one change, set `SEALED_FIELDS_KEY=<new>` and `SEALED_FIELDS_KEY_FALLBACKS=<old>`:
   writes move to the new key.
   Then run `manage.py reseal`, and `manage.py reseal --check` until it passes.
3. Unset `SEALED_FIELDS_KEY_FALLBACKS`: the old key goes.

Skipping step 1 would leave a process still on the old configuration unable to read what the others write.

`reseal` rewrites every sealed field in every row, a locked batch per transaction (`--batch-size`, 500 by default),
so it can be stopped and run again.

Between steps 2 and 3 the same value can sit in a searchable column under both keys, as two tokens.
Lookups and Django's model validation try every key, so they still see the two as equal;
a unique constraint compares tokens and does not.
Find duplicates with a lookup before inserting, and leave the constraint as the backstop for a concurrent insert.

A key shorter than 32 characters never seals but is still read with,
so what it protects can be resealed under a better one.
A missing or short key is a warning (`django_sealed_fields.W001`, `W002`), not an error:
which part of a project is of use without it, the app can't know.

## Moving a plain column in

Encrypting a column that already holds data is a rollout, not a migration.
The `django_sealed_fields.pairing` app, installed for its duration and removed after, carries it:

```python
INSTALLED_APPS = [..., 'django_sealed_fields', 'django_sealed_fields.pairing']
```

```python
from django_sealed_fields.pairing.fields import PairedFieldsMixin, PairedSealedTextField


class Invitation(PairedFieldsMixin, models.Model):
    code = models.CharField(max_length=20, unique=True)
    code_sealed = PairedSealedTextField(purpose='invitation-code', searchable=True, plain='code', null=True)
```

A pair holds one value:
setting either attribute sets both, and every save writes both columns.
A row whose sealed column is still null loads its value from the plain one,
since it was written before the sealed field existed;
any other row whose columns disagree does not load (`PairMismatchError`).
Something wrote such a row around the pair —
`QuerySet.update()`, `bulk_update()` naming one field of a pair, or raw SQL —
so `seal --check` lists it and `seal` leaves it for whoever knows which column is right.

1. **Expand.** Add the paired field, nullable, and deploy.
   Every write from then on fills both columns.
   Run `manage.py seal` to seal the rows written before, then `manage.py seal --check`.
2. **Read from the sealed field.** Lookups, display and writes move to it.
   A unique constraint on the sealed column can stand beside the plain one's:
   under one key a value has one token, so the two agree.
   Before deploying, `seal --check` must pass.
3. **Soak** for as long as it takes to trust it, and rehearse a key rotation and a restore from backup meanwhile.
4. **Contract.** In one migration, turn the pair into a `SealedTextField` and then drop the plain column —
   in that order, since earlier migrations name the paired field, which needs its plain one —
   and remove `django_sealed_fields.pairing` from `INSTALLED_APPS`.
   From here on the key is the only way to read the values.

Rolling back the expand step leaves the release before it writing only the plain column,
so a value it changes in a sealed row leaves the pair disagreeing.
Before deploying again, set the sealed column to `NULL`, and `seal` takes those rows from the plain one.

Dropping a column only hides it: its values stay on disk until the rows are rewritten
(in PostgreSQL, `VACUUM FULL` or `pg_repack`).
They also stay in backups and write-ahead logs until those expire,
so the date plain copies are gone is the contract's deploy date plus their retention, not the deploy date.

## What a token gives away

- Its length: the value's length plus 16 bytes, plus 16 more for the nonce.
- Which key made it, to whoever holds the keys, and nothing to anyone else.
  A token carries no format version; a later format can be tried after the current one, as the keys are,
  and `reseal` rewrites every row into it.
- Nothing tying it to its row.
  Someone who can write to the database but has no key can move a token to another row of the same column,
  and the application will show it there.
  That attacker can as easily move the row itself;
  binding tokens to rows would need the row's primary key in `from_db_value`, which Django doesn't pass,
  and which an insert doesn't have yet.

## Error reports

No stack frame in this app holds a key, or one derived from it, as a local of its own:
the keys travel in an object whose `repr` is only their count,
which is all an error reporter like Sentry sends of it.
That asks nothing of the reporter's configuration.

A value is safe in a frame for as long as it is `Sealed`.
Once revealed, it is text like any other:
in this app's own frames on its way in and out of the database (`unsealed`, the lookups),
and in your code's locals, request bodies and partner responses under whatever name it has there.
Drop the locals of `django_sealed_fields` frames in the reporter, and scrub your own; this app cannot see them.

## Deliberately not here

- **Partial matching, ordering and ranges.**
  Anything the database could compute on its own, whoever holds a dump could compute too.
- **Unsealing in SQL.** The database never sees the key.
- **Reading plain text as if it were sealed.**
  A value no key unseals is an error, not a fallback; moving plain columns in is what `pairing` is for.
- **Types other than text.** Store a number or a date as its text and convert it at the edges.
- **A key management service.** Keys come from settings; where those come from is the deployment's business.

## What it assumes

- That the keys reach every process through settings, and nowhere else.
- That writes go through the ORM.
  Raw SQL stores the text it is given, unsealed, in a column the application then cannot load.

## Compared with other libraries

Read in their source and documentation in November 2026, not run;
versions as read, and any of it may have changed since.

| Library | The value in memory | Asking for equality | A value that won't decrypt | Changing keys | Encrypting a live column |
|---|---|---|---|---|---|
| **django-sealed-fields** | `Sealed`, out only through `reveal()` | `exact`/`in` on a searchable field, blank and null on any; anything else refused | raises | `reseal`, and `reseal --check` over every row | paired columns, `seal --check` over every row |
| [django-fernet-encrypted-fields](https://github.com/jazzband/django-fernet-encrypted-fields) 0.4 | plain | not supported, not refused | reads as the stored text | key list; re-saving every object, documented | – |
| [django-encrypted-field](https://github.com/patowc/django-encrypted-field) 1.1 | plain | not supported, not refused; `unique` refused | raises, or `None` for a value not in its format | single key | – |
| [django-tink-fields](https://pypi.org/project/django-tink-fields/) 0.5 | plain | `exact` on deterministic (AES-SIV) fields; anything else refused | raises | Tink keysets; rewriting rows left to you | documented |
| [django-crypto-fields](https://github.com/erikvw/django-crypto-fields) 1.2 | plain; template filter masks it | `exact`/`in` through a hash, ciphertext in a table of its own | raises | – | – |
| [django-pgcrypto](https://github.com/dcwatson/django-pgcrypto) 3.1 | plain | most lookups, decrypted in SQL with the key sent to the database | a value not in its format reads as itself | per-field key | mixed columns read |
| [django-secured-fields](https://pypi.org/project/django-secured-fields/) 0.5 | plain | `exact`/`in` through a hash stored with the ciphertext; anything else refused | reads as the stored text | key list | – |
| [django-field-encryption](https://pypi.org/project/django-field-encryption/) 0.2 | plain; admin masks it | `exact` through a separate HMAC column; anything else refused | raises, or reads as the stored text when not strict | key ids and a rewriting command | documented; non-strict reads plain text |
| [Rails Active Record Encryption](https://guides.rubyonrails.org/active_record_encryption.html) 8.1 | plain; filtered from `inspect` and parameter logs | equality on deterministic attributes; other queries just don't match | raises | key list; `record.encrypt` per record | `support_unencrypted_data`, `extend_queries` |
| [CipherSweet](https://github.com/paragonie/ciphersweet) (PHP) 4.11 | plain; parameters redacted from stack traces | blind indexes | throws | rotators, `needsReEncrypt()` per row | – |

Three ways to ask an encrypted column for equality run through that list.
A blind index — a keyed hash in a column of its own (CipherSweet, django-field-encryption, django-crypto-fields) —
keeps the ciphertext randomised, for a second column, a second key, and a write that must keep the two in step.
Decrypting in SQL (django-pgcrypto) answers any lookup, by handing the database the key.
Deterministic encryption (here, django-tink-fields, Rails) makes the ciphertext its own index,
and pays for it in equal values looking equal; see [Declaring fields](#declaring-fields) for where that is safe.

What no other library on the list does:

- **Keep a value sealed after it is decrypted.**
  Everywhere else the attribute is plain text from the moment the row loads.
  Rails filters encrypted attributes out of `inspect` and parameter logs,
  CipherSweet out of PHP stack traces,
  and django-crypto-fields and django-field-encryption mask them in templates and the admin;
  each covers the routes it names, where `Sealed` refuses every route but `reveal()`.
- **Check every row.**
  Several rotate keys, and CipherSweet can tell whether one row needs it,
  but none has a check that goes through the table and fails unless every value is under the current key,
  or unless a column being encrypted has caught up — the step a deploy can wait on.
- **Refuse, at every boundary, what it cannot answer.**
  django-tink-fields, django-crypto-fields, django-secured-fields and django-field-encryption refuse unsupported lookups too,
  and django-tink-fields, Rails and CipherSweet raise on a value that won't decrypt.
  The rest let a lookup match nothing or a failed decryption read as the stored text,
  which looks the same as no data.

Where others go further:

- **Keys in a key management service.** django-tink-fields wraps its keyset with a KMS key,
  and Rails takes envelope encryption and custom key providers.
  Here keys come from settings.
- **Binding a ciphertext to its column, and to its row.**
  CipherSweet derives a key per table and field, and can mix a row's columns into the associated data.
  Here `purpose` binds a token to its field; nothing binds it to its row (see [What a token gives away](#what-a-token-gives-away)).
- **Reading plain text during a migration.**
  Rails reads unencrypted values transparently and can query both forms.
  Here a column being encrypted is kept as a pair until it has caught up,
  so a value that won't decrypt is always an error and never a fallback.
- **Types other than text**, which most of the others offer.
- **Refusing to start without keys.**
  django-crypto-fields stops the application when its keys are missing, or have moved.
  Here a missing key is a warning, since which part of a project works without it the app can't know.

## Token format

The URL-safe base64 of AES-SIV (RFC 5297) output,
under a 64-byte key derived from the configured one with HKDF-SHA256.
A searchable token is `siv(value, [purpose])`;
any other is `nonce ‖ siv(value, [purpose, nonce])` with a random 16-byte nonce.
`django_sealed_fields/fields.py` has the details, and a test holds the format still.

## Development

```bash
poetry install
poetry run pytest
poetry run flake8
```

The tests run on PostgreSQL by default (`POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`),
and on SQLite with `TEST_DATABASE=sqlite`.
