from uuid import UUID, uuid4

import pytest
from manim_workbench_runner.queue.signals import (
    JobSignalDecodeError,
    decode_job_signal,
    encode_job_signal,
)


def test_signal_round_trip_is_exact_ascii_uuid() -> None:
    job_id = uuid4()

    payload = encode_job_signal(job_id)

    assert payload == str(job_id).encode("ascii")
    assert decode_job_signal(payload) == job_id


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b" 00000000-0000-0000-0000-000000000000",
        b"00000000-0000-0000-0000-000000000000 ",
        b'{"job_id":"00000000-0000-0000-0000-000000000000"}',
        b"00000000000000000000000000000000",
        b"00000000-0000-0000-0000-000000000000\n",
        b"00000000-0000-0000-0000-00000000000g",
        b"00000000-0000-0000-0000-000000000000\xff",
    ],
)
def test_signal_decoder_rejects_every_noncanonical_payload(payload: bytes) -> None:
    with pytest.raises(JobSignalDecodeError):
        decode_job_signal(payload)


def test_signal_decoder_rejects_non_bytes_and_encoder_rejects_non_uuid() -> None:
    with pytest.raises(TypeError):
        decode_job_signal(str(uuid4()))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        encode_job_signal(UUID(str(uuid4())).hex)  # type: ignore[arg-type]
