"""In-memory stand-ins for the notification service's ports."""

from collections.abc import Sequence

from app.config import Settings
from app.domain.errors import StoreUnavailable
from app.domain.notifications import Notification

ORDER_ID = "01J9Z6R0C4AAAAAAAAAAAAAAAA"


def make_settings() -> Settings:
    return Settings(aws_region="us-east-1")  # type: ignore[call-arg]


class FakeStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], Notification] = {}
        self.down = False

    def add(self, notification: Notification) -> bool:
        if self.down:
            raise StoreUnavailable
        key = (notification.order_id, notification.event_id)
        if key in self.rows:
            return False
        self.rows[key] = notification
        return True

    def for_order(self, order_id: str) -> Sequence[Notification]:
        if self.down:
            raise StoreUnavailable
        return sorted(
            (n for (oid, _), n in self.rows.items() if oid == order_id), key=lambda n: n.event_id
        )
