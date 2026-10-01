"""The boundary that turns "PostgreSQL cannot serve this" into a domain error."""

import pytest
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.domain.errors import DuplicateSku, StoreUnavailable
from app.repo.products import _store_errors


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("connection refused")),  # down / cancelled
        InterfaceError("SELECT 1", {}, Exception("connection already closed")),
        PoolTimeoutError("QueuePool limit of size 5 overflow 5 reached"),  # pool exhausted
    ],
)
def test_connection_level_failures_become_store_unavailable(error: Exception) -> None:
    with pytest.raises(StoreUnavailable), _store_errors():
        raise error


def test_the_original_exception_is_kept_as_the_cause_for_debugging() -> None:
    original = OperationalError("SELECT 1", {}, Exception("boom"))
    with pytest.raises(StoreUnavailable) as raised, _store_errors():
        raise original
    assert raised.value.__cause__ is original


@pytest.mark.parametrize(
    "error",
    [DuplicateSku("X"), ValueError("a bug"), ProgrammingError("SELECT", {}, Exception("bad sql"))],
)
def test_everything_else_passes_through_untouched(error: Exception) -> None:
    """A real bug (or a domain error) must not be disguised as a retryable outage."""
    with pytest.raises(type(error)), _store_errors():
        raise error
