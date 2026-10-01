"""Order-specific Prometheus metrics (DESIGN.md section 8), registered on the process registry."""

from prometheus_client import CollectorRegistry, Counter, Histogram

# Buckets around the 30 s SLO ("99% of orders terminal within 30 s").
TERMINAL_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120)


class OrderMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.orders_total = Counter(
            "orders_total",
            "Orders that reached a terminal status.",
            ["final_status"],
            registry=registry,
        )
        self.time_to_terminal = Histogram(
            "order_time_to_terminal_seconds",
            "Seconds from order creation to CONFIRMED or REJECTED.",
            buckets=TERMINAL_BUCKETS,
            registry=registry,
        )
