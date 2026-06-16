"""Tests for the Lenovo Tianxi "AI生成" visible-watermark engine (reverse-alpha)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from remove_ai_watermarks.lenovo_engine import (
    _ALPHA_HEIGHT_FRAC,
    _ALPHA_LOGO_BGR,
    _ALPHA_MARGIN_BOTTOM_FRAC,
    _ALPHA_MARGIN_RIGHT_FRAC,
    _ALPHA_NATIVE_WIDTH,
    _ALPHA_WIDTH_FRAC,
    DETECT_NCC_THRESHOLD,
    LenovoEngine,
    _alpha_template,
    _glyph_silhouette,
    _template_match_score,
)

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples" / "lenovo-1.jpg"


class TestLocate:
    def test_box_anchored_bottom_right(self):
        eng = LenovoEngine()
        img = np.zeros((1123, 2000, 3), np.uint8)
        loc = eng.locate(img)
        assert 2000 - (loc.x + loc.w) < int(2000 * 0.03)
        assert 1123 - (loc.y + loc.h) < int(1123 * 0.03)

    def test_box_scales_with_width(self):
        eng = LenovoEngine()
        small = eng.locate(np.zeros((512, 512, 3), np.uint8))
        large = eng.locate(np.zeros((1024, 1024, 3), np.uint8))
        assert large.w == pytest.approx(small.w * 2, rel=0.1)


# ── Detection: alpha-template NCC ───────────────────────────────────


class TestDetect:
    def test_clean_gradient_not_detected(self):
        eng = LenovoEngine()
        ramp = np.tile(np.linspace(0, 255, 1024, dtype=np.uint8), (1024, 1))
        img = cv2.cvtColor(ramp, cv2.COLOR_GRAY2BGR)
        assert not eng.detect(img).detected

    def test_solid_blob_corner_not_detected(self):
        """A bright blob is not the glyph shape -> low correlation, not detected."""
        eng = LenovoEngine()
        img = np.zeros((1123, 2000, 3), np.uint8)
        x, y, bw, bh = eng.locate(img).bbox
        img[y + bh // 4 : y + bh * 3 // 4, x : x + bw // 2] = 200
        assert not eng.detect(img).detected

    def test_silhouette_loads(self):
        sil = _glyph_silhouette()
        assert sil is not None
        assert set(np.unique(sil)).issubset({0, 255})

    def test_match_score_shape_sensitive(self):
        """The glyph silhouette correlates with itself, not with a filled block."""
        sil = _glyph_silhouette()
        h, w = sil.shape
        # box that contains the silhouette -> high score
        box = np.zeros((h + 8, int(w / _ALPHA_WIDTH_FRAC * 0.2) + w), np.uint8)
        box[4 : 4 + h, 4 : 4 + w] = sil
        assert _template_match_score(box, _ALPHA_NATIVE_WIDTH) >= DETECT_NCC_THRESHOLD
        # a uniformly filled box has no glyph structure -> low score
        solid = np.full_like(box, 255)
        assert _template_match_score(solid, _ALPHA_NATIVE_WIDTH) < DETECT_NCC_THRESHOLD


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample image not present")
class TestRealSample:
    def test_detects_watermark(self):
        from remove_ai_watermarks import image_io

        det = LenovoEngine().detect(image_io.imread(SAMPLE))
        assert det.detected
        assert det.confidence >= DETECT_NCC_THRESHOLD

    def test_reverse_alpha_removes_mark(self):
        from remove_ai_watermarks import image_io

        eng = LenovoEngine()
        img = image_io.imread(SAMPLE)
        assert eng.reverse_alpha_available(img)
        out = eng.remove_watermark_reverse_alpha(img)
        assert not eng.detect(out).detected  # mark gone after recovery

    def test_far_region_untouched(self):
        from remove_ai_watermarks import image_io

        eng = LenovoEngine()
        img = image_io.imread(SAMPLE)
        out = eng.remove_watermark_reverse_alpha(img)
        h, w = img.shape[:2]
        assert np.array_equal(img[: h // 2, : w // 2], out[: h // 2, : w // 2])


# ── Reverse-alpha (exact recovery) ──────────────────────────────────


class TestReverseAlpha:
    def test_alpha_asset_loads(self):
        at = _alpha_template()
        assert at is not None
        assert at.dtype.kind == "f"
        assert float(at.min()) >= 0.0
        assert float(at.max()) <= 1.0

    def test_available_whenever_asset_present(self):
        eng = LenovoEngine()
        assert eng.reverse_alpha_available(np.zeros((1024, 1024, 3), np.uint8))
        assert eng.reverse_alpha_available(np.zeros((1123, 2000, 3), np.uint8))
        assert not eng.reverse_alpha_available(np.zeros((0, 0, 3), np.uint8))

    def test_synthetic_mark_removed(self):
        """A synthetic alpha-blended mark on a gradient is recovered within tolerance."""
        at = _alpha_template()
        if at is None:
            pytest.skip("alpha asset missing")
        h, w = 1123, 2000
        # gradient background
        bg = np.tile(np.linspace(80, 200, w, dtype=np.float32), (h, 1))
        bg = np.stack([bg, bg, bg], axis=-1).astype(np.uint8)
        # stamp the mark
        at3 = np.clip(at, 0, 1)[:, :, None]
        logo = np.array(_ALPHA_LOGO_BGR, np.float32)
        aw, ah = at.shape[1], at.shape[0]
        # place at the expected position
        ax = w - int(_ALPHA_MARGIN_RIGHT_FRAC * w) - int(_ALPHA_WIDTH_FRAC * w)
        ay = h - int(_ALPHA_MARGIN_BOTTOM_FRAC * w) - int(_ALPHA_HEIGHT_FRAC * w)
        patch = bg[ay : ay + ah, ax : ax + aw].astype(np.float32)
        blended = np.clip(patch * (1 - at3) + logo * at3, 0, 255).astype(np.uint8)
        watermarked = bg.copy()
        watermarked[ay : ay + ah, ax : ax + aw] = blended
        # reverse-alpha should recover close to the background
        eng = LenovoEngine()
        out = eng.remove_watermark_reverse_alpha(watermarked)
        # the watermark region should be closer to the background than the input
        diff_in = np.abs(watermarked[ay : ay + ah, ax : ax + aw].astype(float) - patch).mean()
        diff_out = np.abs(out[ay : ay + ah, ax : ax + aw].astype(float) - patch).mean()
        assert diff_out < diff_in
