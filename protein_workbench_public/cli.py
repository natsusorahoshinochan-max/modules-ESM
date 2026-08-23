"""Installed command-line owner for the loopback backend server."""

from __future__ import annotations

import argparse

from protein_workbench_public.bootstrap import create_application


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _loopback_host(value: str) -> str:
    if value not in _LOOPBACK_HOSTS:
        raise argparse.ArgumentTypeError(
            "server host must be a loopback address"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    """Construct and launch the installed current-protocol backend."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host",
        type=_loopback_host,
        default="127.0.0.1",
    )
    parser.add_argument("--port", type=int, default=8000)
    parsed = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        create_application(),
        host=parsed.host,
        port=parsed.port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
