"""Watermark removal model profiles, the default strength, and profile detection.

Pure configuration and lookup functions with no ML dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
CTRLREGEN_MODEL_ID = "yepengliu/ctrlregen"

# Vendor-adaptive default denoising strength for the SDXL img2img scrub, overridable
# from the CLI (`--strength`). The right strength depends on which vendor's SynthID is
# present, detected from the C2PA issuer (metadata.synthid_source). Oracle-verified
# controlled study (2026-06-01, clean v0.8.6 with protect_text/faces OFF, per-image
# openai.com/verify or Gemini-app verdict; see docs/synthid.md section 2.2):
#   - OpenAI gpt-image: removed at 0.05 across 1024-1600 (n=4), resolution-independent.
#     OPENAI_STRENGTH 0.10 = the 0.05 floor plus a 2x margin (keeps quality high).
#   - Google Gemini: removed at 0.15 on the capped-1536 path (n=4); 0.05/0.10 do NOT
#     clear. GEMINI_STRENGTH 0.15. CAVEAT: 0.15 was validated only on
#     `--max-resolution 1536`; native 2816 (the default path) was not locally
#     measurable (OOM on Apple Silicon) and may need more -- pending GPU validation on
#     the raiw.cc backend. If a native large Gemini still verifies positive at 0.15,
#     raise `--strength`.
#   - Unknown vendor (metadata stripped, or non-OpenAI/Google C2PA): UNKNOWN_STRENGTH
#     0.15, the safe middle that clears both vendors at the tested resolutions.
# The dominant factor is VENDOR, not resolution: Google's SynthID is ~3x more robust
# than OpenAI's. The earlier single 0.30 default (and the "resolution dependence" lore)
# came from contaminated tests run with protect_text ON -- see docs/synthid.md 2.2.
OPENAI_STRENGTH = 0.10
GEMINI_STRENGTH = 0.15
UNKNOWN_STRENGTH = 0.15
# Backwards-compatible alias: the vendor-unknown default (what a caller gets without a
# detected vendor). Kept as DEFAULT_STRENGTH for existing references.
DEFAULT_STRENGTH = UNKNOWN_STRENGTH

# Detected-vendor -> default strength. Vendor strings come from `vendor_for_strength`.
_VENDOR_STRENGTH = {"openai": OPENAI_STRENGTH, "google": GEMINI_STRENGTH}

# CtrlRegen removes watermarks by regenerating from (near) clean Gaussian noise,
# NOT by the light-touch partial-noise img2img the SDXL default uses. The research
# is explicit (CtrlRegen, ICLR 2025, arXiv:2410.05470): partial-noise regeneration
# "struggles with high-perturbation watermarks" because a small noise step "retains"
# watermark information that diffuses back into the output; the fix is to start from
# clean noise. With the StableDiffusionControlNetImg2ImgPipeline that maps to a high
# strength (~1.0 = full noise at the first timestep, structure held by the canny
# ControlNet + DINOv2 IP-Adapter, not by the watermarked latent). So the ctrlregen
# profile must NOT inherit the SDXL default (`DEFAULT_STRENGTH`, a partial-noise
# value) -- at that low strength it loads ControlNet + DINOv2-giant and then barely
# changes the image (a no-op for removal). Tunable via
# `--strength`; lower it to trade removal strength for fidelity (the CtrlRegen+ regime).
#
# EXPERIMENTAL -- NOT recommended for production. The same GPU study that set the 0.3
# SDXL threshold tested ctrlregen at its clean-noise strength and found it DESTROYS
# images: smooth/background regions fill with hallucinated micro-text garbage, and it
# is heavy (~8.5 min / ~$0.30 vs ~25 s / ~$0.02 for SDXL on a large image). The pipeline
# is effectively binary -- low strength = no-op, high strength = destroys -- with no
# usable middle, so the literature's "clean-noise is the lever" (arXiv:2410.05470) did
# NOT survive empirical testing on real content. SDXL img2img at ~0.3 is the shippable
# path; ctrlregen stays opt-in and flagged experimental.
CTRLREGEN_DEFAULT_STRENGTH = 1.0


def resolve_strength(strength: float | None, profile: str, vendor: str | None = None) -> float:
    """Resolve the denoising strength, applying the profile/vendor default when unset.

    ``None`` means "the user did not pass ``--strength``". ``ctrlregen`` resolves to
    ``CTRLREGEN_DEFAULT_STRENGTH`` (clean-noise regeneration). The SDXL default profile
    resolves **vendor-adaptively**: ``vendor`` (``"openai"`` / ``"google"`` / None, from
    ``vendor_for_strength``) selects ``OPENAI_STRENGTH`` / ``GEMINI_STRENGTH`` /
    ``UNKNOWN_STRENGTH``. An explicit value always wins (including ``0.0`` -- the check is
    ``is None``, not falsiness). Shared by the CLI (for display) and the engine (for
    execution) so the two never disagree -- both must pass the SAME ``vendor``.
    """
    if strength is not None:
        return strength
    if profile == "ctrlregen":
        return CTRLREGEN_DEFAULT_STRENGTH
    return _VENDOR_STRENGTH.get(vendor or "", UNKNOWN_STRENGTH)


def vendor_for_strength(image_path: Path) -> Literal["openai", "google"] | None:
    """Detect the SynthID vendor for strength selection: ``"openai"`` / ``"google"`` / None.

    Reads the C2PA SynthID proxy (``metadata.synthid_source``) on the ORIGINAL input,
    so it must run before any pass that strips metadata. When both issuers appear (a
    rare multi-sign anomaly) Google wins -- the more-robust watermark -> safer (higher)
    strength. Returns None when metadata is stripped or the issuer is neither vendor,
    which maps to ``UNKNOWN_STRENGTH``. Lazy-imports ``metadata`` to keep this module
    dependency-light.
    """
    try:
        from remove_ai_watermarks.metadata import synthid_source

        src = (synthid_source(image_path) or "").lower()
    except Exception:  # metadata unreadable -> treat as unknown vendor
        return None
    if "google" in src:
        return "google"
    if "openai" in src:
        return "openai"
    return None


def get_model_id_for_profile(profile: str) -> str:
    """Map CLI model profile names to concrete Hugging Face model IDs."""
    normalized = profile.strip().lower()
    if normalized == "default":
        return DEFAULT_MODEL_ID
    if normalized == "ctrlregen":
        return CTRLREGEN_MODEL_ID
    raise ValueError(f"Unknown model profile '{profile}'. Use one of: default, ctrlregen.")


def detect_model_profile(model_id: str) -> str:
    """Infer model profile from model identifier."""
    if "ctrlregen" in model_id.lower():
        return "ctrlregen"
    return "default"
