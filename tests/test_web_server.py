"""Tests for the web GUI server API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from remove_ai_watermarks.web.server import create_app

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
SAMPLE_JPG = SAMPLE_DIR / "lenovo-1.jpg"


@pytest.fixture()
def client():
    """Create a test client with a fresh app instance."""
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_image() -> bytes:
    """Read sample image bytes, skip if not available."""
    if not SAMPLE_JPG.exists():
        pytest.skip("Sample image not available")
    return SAMPLE_JPG.read_bytes()


def _upload(client: TestClient, name: str = "test.jpg", data: bytes | None = None) -> str:
    """Helper: upload an image and return the id."""
    if data is None:
        # Create a minimal 10x10 red PNG
        import cv2
        import numpy as np

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, :] = (0, 0, 255)  # BGR red
        _, buf = cv2.imencode(".jpg", img)
        data = buf.tobytes()

    res = client.post("/api/upload", files={"files": (name, data, "image/jpeg")})
    assert res.status_code == 200
    result = res.json()
    assert len(result) == 1
    return result[0]["id"]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestUpload:
    def test_upload_single(self, client):
        img_id = _upload(client)
        assert len(img_id) == 12

    def test_upload_multiple(self, client):
        import cv2
        import numpy as np

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", img)
        data = buf.tobytes()

        res = client.post(
            "/api/upload",
            files=[
                ("files", ("a.jpg", data, "image/jpeg")),
                ("files", ("b.jpg", data, "image/jpeg")),
            ],
        )
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_upload_with_real_sample(self, client, sample_image):
        img_id = _upload(client, "lenovo.jpg", sample_image)
        assert len(img_id) == 12


class TestListImages:
    def test_empty_list(self, client):
        res = client.get("/api/images")
        assert res.status_code == 200
        assert res.json() == []

    def test_list_after_upload(self, client):
        _upload(client)
        res = client.get("/api/images")
        assert res.status_code == 200
        images = res.json()
        assert len(images) == 1
        assert images[0]["status"] == "pending"


class TestGetOriginal:
    def test_get_original(self, client):
        img_id = _upload(client)
        res = client.get(f"/api/images/{img_id}/original")
        assert res.status_code == 200
        assert len(res.content) > 0

    def test_get_thumbnail(self, client):
        img_id = _upload(client)
        res = client.get(f"/api/images/{img_id}/original?thumb=1")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/jpeg"

    def test_get_nonexistent(self, client):
        res = client.get("/api/images/nonexistent123/original")
        assert res.status_code == 404


class TestDetect:
    def test_detect_clean_image(self, client):
        """Detection on a plain red image should return no detections."""
        img_id = _upload(client)
        res = client.post(f"/api/detect/{img_id}")
        assert res.status_code == 200
        detections = res.json()
        assert isinstance(detections, list)
        # A plain red image should have no detected watermarks
        fired = [d for d in detections if d["detected"]]
        assert len(fired) == 0

    def test_detect_real_sample(self, client, sample_image):
        """Detection on a real Lenovo watermarked image should find the mark."""
        img_id = _upload(client, "lenovo.jpg", sample_image)
        res = client.post(f"/api/detect/{img_id}")
        assert res.status_code == 200
        detections = res.json()
        fired = [d for d in detections if d["detected"]]
        # Should detect the Lenovo mark
        assert any(d["key"] == "lenovo" for d in fired)

    def test_detect_nonexistent(self, client):
        res = client.post("/api/detect/nonexistent123")
        assert res.status_code == 404


class TestProcess:
    def test_process_auto(self, client):
        """Process a plain image with auto-detect (no watermark found = unchanged)."""
        img_id = _upload(client)
        res = client.post(f"/api/process/{img_id}?mark=auto")
        assert res.status_code == 200
        assert res.json()["status"] == "done"

    def test_process_specific_mark(self, client, sample_image):
        """Process a real image targeting a specific watermark."""
        img_id = _upload(client, "lenovo.jpg", sample_image)
        res = client.post(f"/api/process/{img_id}?mark=lenovo")
        assert res.status_code == 200
        assert res.json()["status"] == "done"

    def test_process_with_regions(self, client):
        """Process with manual region erase."""
        img_id = _upload(client)
        res = client.post(f"/api/process/{img_id}?regions=0,0,5,5")
        assert res.status_code == 200

    def test_process_invalid_region(self, client):
        img_id = _upload(client)
        res = client.post(f"/api/process/{img_id}?regions=0,0")
        assert res.status_code == 400

    def test_process_force(self, client):
        """Force removal even without detection."""
        img_id = _upload(client)
        res = client.post(f"/api/process/{img_id}?mark=lenovo&force=true")
        assert res.status_code == 200

    def test_process_nonexistent(self, client):
        res = client.post("/api/process/nonexistent123")
        assert res.status_code == 404


class TestGetResult:
    def test_get_result_after_process(self, client):
        img_id = _upload(client)
        client.post(f"/api/process/{img_id}?mark=auto")
        res = client.get(f"/api/images/{img_id}/result")
        assert res.status_code == 200
        assert len(res.content) > 0

    def test_get_result_before_process(self, client):
        img_id = _upload(client)
        res = client.get(f"/api/images/{img_id}/result")
        assert res.status_code == 404


class TestDownload:
    def test_download_single(self, client):
        img_id = _upload(client)
        client.post(f"/api/process/{img_id}?mark=auto")
        res = client.get(f"/api/download/{img_id}")
        assert res.status_code == 200
        assert "attachment" in res.headers.get("content-disposition", "")

    def test_download_all(self, client):
        img_id = _upload(client)
        client.post(f"/api/process/{img_id}?mark=auto")
        res = client.get("/api/download-all")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/zip"

    def test_download_all_empty(self, client):
        res = client.get("/api/download-all")
        assert res.status_code == 404


class TestDelete:
    def test_delete_image(self, client):
        img_id = _upload(client)
        res = client.delete(f"/api/images/{img_id}")
        assert res.status_code == 200
        assert res.json()["status"] == "deleted"

        # Should be gone now
        res = client.get("/api/images")
        assert res.json() == []

    def test_delete_nonexistent(self, client):
        res = client.delete("/api/images/nonexistent123")
        assert res.status_code == 404


class TestIndexPage:
    def test_serves_html(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Remove AI Watermarks" in res.text
