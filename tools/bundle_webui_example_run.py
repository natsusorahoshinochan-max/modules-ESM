"""Copy one successful real WebUI example Run into the shipped fixture."""

from __future__ import annotations

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".scratch" / "webui-example-run-generation-2"
RUN_ID = "run-b2aaed46fb5248f2aa9dc9192420c13a"
DESTINATION = ROOT / "examples" / "v2" / "webui-3gb1-run"


def main() -> None:
    shutil.copytree(
        SOURCE / "runs" / "webui-3gb1-example" / RUN_ID,
        DESTINATION / "run",
    )
    shutil.copytree(
        SOURCE / "outputs" / "webui-3gb1-example" / "objects",
        DESTINATION / "objects",
    )


if __name__ == "__main__":
    main()
