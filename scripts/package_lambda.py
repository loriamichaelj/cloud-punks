"""Build the Lambda packages: low-stock-alert and market-activity-email, one zip each.

    python3 scripts/package_lambda.py [OUTPUT_DIR]      # default: dist/

``low-stock-alert.zip`` holds ``handler.py`` at its root. ``market-activity-email.zip`` holds its
``handler.py`` and, under ``art/``, the 100 CloudPunk SVGs from ``nft-collection/`` that it draws
the email's picture from (the art has one home, so the package takes it from there at build time).

Terraform reads these files (``filename`` and ``source_code_hash`` on each function), so the
"Platform" workflows run this script before ``terraform plan`` and again before ``terraform
apply``. The plan and the apply run on different machines, so the zips cannot be made by Terraform
itself: a file a data source writes during the plan would not exist where the saved plan is applied.

The output must be byte-identical every time or the saved plan no longer matches the file at apply
time. So every entry has a fixed timestamp (the ZIP epoch) and a fixed mode, entries are in a fixed
order, and nothing is compressed: deflate output can differ between zlib versions. Both handlers use
the standard library (and the runtime's boto3) only, so there is nothing to install.
"""

import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "functions" / "low-stock-alert" / "handler.py"
EMAIL_SOURCE = ROOT / "functions" / "market-activity-email" / "handler.py"
ART = ROOT / "nft-collection"
DIST = ROOT / "dist"
DEFAULT_OUTPUT = DIST / "low-stock-alert.zip"
EMAIL_OUTPUT_NAME = "market-activity-email.zip"
# The handler string is handler.lambda_handler, so the module sits at the root of the zip.
ENTRY = "handler.py"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # the ZIP epoch
UNIX_REGULAR_FILE_0644 = (0o100000 | 0o644) << 16
UNIX = 3  # create_system: tells unzip to honour the mode above on every platform


def write_zip(entries: Sequence[tuple[str, Path]], output: Path) -> Path:
    """A reproducible zip of ``(name in the archive, source file)`` pairs, in the order given."""
    for _, source in entries:
        if not source.is_file():
            raise FileNotFoundError(f"the Lambda source is missing: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for name, source in entries:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = UNIX_REGULAR_FILE_0644
            info.create_system = UNIX
            archive.writestr(info, source.read_bytes())
    return output


def build(source: Path = SOURCE, output: Path = DEFAULT_OUTPUT) -> Path:
    """The low-stock-alert package."""
    return write_zip([(ENTRY, source)], output)


def build_email(
    output: Path = DIST / EMAIL_OUTPUT_NAME, source: Path = EMAIL_SOURCE, art: Path = ART
) -> Path:
    """The market-activity-email package: the handler and every CloudPunk's SVG under art/."""
    svgs = sorted(art.glob("*.svg"))
    if len(svgs) != 100:
        raise FileNotFoundError(f"expected the 100 CloudPunk SVGs in {art}, found {len(svgs)}")
    return write_zip([(ENTRY, source), *[(f"art/{svg.name}", svg) for svg in svgs]], output)


def main(argv: list[str]) -> int:
    directory = Path(argv[0]) if argv else DIST
    try:
        print(build(output=directory / DEFAULT_OUTPUT.name))
        print(build_email(output=directory / EMAIL_OUTPUT_NAME))
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
