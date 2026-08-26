import pytest
from manim_workbench_contracts import (
    CONTRACT_SCHEMA_VERSION,
    RenderJobFailureCode,
    RenderJobHeartbeat,
    RenderJobStatus,
    can_transition_render_job,
)
from pydantic import ValidationError


def test_phase5_contract_version_and_state_machine_are_frozen() -> None:
    assert CONTRACT_SCHEMA_VERSION == "1.11"
    assert can_transition_render_job(RenderJobStatus.QUEUED, RenderJobStatus.CLAIMED)
    assert can_transition_render_job(RenderJobStatus.CLAIMED, RenderJobStatus.RUNNING)
    assert can_transition_render_job(RenderJobStatus.RUNNING, RenderJobStatus.SUCCEEDED)
    assert not can_transition_render_job(RenderJobStatus.SUCCEEDED, RenderJobStatus.QUEUED)
    assert not can_transition_render_job(RenderJobStatus.CANCELLED, RenderJobStatus.RUNNING)


def test_lease_tokens_and_failure_codes_are_closed_contracts() -> None:
    heartbeat = RenderJobHeartbeat(lease_token="a" * 64, extend_seconds=30)
    assert heartbeat.extend_seconds == 30
    assert RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION.value == "sandbox_security_violation"

    with pytest.raises(ValidationError):
        RenderJobHeartbeat(lease_token="attacker-controlled", extend_seconds=30)
    with pytest.raises(ValueError):
        RenderJobFailureCode("internal_error")
