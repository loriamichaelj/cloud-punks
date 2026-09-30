"""inventory-service settings; service-specific variables are added as milestones need them."""

from retail_common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "inventory-service"
