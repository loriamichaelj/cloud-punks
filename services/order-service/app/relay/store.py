"""PostgreSQL implementation of the relay's ``OutboxStore``."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.engine import Connection

from app.relay.core import OutboxBatch, OutboxRow
from app.repo.tables import outbox

LAST_ERROR_MAX = 512


class _Batch:
    def __init__(self, connection: Connection, rows: Sequence[OutboxRow]) -> None:
        self._connection = connection
        self.rows = rows

    def mark_published(self, ids: Sequence[int]) -> None:
        if ids:
            self._connection.execute(
                update(outbox).where(outbox.c.id.in_(ids)).values(published_at=func.now())
            )

    def mark_failed(self, failures: Mapping[int, str]) -> None:
        for row_id, error in failures.items():
            self._connection.execute(
                update(outbox)
                .where(outbox.c.id == row_id)
                .values(attempts=outbox.c.attempts + 1, last_error=error[:LAST_ERROR_MAX])
            )


class PostgresOutboxStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def claim(self, limit: int) -> Iterator[OutboxBatch]:
        with self._engine.begin() as connection:
            rows = connection.execute(
                select(outbox.c.id, outbox.c.event_id, outbox.c.payload)
                .where(outbox.c.published_at.is_(None))
                .order_by(outbox.c.id)
                .limit(limit)
                # Rows locked by another relay are skipped, so replicas never block each other.
                .with_for_update(skip_locked=True)
            ).all()
            yield _Batch(
                connection,
                [OutboxRow(id=r.id, event_id=r.event_id, payload=r.payload) for r in rows],
            )

    def delete_published_before(self, cutoff: datetime, limit: int) -> int:
        with self._engine.begin() as connection:
            doomed = (
                select(outbox.c.id)
                .where(outbox.c.published_at < cutoff)
                .order_by(outbox.c.id)
                .limit(limit)
                .scalar_subquery()
            )
            result = connection.execute(delete(outbox).where(outbox.c.id.in_(doomed)))
        return int(result.rowcount)

    def unpublished_stats(self) -> tuple[int, float | None]:
        """``(count, age in seconds of the oldest unpublished row)``; uses the partial index."""
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    func.count(),
                    func.extract("epoch", func.now() - func.min(outbox.c.created_at)),
                ).where(outbox.c.published_at.is_(None))
            ).one()
        return int(row[0]), (float(row[1]) if row[1] is not None else None)
