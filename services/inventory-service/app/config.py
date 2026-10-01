"""inventory-service settings (DESIGN.md section 8). Everything comes from the environment."""

from retail_common.config import AwsSettings


class Settings(AwsSettings):
    """``AWS_REGION`` is required. The endpoint (``AWS_ENDPOINT_URL``) and credentials are read
    by boto3 itself, so the same code runs against LocalStack and AWS."""

    service_name: str = "inventory-service"
