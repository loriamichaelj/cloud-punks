"""HTTP routes for product-service (DESIGN.md section 4). Handlers are sync: the stores are too."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.schemas import (
    CategoryListOut,
    CategoryOut,
    ProductCreate,
    ProductOut,
    ProductPageOut,
    ProductUpdate,
    Sku,
    Slug,
)
from app.domain.service import ProductService

router = APIRouter(prefix="/api/v1")


def get_service(request: Request) -> ProductService:
    service: ProductService = request.app.state.product_service
    return service


Service = Annotated[ProductService, Depends(get_service)]


@router.get("/products", response_model=ProductPageOut)
def list_products(
    service: Service,
    category: Annotated[Slug | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProductPageOut:
    return ProductPageOut.from_domain(service.list_products(category, page, size))


@router.get("/products/{sku}", response_model=ProductOut)
def get_product(sku: Sku, service: Service) -> ProductOut:
    return ProductOut.from_domain(service.get_product(sku))


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductCreate, service: Service) -> ProductOut:
    return ProductOut.from_domain(service.create_product(body.to_domain()))


@router.put("/products/{sku}", response_model=ProductOut)
def update_product(sku: Sku, body: ProductUpdate, service: Service) -> ProductOut:
    return ProductOut.from_domain(service.update_product(sku, body.to_domain()))


@router.get("/categories", response_model=CategoryListOut)
def list_categories(service: Service) -> CategoryListOut:
    return CategoryListOut(
        items=[CategoryOut.from_domain(category) for category in service.list_categories()]
    )
