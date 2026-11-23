import pytest
from sentry_sdk.utils import event_from_exception

from django_sealed_fields.fields import DecryptionError, SealedTextField
from django_sealed_fields.sentry import drop_frame_locals


def test_an_error_inside_the_package_reaches_sentry_without_its_frames_locals():
    """``unsealed`` holds the stored token, and on success the value; the caller's frame is the caller's."""
    with pytest.raises(DecryptionError) as error:
        SealedTextField(purpose='test-sentry').unsealed('not-a-token')

    event = drop_frame_locals(*event_from_exception(error.value))

    frames = event['exception']['values'][0]['stacktrace']['frames']
    assert {(frame['module'], 'vars' in frame) for frame in frames} == {
        ('tests.test_sentry', True),
        ('django_sealed_fields.fields', False),
    }
