"""Guards the hermetic-environment fixture in conftest.py: a test in conftest would never run."""

import os


def test_no_aws_endpoint_or_profile_reaches_unit_tests() -> None:
    assert not [name for name in os.environ if name.startswith("AWS_ENDPOINT_URL")]
    assert "AWS_PROFILE" not in os.environ
    assert os.environ["AWS_ACCESS_KEY_ID"] == "test"  # dummy credentials, never a real key
