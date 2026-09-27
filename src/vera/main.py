"""Process entry point: `python -m vera.main` or `uvicorn vera.main:app --workers 1`."""

from __future__ import annotations

import os

import uvicorn

from vera.app import create_app

app = create_app()


def main() -> None:
    # One worker only: all state lives in this process (ADR-001).
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), workers=1, log_level="warning")


if __name__ == "__main__":
    main()
