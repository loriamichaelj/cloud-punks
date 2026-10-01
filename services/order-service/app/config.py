"""order-service settings (DESIGN.md section 8). Everything comes from the environment.

Three processes share one image and need different variables, so each gets its own class and a
missing variable fails only the process that needs it:

* ``DatabaseSettings`` - the ``migrate`` job (runs as ``order_owner``);
* ``Settings`` - the API (runs as ``order_app``): also needs the two upstream URLs. It never talks
  to the event bus: events leave only through the outbox relay;
* ``RelaySettings`` - the relay: also needs AWS and the bus name, but no upstream URLs.
"""

from pydantic import Field

from retail_common.config import AwsSettings
from retail_common.database import DatabaseSettings as CommonDatabaseSettings


class DatabaseSettings(CommonDatabaseSettings):
    service_name: str = "order-service"


class Settings(DatabaseSettings):
    product_service_url: str = Field(min_length=1)
    inventory_service_url: str = Field(min_length=1)


class RelaySettings(DatabaseSettings, AwsSettings):
    event_bus_name: str = Field(min_length=1)
    # How often the stuck-order sweeper looks (section 8: 60 s). Compose shortens it so the
    # drill sees the gauge move within seconds; the 5 minute threshold is not configurable.
    sweep_interval_s: float = Field(default=60.0, gt=0)


class ConsumerSettings(DatabaseSettings, AwsSettings):
    """The consumer reads one queue and writes only to PostgreSQL: its events leave through the
    outbox, so unlike the inventory consumer it needs no event-bus name."""

    queue_name: str = Field(min_length=1)
