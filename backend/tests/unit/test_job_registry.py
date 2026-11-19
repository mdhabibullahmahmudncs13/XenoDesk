"""Every job type the scheduler can write must have a handler.

A missing handler is not a loud failure: the worker marks the job ``failed`` and moves
on, so the feature the job drives silently never runs. This is the cheap guard.
"""

import pytest

import xenovarients.jobs.handlers  # noqa: F401 — importing registers the handlers
from xenovarients.jobs.runner import handlers
from xenovarients.models.platform import JobType


@pytest.mark.parametrize("job_type", [member.value for member in JobType])
def test_every_job_type_has_a_handler(job_type: str) -> None:
    assert job_type in handlers(), f"no handler registered for job type {job_type!r}"


def test_the_scheduler_aliases_share_one_implementation() -> None:
    """The aliases exist so the enum's own names work; they are not second copies."""
    assert handlers()[JobType.inventory_poll.value] is handlers()["restock_detection"]
    assert handlers()[JobType.restock_batch_dispatch.value] is handlers()["retry_delivery"]
