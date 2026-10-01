"""HTTP routes for notification-service (DESIGN.md section 4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.schemas import NotificationList, NotificationOut
from app.domain.notifications import NotificationService

ULID_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{26}$"

router = APIRouter(prefix="/api/v1")


def get_service(request: Request) -> NotificationService:
    service: NotificationService = request.app.state.notification_service
    return service


@router.get("/notifications", response_model=NotificationList)
def list_notifications(
    order_id: Annotated[str, Query(pattern=ULID_PATTERN)],
    service: Annotated[NotificationService, Depends(get_service)],
) -> NotificationList:
    """Notifications for one order, oldest first. An unknown order has none: an empty list."""
    return NotificationList(
        items=[NotificationOut.from_domain(n) for n in service.for_order(order_id)]
    )
