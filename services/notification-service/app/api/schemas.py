"""Response models for the notification API."""

from datetime import datetime

from pydantic import BaseModel

from app.domain.notifications import Notification


class NotificationOut(BaseModel):
    event_id: str
    type: str
    channel: str
    message: str
    created_at: datetime

    @classmethod
    def from_domain(cls, notification: Notification) -> "NotificationOut":
        return cls(
            event_id=notification.event_id,
            type=notification.type,
            channel=notification.channel,
            message=notification.message,
            created_at=notification.created_at,
        )


class NotificationList(BaseModel):
    items: list[NotificationOut]
