"""Explicit one-time Selection data-root conversion; never run at startup."""

import argparse
from pathlib import Path

from core.project.migration import convert_data_root as convert_project_data_root
from modules.selection.migration import convert_selection_workflow


def convert_data_root(source: Path, destination: Path) -> Path:
    """Convert an isolated whole-root copy while retaining all original records."""
    return convert_project_data_root(source, destination, convert_selection_workflow)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    convert_data_root(args.source, args.destination)


if __name__ == "__main__":
    main()
