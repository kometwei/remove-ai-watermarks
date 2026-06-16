"""Lenovo Tianxi "AI生成" visible watermark removal engine.

Lenovo Tianxi (联想天禧智能体 / AI修图) stamps generated images with a visible
"AI生成" text badge in the bottom-right corner -- a near-white semi-transparent
overlay with a subtle rounded-rectangle background, the same overlay class as the
Doubao / Jimeng text marks.

Removal is **reverse-alpha blending** against a captured alpha map
(``original = (wm - a*logo)/(1-a)``), always NCC-aligned to the actual mark plus a
thin residual inpaint over the glyph footprint. This is one of the four text-mark
engines that share :class:`remove_ai_watermarks._text_mark_engine.TextMarkEngine`;
this module supplies only Lenovo's tuned :class:`TextMarkConfig` (bottom-right corner,
``assets/lenovo_alpha.png`` rebuilt from the black capture via
``scripts/_analyze_lenovo.py``).
"""
# The module-level _alpha_template / _glyph_silhouette / _template_match_score below
# are thin test-facing shims (imported by tests/), so pyright's src-only pass sees them
# as unused; the use is cross-module.
# pyright: reportUnusedFunction=false

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from remove_ai_watermarks import _text_mark_engine
from remove_ai_watermarks._text_mark_engine import TextMarkConfig, TextMarkDetection, TextMarkEngine

if TYPE_CHECKING:
    from numpy.typing import NDArray

# Locate geometry as a fraction of image WIDTH (the mark scales with width, anchored
# bottom-right). The box is GENEROUSLY wider than the mark and reaches close to the
# corner so a per-image re-rasterization shift stays inside the NCC alignment search.
# The watermark is small (~8.8% width), so the locate box is ~2x to give the NCC
# alignment room to search.
WM_WIDTH_FRAC = 0.18
WM_HEIGHT_FRAC = 0.07
MARGIN_RIGHT_FRAC = 0.008
MARGIN_BOTTOM_FRAC = 0.008

# Glyph appearance: a light, low-saturation gray rendered brighter than the local
# background (white top-hat), so a white-paper document is left untouched.
# The Lenovo mark includes a subtle rounded-rectangle background plate (~alpha 0.07)
# around the text (~alpha 0.28), so the max saturation is generous.
MAX_SATURATION = 55  # max channel spread to count a pixel as "grayish"
LOGO_MIN_LUMA = 150  # glyphs are at least this bright in absolute terms
TOPHAT_DELTA = 12  # glyph must exceed the local background by this many levels

# Shape-consistent detection: match the bundled alpha glyph silhouette against the
# corner candidate via TM_CCOEFF_NORMED (keys on glyph SHAPE, not coverage).
# The mark is small (4 characters) and the real-photo NCC (0.36) is lower than
# Doubao/Jimeng because the alpha was solved from a single JPEG capture (not the
# multi-seed cubic-fit method), so the threshold is set lower. A solid blob scores
# ~0.10 and random texture ~0.15, so 0.30 still avoids false positives.
DETECT_MIN_COVERAGE = 0.02
DETECT_NCC_THRESHOLD = 0.30

# Reverse-alpha geometry, derived from the black capture at the captured width (2000).
# The alpha was solved directly from the black capture (alpha = max_channel / 255),
# which is exact for a white logo on pure black -- simpler and more precise than the
# cubic-fit gray-capture method used for Doubao/Jimeng.
_ALPHA_NATIVE_WIDTH = 2000
_ALPHA_LOGO_BGR: tuple[float, float, float] = (255.0, 255.0, 255.0)
_ALPHA_WIDTH_FRAC = 0.0930  # asset width / image width -- the alignment scale seed
_ALPHA_HEIGHT_FRAC = 0.0380
_ALPHA_MARGIN_RIGHT_FRAC = 0.0185
_ALPHA_MARGIN_BOTTOM_FRAC = 0.0185
_ALPHA_ALIGN_SEARCH = (0.75, 1.25, 31)
_RESIDUAL_ALPHA_FLOOR = 0.05
_RESIDUAL_DILATE = 5
_RESIDUAL_INPAINT_RADIUS = 2

_CONFIG = TextMarkConfig(
    name="Lenovo",
    asset_name="lenovo_alpha.png",
    corner="br",
    margin_floor=4,
    width_frac=WM_WIDTH_FRAC,
    height_frac=WM_HEIGHT_FRAC,
    margin_x_frac=MARGIN_RIGHT_FRAC,
    margin_bottom_frac=MARGIN_BOTTOM_FRAC,
    max_saturation=MAX_SATURATION,
    logo_min_luma=LOGO_MIN_LUMA,
    tophat_delta=TOPHAT_DELTA,
    morph_open_size=5,
    detect_min_coverage=DETECT_MIN_COVERAGE,
    detect_ncc_threshold=DETECT_NCC_THRESHOLD,
    alpha_width_frac=_ALPHA_WIDTH_FRAC,
    alpha_height_frac=_ALPHA_HEIGHT_FRAC,
    alpha_margin_x_frac=_ALPHA_MARGIN_RIGHT_FRAC,
    alpha_margin_bottom_frac=_ALPHA_MARGIN_BOTTOM_FRAC,
    alpha_align_search=_ALPHA_ALIGN_SEARCH,
    min_gw=8,
    alpha_logo_bgr=_ALPHA_LOGO_BGR,
    residual_alpha_floor=_RESIDUAL_ALPHA_FLOOR,
    residual_dilate=_RESIDUAL_DILATE,
    residual_inpaint_radius=_RESIDUAL_INPAINT_RADIUS,
)

# Stage-2 fallback: for watermarks on dark/medium backgrounds where the primary
# glyph mask (luma>150) filters out all candidates.  Uses a relaxed mask
# (luma>40, tophat>8, open=3) plus a try-removal verification: apply reverse-alpha
# and re-detect -- if the watermark was real, the confidence drops significantly;
# if it was noise, the confidence stays the same.  Only tried when Stage 1 fails.
_STAGE2_MIN_IMPROVEMENT = 0.10  # confidence must drop by this much to confirm

# Lenovo-specific aliases for the shared detection result/engine.
LenovoDetection = TextMarkDetection


def _alpha_template() -> NDArray[Any] | None:
    """The bundled Lenovo alpha template (float [0,1]), or None."""
    return _text_mark_engine.load_alpha_template(_CONFIG.asset_name)


def _glyph_silhouette() -> NDArray[Any] | None:
    """Binary "AI生成" silhouette (255 = glyph) from the alpha map, or None."""
    return _text_mark_engine.glyph_silhouette(_CONFIG.asset_name)


def _template_match_score(box_mask: NDArray[Any], image_width: int) -> float:
    """TM_CCOEFF_NORMED of the Lenovo glyph silhouette against ``box_mask``."""
    return _text_mark_engine.template_match_score(box_mask, image_width, _CONFIG)


class LenovoEngine(TextMarkEngine):
    """Remove the visible Lenovo "AI生成" watermark (locate -> mask -> reverse-alpha).

    Detection is two-stage: the primary config uses conservative thresholds that
    work on bright backgrounds; a Stage 2 with relaxed mask extraction plus a
    try-removal verification catches watermarks on dark/medium backgrounds without
    false-positive risk.
    """

    def __init__(self) -> None:
        super().__init__(_CONFIG)
        # Stage-2 engine: relaxed mask extraction for dark backgrounds.
        self._s2_config = TextMarkConfig(
            name=_CONFIG.name + "-S2",
            asset_name=_CONFIG.asset_name,
            corner=_CONFIG.corner,
            margin_floor=_CONFIG.margin_floor,
            width_frac=_CONFIG.width_frac,
            height_frac=_CONFIG.height_frac,
            margin_x_frac=_CONFIG.margin_x_frac,
            margin_bottom_frac=_CONFIG.margin_bottom_frac,
            max_saturation=_CONFIG.max_saturation,
            logo_min_luma=40,  # relaxed: catch glyphs on darker backgrounds
            tophat_delta=8,  # relaxed: catch subtler brightness difference
            morph_open_size=3,  # gentler: preserve finer strokes
            detect_min_coverage=_CONFIG.detect_min_coverage,
            detect_ncc_threshold=0.15,  # permissive: verified by removal test
            alpha_width_frac=_CONFIG.alpha_width_frac,
            alpha_height_frac=_CONFIG.alpha_height_frac,
            alpha_margin_x_frac=_CONFIG.alpha_margin_x_frac,
            alpha_margin_bottom_frac=_CONFIG.alpha_margin_bottom_frac,
            alpha_align_search=_CONFIG.alpha_align_search,
            min_gw=_CONFIG.min_gw,
            alpha_logo_bgr=_CONFIG.alpha_logo_bgr,
            residual_alpha_floor=_CONFIG.residual_alpha_floor,
            residual_dilate=_CONFIG.residual_dilate,
            residual_inpaint_radius=_CONFIG.residual_inpaint_radius,
        )
        self._s2_engine = TextMarkEngine(self._s2_config)

    def detect(self, image: NDArray[Any]) -> TextMarkDetection:
        """Two-stage detection: primary (safe) then Stage 2 (try-removal verify)."""
        det = super().detect(image)
        if det.detected:
            return det
        # Stage 2: relaxed mask + try-removal verification
        s2_det = self._s2_engine.detect(image)
        if s2_det.confidence < 0.15:
            return det  # nothing even with relaxed params
        # Apply reverse-alpha and check if confidence drops (watermark was real)
        amap_result = self._s2_engine._aligned_alpha_map(image)
        if amap_result is None:
            amap_result = self._s2_engine._fixed_alpha_map(image)
        if amap_result is None:
            return det
        amap, _ = amap_result
        result = self._s2_engine._apply_reverse_alpha(image, amap)
        after_det = self._s2_engine.detect(result)
        improvement = s2_det.confidence - after_det.confidence
        if improvement > _STAGE2_MIN_IMPROVEMENT:
            return s2_det  # real watermark confirmed
        return det  # false positive rejected
