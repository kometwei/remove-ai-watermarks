"""FastAPI backend for the web GUI.

Endpoints:
  POST   /api/upload           Upload images (multipart)
  GET    /api/images           List uploaded images and their status
  GET    /api/images/{id}/original   Return original image (with optional thumb)
  POST   /api/detect/{id}      Run watermark detection, return coordinates
  POST   /api/process/{id}     Process image (remove watermark)
  GET    /api/images/{id}/result     Return processed image
  GET    /api/download/{id}    Download single result
  GET    /api/download-all     Download all results as zip
  DELETE /api/images/{id}      Remove an image
"""

from __future__ import annotations

import io
import logging
import shutil
import tempfile
import threading
import uuid
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from remove_ai_watermarks import watermark_registry
from remove_ai_watermarks.noai.constants import SUPPORTED_FORMATS

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


# ── State ────────────────────────────────────────────────────────────────────


@dataclass
class _ImageRecord:
    """In-memory record for an uploaded image."""

    id: str
    name: str
    original_path: Path
    status: Literal["pending", "processing", "done", "error"] = "pending"
    result_path: Path | None = None
    error_msg: str | None = None
    detections: list[dict[str, Any]] = field(default_factory=list)
    # Image dimensions (populated on upload)
    width: int = 0
    height: int = 0


# Module-level mutable state; reset on each server startup.
_images: dict[str, _ImageRecord] = {}
_lock = threading.Lock()
_tmp_dir: Path | None = None


def _get_tmp_dir() -> Path:
    global _tmp_dir  # noqa: PLW0603
    if _tmp_dir is None:
        _tmp_dir = Path(tempfile.mkdtemp(prefix="raw_web_"))
    return _tmp_dir


def _read_bgr(path: Path) -> np.ndarray | None:
    """Read image as BGR ndarray; returns None on failure."""
    import cv2 as _cv2

    img = _cv2.imread(str(path), _cv2.IMREAD_COLOR)
    return img


def _encode_png(image_bgr: np.ndarray) -> bytes:
    """Encode a BGR ndarray to PNG bytes."""
    ok, buf = cv2.imencode(".png", image_bgr)
    if not ok:
        raise RuntimeError("Failed to encode image")
    return buf.tobytes()


def _make_thumbnail(image_bgr: np.ndarray, max_side: int = 128) -> bytes:
    """Create a JPEG thumbnail of the image."""
    h, w = image_bgr.shape[:2]
    scale = min(max_side / h, max_side / w, 1.0)
    if scale < 1.0:
        nw, nh = int(w * scale), int(h * scale)
        image_bgr = cv2.resize(image_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("Failed to encode thumbnail")
    return buf.tobytes()


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""

    app = FastAPI(
        title="Remove AI Watermarks",
        version="0.11.2",
        docs_url=None,
        redoc_url=None,
    )

    # Mount static files (css/js/images) -- index.html is served separately
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ── Lifecycle ─────────────────────────────────────────────────────

    @app.on_event("startup")
    async def _startup() -> None:
        # Reset temp dir for each app instance (important for tests)
        global _tmp_dir  # noqa: PLW0603
        _tmp_dir = None
        _images.clear()
        _get_tmp_dir()
        logger.info("Web server temp dir: %s", _tmp_dir)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if _tmp_dir and _tmp_dir.exists():
            shutil.rmtree(_tmp_dir, ignore_errors=True)
        _images.clear()

    # ── Pages ─────────────────────────────────────────────────────────

    @app.get("/")
    async def index() -> FileResponse:
        html = _STATIC_DIR / "index.html"
        if not html.exists():
            raise HTTPException(404, "Frontend not found")
        return FileResponse(str(html), media_type="text/html")

    # ── Upload ────────────────────────────────────────────────────────

    @app.post("/api/upload")
    async def upload(files: list[UploadFile] = File(...)) -> list[dict[str, Any]]:
        results = []
        tmp = _get_tmp_dir()
        for f in files:
            suffix = Path(f.filename or "image.png").suffix.lower()
            if suffix not in SUPPORTED_FORMATS:
                continue
            img_id = uuid.uuid4().hex[:12]
            orig_path = tmp / f"{img_id}{suffix}"
            content = await f.read()
            orig_path.write_bytes(content)

            # Read dimensions
            image = _read_bgr(orig_path)
            w, h = 0, 0
            if image is not None:
                h, w = image.shape[:2]

            rec = _ImageRecord(id=img_id, name=f.filename or "image", original_path=orig_path, width=w, height=h)
            with _lock:
                _images[img_id] = rec

            results.append({"id": img_id, "name": rec.name, "width": w, "height": h})
        return results

    # ── List ──────────────────────────────────────────────────────────

    @app.get("/api/images")
    async def list_images() -> list[dict[str, Any]]:
        with _lock:
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "status": r.status,
                    "width": r.width,
                    "height": r.height,
                    "error": r.error_msg,
                    "detections": r.detections,
                }
                for r in _images.values()
            ]

    # ── Serve images ──────────────────────────────────────────────────

    @app.get("/api/images/{img_id}/original")
    async def get_original(img_id: str, thumb: int = Query(0, ge=0, le=1)) -> Response:
        rec = _get_record(img_id)
        if not rec.original_path.exists():
            raise HTTPException(404, "Original file not found")

        if thumb:
            image = _read_bgr(rec.original_path)
            if image is None:
                raise HTTPException(500, "Failed to read image")
            data = _make_thumbnail(image)
            return Response(data, media_type="image/jpeg")

        suffix = rec.original_path.suffix.lower()
        media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
            suffix, "application/octet-stream"
        )
        return FileResponse(str(rec.original_path), media_type=media)

    @app.get("/api/images/{img_id}/result")
    async def get_result(img_id: str) -> Response:
        rec = _get_record(img_id)
        if rec.status != "done" or rec.result_path is None:
            raise HTTPException(404, "No result available")
        if not rec.result_path.exists():
            raise HTTPException(404, "Result file not found")
        suffix = rec.result_path.suffix.lower()
        media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
            suffix, "application/octet-stream"
        )
        return FileResponse(str(rec.result_path), media_type=media)

    # ── Detect ────────────────────────────────────────────────────────

    @app.post("/api/detect/{img_id}")
    async def detect_watermarks(img_id: str) -> list[dict[str, Any]]:
        rec = _get_record(img_id)
        image = _read_bgr(rec.original_path)
        if image is None:
            raise HTTPException(500, "Failed to read image")

        try:
            detections = watermark_registry.detect_marks(image)
        except Exception as e:
            logger.warning("Detection failed on %s: %s", img_id, e)
            detections = []

        result = [
            {
                "key": d.key,
                "label": d.label,
                "location": d.location,
                "detected": d.detected,
                "confidence": round(d.confidence, 4),
                "region": list(d.region) if d.region else None,
            }
            for d in detections
        ]
        with _lock:
            rec.detections = result
        return result

    # ── Process ───────────────────────────────────────────────────────

    @app.post("/api/process/{img_id}")
    async def process_image(
        img_id: str,
        mark: str = Query("auto", description="Watermark mark key or 'auto'"),
        method: str = Query("reverse-alpha+inpaint", description="Processing method"),
        strip_metadata: bool = Query(True, description="Strip AI metadata from result"),
        force: bool = Query(False, description="Force removal even without detection"),
        regions: str = Query("", description="Comma-separated x,y,w,h regions for manual erase"),
    ) -> dict[str, Any]:
        rec = _get_record(img_id)

        with _lock:
            rec.status = "processing"

        try:
            image = _read_bgr(rec.original_path)
            if image is None:
                raise RuntimeError("Failed to read image")

            result: np.ndarray

            if regions:
                # Manual region erase
                from remove_ai_watermarks.region_eraser import erase

                boxes = _parse_regions(regions)
                result = erase(image, boxes=boxes, backend="cv2", dilate=3, cv2_method="ns")
            elif mark == "auto":
                # Auto-detect best mark
                from remove_ai_watermarks.cli import _remove_visible_auto

                result, _ = _remove_visible_auto(image, inpaint=True, inpaint_method="ns")
            else:
                # Specific mark
                chosen = watermark_registry.get_mark(mark)
                result, _ = chosen.remove(image, inpaint_method="ns", inpaint=True, inpaint_strength=0.85, force=force)

            # Save result
            tmp = _get_tmp_dir()
            suffix = rec.original_path.suffix.lower()
            out_suffix = suffix if suffix in {".png", ".webp", ".jpg", ".jpeg"} else ".png"
            result_path = tmp / f"{img_id}_clean{out_suffix}"
            ok, buf = cv2.imencode(out_suffix, result)
            if not ok:
                raise RuntimeError("Failed to encode result")
            result_path.write_bytes(buf.tobytes())

            # Strip metadata
            if strip_metadata:
                try:
                    from remove_ai_watermarks.metadata import remove_ai_metadata

                    remove_ai_metadata(result_path, result_path)
                except Exception as e:
                    logger.warning("Failed to strip metadata: %s", e)

            with _lock:
                rec.result_path = result_path
                rec.status = "done"

            return {"id": img_id, "status": "done", "name": rec.name}

        except HTTPException:
            raise
        except Exception as e:
            with _lock:
                rec.status = "error"
                rec.error_msg = str(e)
            raise HTTPException(500, str(e)) from e

    # ── Download ──────────────────────────────────────────────────────

    @app.get("/api/download/{img_id}")
    async def download_single(img_id: str) -> FileResponse:
        rec = _get_record(img_id)
        if rec.status != "done" or rec.result_path is None:
            raise HTTPException(404, "No result available")
        if not rec.result_path.exists():
            raise HTTPException(404, "Result file not found")
        # Use original filename
        return FileResponse(
            str(rec.result_path),
            media_type="application/octet-stream",
            filename=rec.name,
        )

    @app.get("/api/download-all")
    async def download_all() -> StreamingResponse:
        import zipfile

        done = [r for r in _images.values() if r.status == "done" and r.result_path and r.result_path.exists()]
        if not done:
            raise HTTPException(404, "No processed results to download")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for r in done:
                zf.write(str(r.result_path), r.name)  # type: ignore[union-attr]
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": "attachment; filename=results.zip"})

    # ── Delete ────────────────────────────────────────────────────────

    @app.delete("/api/images/{img_id}")
    async def delete_image(img_id: str) -> dict[str, str]:
        rec = _get_record(img_id)
        # Clean up files
        if rec.original_path.exists():
            rec.original_path.unlink()
        if rec.result_path and rec.result_path.exists():
            rec.result_path.unlink()
        with _lock:
            del _images[img_id]
        return {"status": "deleted", "id": img_id}

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_record(img_id: str) -> _ImageRecord:
    with _lock:
        rec = _images.get(img_id)
    if rec is None:
        raise HTTPException(404, f"Image not found: {img_id}")
    return rec


def _parse_regions(spec: str) -> list[tuple[int, int, int, int]]:
    """Parse ``x,y,w,h;x,y,w,h;...`` into a list of boxes."""
    if not spec.strip():
        return []
    boxes = []
    for part in spec.split(";"):
        vals = [int(v.strip()) for v in part.split(",")]
        if len(vals) != 4:
            raise HTTPException(400, f"Invalid region format: {part!r}, expected x,y,w,h")
        x, y, w, h = vals
        if w <= 0 or h <= 0:
            raise HTTPException(400, f"Region width/height must be positive: {part!r}")
        boxes.append((x, y, w, h))
    return boxes


# ── Server launcher ───────────────────────────────────────────────────────────


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """Start the uvicorn server and optionally open the browser."""
    import uvicorn

    url = f"http://{host}:{port}"
    if open_browser:
        # Open browser after a short delay so the server has started
        threading.Timer(1.5, webbrowser.open, args=[url]).start()

    print(f"  Web GUI starting at {url}")
    print(f"  Press Ctrl+C to stop.\n")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
