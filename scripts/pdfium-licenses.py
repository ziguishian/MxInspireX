from __future__ import annotations

import shutil
import sys
from importlib import metadata
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: pdfium-licenses.py OUTPUT_DIR")
    output = Path(sys.argv[1]).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    distribution = metadata.distribution("pypdfium2")
    copied = 0
    for entry in distribution.files or []:
        lowered = "/".join(entry.parts).lower()
        if "license" not in lowered and "notice" not in lowered:
            continue
        source = Path(distribution.locate_file(entry))
        if not source.is_file():
            continue
        destination = output / Path(*entry.parts[-2:])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    if copied == 0:
        raise SystemExit("pypdfium2 wheel did not expose license files")
    (output / "PACKAGE.txt").write_text(f"pypdfium2 {distribution.version}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
