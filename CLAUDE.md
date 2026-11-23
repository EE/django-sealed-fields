# CLAUDE.md

This repository is public.
Work on it often starts from a private project that uses it,
so nothing from such a project goes in here: no names, models, field names, data, incidents or links to its docs —
not in code, tests, docs or commit messages.
Examples use made-up models (`Invitation`).

## Running tests

The README's Development section says how.
Run both databases before committing:
the fixtures create tables outside a transaction because SQLite insists on it, which PostgreSQL alone would never show.

## The token format is frozen

Deployments store tokens made by this code, so the key derivation (`HKDF_INFO`) and both token layouts never change.
`test_the_token_format_stays_put` holds them;
if it fails, the change is wrong, not the test.

## Writing

The README owns why and how to use it; docstrings own how the code works; neither repeats the other.
Prose — README, `TODO.md`, docstrings, comments — breaks at clause boundaries, one sentence per line, not at a column.

`TODO.md` holds deferred work, a paragraph each, concrete enough to pick up cold.
A finished item is deleted in the change that finishes it.
