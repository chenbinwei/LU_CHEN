"""Run the local FastAPI backend."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run("video_slicer.api.app:create_app", host=host, port=port, factory=True, reload=False)


if __name__ == "__main__":
    main()
