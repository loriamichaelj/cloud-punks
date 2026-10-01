"""HTTP routes for inventory-service (DESIGN.md section 4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.schemas import AvailabilityIn, AvailabilityOut, Sku, StockOut, StockSet
from app.domain.service import InventoryService


def get_service(request: Request) -> InventoryService:
    service: InventoryService = request.app.state.inventory_service
    return service


INVENTORY_PREFIX = "/api/v1/inventory"

Service = Annotated[InventoryService, Depends(get_service)]

router = APIRouter(prefix=INVENTORY_PREFIX)


# `/availability` is declared before `/{sku}` so the literal path is never read as a SKU.
@router.post("/availability", response_model=AvailabilityOut)
def check_availability(body: AvailabilityIn, service: Service) -> AvailabilityOut:
    """Advisory only: the reservation made from the OrderCreated event is authoritative."""
    return AvailabilityOut.from_domain(service.check_availability(body.to_domain()))


@router.get("/{sku}", response_model=StockOut)
def get_stock(sku: Sku, service: Service) -> StockOut:
    return StockOut.from_domain(service.get_stock(sku))


@router.put("/{sku}", response_model=StockOut)
def set_stock(sku: Sku, body: StockSet, service: Service) -> StockOut:
    """Admin/seed: sets ``available`` (creating the record if needed), keeps ``reserved``."""
    return StockOut.from_domain(service.set_stock(sku, body.available))
