"""order-service FastAPI application (M0 stub: liveness only)."""

from fastapi import FastAPI

app = FastAPI(title="order-service")


@app.get("/health/live")
def live() -> dict[str, str]:
    """Liveness: the process answers. Checks no dependencies."""
    return {"status": "ok"}
