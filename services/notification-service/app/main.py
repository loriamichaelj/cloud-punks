"""notification-service FastAPI application."""

from app.config import Settings
from retail_common.service import create_service_app

settings = Settings()
app = create_service_app(settings)
