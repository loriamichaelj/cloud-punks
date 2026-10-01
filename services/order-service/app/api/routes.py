"""HTTP routes for order-service (DESIGN.md section 4). Handlers are sync: the stores are too."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.api.schemas import (
    CustomerId,
    IdempotencyKey,
    OrderCreate,
    OrderId,
    OrderOut,
    OrderPageOut,
)
from app.domain.service import OrderService

router = APIRouter(prefix="/api/v1")


def get_service(request: Request) -> OrderService:
    service: OrderService = request.app.state.order_service
    return service


Service = Annotated[OrderService, Depends(get_service)]


@router.post("/orders", response_model=OrderOut, status_code=202)
def create_order(
    body: OrderCreate,
    response: Response,
    service: Service,
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
) -> OrderOut:
    """202 with the order in PENDING; the same key and body again returns the original (200)."""
    result = service.create_order(body.customer_id, idempotency_key, body.lines())
    if not result.created:
        response.status_code = 200
    response.headers["Location"] = f"/api/v1/orders/{result.order.order_id}"
    return OrderOut.from_domain(result.order)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: OrderId, service: Service) -> OrderOut:
    return OrderOut.from_domain(service.get_order(order_id))


@router.get("/orders", response_model=OrderPageOut)
def list_orders(
    service: Service,
    customer_id: Annotated[CustomerId, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OrderPageOut:
    return OrderPageOut.from_domain(service.list_orders(customer_id, page, size))
