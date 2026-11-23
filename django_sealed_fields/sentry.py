"""Keep the locals of this package's frames out of what Sentry is sent.

A frame here may hold a value revealed on its way in or out of the database.
Only this package's frames lose their locals:
the names a value goes by in a project's own code are the project's to scrub.
It reads the event as Sentry's protocol lays it out, so it imports nothing of the SDK.
"""


PACKAGE = f'{__package__}.'


def drop_frame_locals(event, hint=None):
    """Usable as ``before_send``, or called from one."""
    for frame in _frames(event):
        if (frame.get('module') or '').startswith(PACKAGE):
            frame.pop('vars', None)
    return event


def _frames(event):
    for interface in ('exception', 'threads'):
        for value in (event.get(interface) or {}).get('values') or []:
            yield from (value.get('stacktrace') or {}).get('frames') or []
    yield from (event.get('stacktrace') or {}).get('frames') or []
