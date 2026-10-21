"""Frozen-process entry point for the local FastAPI sidecar."""

from __future__ import annotations

import os

import sys


if __name__ == "__main__":
    if "--cad-worker" in sys.argv:
        from app.cad_worker import main
        main()
        raise SystemExit(0)
    from app.server import run
    run(
        host=os.environ.get("AICS_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("AICS_API_PORT", "8765")),
    )
