"""Web GUI server for remove-ai-watermarks.

Provides a browser-based interface for uploading images, selecting watermark
types, previewing before/after results, and downloading cleaned images.

Requires the ``[web]`` extra::

    pip install 'remove-ai-watermarks[web]'
"""

from __future__ import annotations

from remove_ai_watermarks.web.server import create_app, run_server

__all__ = ["create_app", "run_server"]
