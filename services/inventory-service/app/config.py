"""inventory-service settings (DESIGN.md section 8). Everything comes from the environment."""

from pydantic import Field

from retail_common.config import AwsSettings


class Settings(AwsSettings):
    """``AWS_REGION`` is required. The endpoint (``AWS_ENDPOINT_URL``) and credentials are read
    by boto3 itself, so the same code runs against LocalStack and AWS."""

    service_name: str = "inventory-service"
    # The defaults are the local names (DESIGN.md section 5); the cloud tables are prefixed loria-.
    inventory_table: str = Field(default="inventory", min_length=1)
    reservations_table: str = Field(default="inventory_reservations", min_length=1)


class ConsumerSettings(Settings):
    """The consumer process also needs its queue and the bus its outcome events go to."""

    queue_name: str = Field(min_length=1)
    event_bus_name: str = Field(min_length=1)
