"""Build the low-stock-alert Lambda package: a zip with handler.py at its root.

    python3 scripts/package_lambda.py [OUTPUT]       # default: dist/low-stock-alert.zip

Terraform reads this file (``filename`` and ``source_code_hash`` on the function), so the "Platform"
workflows run this script before ``terraform plan`` and again before ``terraform apply``. The plan
and the apply run on different machines, so the zip cannot be made by Terraform itself: a file a
data source writes during the plan would not exist where the saved plan is applied.

The output must be byte-identical every time or the saved plan no longer matches the file at apply
time. So the entry has a fixed timestamp (the ZIP epoch) and a fixed mode, and is stored without
compression: deflate output can differ between zlib versions, and a 3 KB file gains nothing from it.
The handler uses the standard library only, so there is nothing to install into the package.
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "functions" / "low-stock-alert" / "handler.py"
DEFAULT_OUTPUT = ROOT / "dist" / "low-stock-alert.zip"
# The handler string is handler.lambda_handler, so the module sits at the root of the zip.
ENTRY = "handler.py"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # the ZIP epoch
UNIX_REGULAR_FILE_0644 = (0o100000 | 0o644) << 16
UNIX = 3  # create_system: tells unzip to honour the mode above on every platform


def build(source: Path = SOURCE, output: Path = DEFAULT_OUTPUT) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"the Lambda source is missing: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    info = zipfile.ZipInfo(ENTRY, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = UNIX_REGULAR_FILE_0644
    info.create_system = UNIX
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(info, source.read_bytes())
    return output


def main(argv: list[str]) -> int:
    output = Path(argv[0]) if argv else DEFAULT_OUTPUT
    try:
        print(build(output=output))
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
