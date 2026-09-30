from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from retail_common.config import BaseServiceSettings
from retail_common.service import create_service_app


def build(settings: BaseServiceSettings) -> tuple[TestClient, CollectorRegistry]:
    registry = CollectorRegistry()
    app = create_service_app(settings, registry=registry)

    @app.get("/api/v1/orders/{order_id}")
    def get_order(order_id: str) -> dict[str, str]:
        return {"order_id": order_id}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    return TestClient(app, raise_server_exceptions=False), registry


def sample(registry: CollectorRegistry, name: str, **labels: str) -> float | None:
    return registry.get_sample_value(name, labels)


def test_route_label_is_the_template_not_the_raw_path(settings: BaseServiceSettings) -> None:
    client, registry = build(settings)

    for order_id in ("A1", "B2", "C3"):
        client.get(f"/api/v1/orders/{order_id}")

    labels = {"method": "GET", "route": "/api/v1/orders/{order_id}", "status": "200"}
    assert sample(registry, "http_requests_total", **labels) == 3
    raw_paths = [
        s.labels["route"]
        for m in registry.collect()
        for s in m.samples
        if m.name == "http_requests"
    ]
    assert not any("A1" in route for route in raw_paths)


def test_unmatched_paths_share_one_bounded_label(settings: BaseServiceSettings) -> None:
    client, registry = build(settings)

    for path in ("/nope/1", "/nope/2", "/another/3"):
        assert client.get(path).status_code == 404

    labels = {"method": "GET", "route": "unmatched", "status": "404"}
    assert sample(registry, "http_requests_total", **labels) == 3


def test_request_duration_is_observed_per_route(settings: BaseServiceSettings) -> None:
    client, registry = build(settings)
    client.get("/api/v1/orders/A1")

    labels = {"method": "GET", "route": "/api/v1/orders/{order_id}"}
    assert sample(registry, "http_request_duration_seconds_count", **labels) == 1
    assert (sample(registry, "http_request_duration_seconds_sum", **labels) or 0) > 0


def test_unhandled_exception_is_counted_as_500(settings: BaseServiceSettings) -> None:
    client, registry = build(settings)
    client.get("/boom")

    labels = {"method": "GET", "route": "/boom", "status": "500"}
    assert sample(registry, "http_requests_total", **labels) == 1


def test_wrong_method_is_counted_against_the_matched_template(
    settings: BaseServiceSettings,
) -> None:
    client, registry = build(settings)
    assert client.post("/api/v1/orders/A1").status_code == 405

    labels = {"method": "POST", "route": "/api/v1/orders/{order_id}", "status": "405"}
    assert sample(registry, "http_requests_total", **labels) == 1


def test_metrics_endpoint_serves_prometheus_text_and_is_not_self_counted(
    settings: BaseServiceSettings,
) -> None:
    client, registry = build(settings)
    client.get("/api/v1/orders/A1")

    response = client.get("/metrics")
    client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert (
        'http_requests_total{method="GET",route="/api/v1/orders/{order_id}",status="200"} 1.0'
        in (response.text)
    )
    assert 'route="/metrics"' not in response.text
    assert (
        sample(registry, "http_requests_total", method="GET", route="/metrics", status="200")
        is None
    )


def test_process_metrics_are_exposed_on_the_default_registry(settings: BaseServiceSettings) -> None:
    app = create_service_app(settings)
    text = TestClient(app).get("/metrics").text
    assert "process_cpu_seconds_total" in text or "python_gc_objects_collected_total" in text


def test_event_metrics_are_registered_with_the_documented_names(
    settings: BaseServiceSettings,
) -> None:
    app = create_service_app(settings)
    metrics = app.state.event_metrics
    metrics.published_total.labels("OrderCreated").inc()
    metrics.consumed_total.labels("OrderCreated", "duplicate").inc()

    text = TestClient(app).get("/metrics").text
    assert 'events_published_total{event_type="OrderCreated"} 1.0' in text
    assert 'events_consumed_total{event_type="OrderCreated",outcome="duplicate"} 1.0' in text
