"""PostgreSQL unavailable while Valkey is fine: the 'database down' drill, in-process."""

from conftest import CATEGORY, UP_URL, _env
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repo.products import PostgresProductRepository
from retail_common.database import build_engine


def dead_repository() -> PostgresProductRepository:
    """A repository whose database nothing listens on (connection refused)."""
    settings = Settings(
        db_host="127.0.0.1",
        db_port=1,
        db_name="product_db",
        db_user="product_app",
        db_password=_env("PRODUCT_APP_PASSWORD"),  # type: ignore[arg-type]
        cache_url=UP_URL,
    )
    return PostgresProductRepository(build_engine(settings))


def test_database_outage_is_a_503_not_a_500_and_cached_reads_survive(
    up_client: TestClient, sku: str
) -> None:
    up_client.post(
        "/api/v1/products", json={"sku": sku, "name": "x", "category": CATEGORY, "price": "5"}
    )
    up_client.get(f"/api/v1/products/{sku}")  # warm the cache while PostgreSQL is still up

    # PostgreSQL goes away.
    service = up_client.app.state.product_service  # type: ignore[attr-defined]
    service._repository = dead_repository()

    cached = up_client.get(f"/api/v1/products/{sku}")
    uncached = up_client.get("/api/v1/products/ITEST-NEVER-CACHED")
    write = up_client.post(
        "/api/v1/products",
        json={"sku": f"{sku}-w", "name": "x", "category": CATEGORY, "price": "5"},
    )

    assert cached.status_code == 200  # served by the cache
    assert uncached.status_code == 503
    assert uncached.headers["Retry-After"] == "1"
    assert uncached.json()["error"]["code"] == "STORE_UNAVAILABLE"
    assert write.status_code == 503
    assert "127.0.0.1" not in uncached.text  # no connection details leak to the client


def test_a_dead_database_makes_the_service_unready_but_not_unlive() -> None:
    from retail_common.database import ping
    from retail_common.health import ReadinessCheck

    repository = dead_repository()
    engine = repository._engine
    app = create_app(
        Settings(
            db_host="127.0.0.1", db_port=1, db_name="product_db", db_user="product_app",
            db_password=_env("PRODUCT_APP_PASSWORD"),  # type: ignore[arg-type]
            cache_url=UP_URL,
        ),
        repository=repository,
        readiness_probes=(ReadinessCheck("postgres", lambda: ping(engine)),),
    )  # fmt: skip
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200
