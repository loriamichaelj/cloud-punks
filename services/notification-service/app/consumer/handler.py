"""Handlers for the events that become notifications (DESIGN.md section 6).

Dedupe is the store's conditional put, so a redelivered event stores nothing and is reported as
a duplicate. The SQS message is deleted by the consumer only after this returns.
"""

from pydantic import BaseModel

from app.domain.notifications import NotificationService
from retail_common.errors import PoisonMessage
from retail_common.events.consumer import HandlerOutcome
from retail_common.events.envelope import Envelope


class NotificationHandler:
    def __init__(self, service: NotificationService) -> None:
        self._service = service

    def __call__(self, envelope: Envelope, data: BaseModel) -> HandlerOutcome:
        try:
            stored = self._service.record(envelope, data)
        except ValueError as exc:  # an event type we registered but cannot describe
            raise PoisonMessage(str(exc)) from exc
        return HandlerOutcome.PROCESSED if stored else HandlerOutcome.DUPLICATE
