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
    """Remove the visible Lenovo "AI生成" watermark (locate -> mask -> reverse-alpha)."""

    def __init__(self) -> None:
        super().__init__(_CONFIG)
