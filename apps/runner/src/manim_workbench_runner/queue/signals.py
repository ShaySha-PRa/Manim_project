"""The deliberately tiny Redis payload contract for render-job wake-ups."""

from uuid import UUID


class JobSignalDecodeError(ValueError):
    """Raised when a Redis signal is not exactly one canonical ASCII UUID."""


def encode_job_signal(job_id: UUID) -> bytes:
    """Encode one job ID without any contextual or sensitive information."""
    if not isinstance(job_id, UUID):
        raise TypeError("job_id must be a UUID")
    return str(job_id).encode("ascii")


def decode_job_signal(payload: bytes) -> UUID:
    """Decode only the lower-case, hyphenated UUID representation produced above."""
    if type(payload) is not bytes:
        raise TypeError("Redis job signal must be bytes")
    try:
        encoded_job_id = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise JobSignalDecodeError("Redis job signal must be ASCII") from error

    try:
        job_id = UUID(encoded_job_id)
    except (AttributeError, ValueError) as error:
        raise JobSignalDecodeError("Redis job signal must be a UUID") from error

    if encoded_job_id != str(job_id):
        raise JobSignalDecodeError("Redis job signal must be a canonical UUID")
    return job_id
