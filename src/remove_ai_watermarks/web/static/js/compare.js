/**
 * Remove AI Watermarks — Before/After Compare Slider
 *
 * Features:
 *  - Draggable slider for side-by-side comparison
 *  - Space key hold to flash original (release to show result)
 *  - Auto-fit sizing based on container dimensions
 */

const CompareSlider = (() => {
  const $ = (sel) => document.querySelector(sel);
  let sliderPos = 0.5;  // 0..1
  let dragging = false;
  let spaceHeld = false;

  function init() {
    const handle = $('#slider-handle');
    const line = $('#slider-line');
    const container = $('#compare-view');

    // Slider drag
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      dragging = true;
    });

    line.addEventListener('mousedown', (e) => {
      e.preventDefault();
      dragging = true;
      _updateSliderFromMouse(e, container);
    });

    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      _updateSliderFromMouse(e, container);
    });

    document.addEventListener('mouseup', () => {
      dragging = false;
    });

    // Space key flash
    document.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && !e.repeat && !e.target.closest('input, select, textarea')) {
        e.preventDefault();
        spaceHeld = true;
        _flashOriginal(true);
      }
    });

    document.addEventListener('keyup', (e) => {
      if (e.code === 'Space' && spaceHeld) {
        e.preventDefault();
        spaceHeld = false;
        _flashOriginal(false);
      }
    });
  }

  function _updateSliderFromMouse(e, container) {
    const rect = container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    sliderPos = Math.max(0, Math.min(1, x / rect.width));
    _applySlider();
  }

  function _applySlider() {
    const before = $('#img-before');
    const handle = $('#slider-handle');
    const line = $('#slider-line');

    const pct = sliderPos * 100;
    before.style.width = `${pct}%`;
    handle.style.left = `${pct}%`;
    line.style.left = `${pct}%`;
  }

  function _flashOriginal(show) {
    const before = $('#img-before');
    const after = $('#img-after');
    if (show) {
      // Show full original (cover entire view)
      before.style.width = '100%';
      before.style.zIndex = '3';
    } else {
      before.style.width = `${sliderPos * 100}%`;
      before.style.zIndex = '2';
    }
  }

  /**
   * Resize the compare view to fit the container (auto-fit).
   * Called after the original image loads.
   */
  function resize() {
    const container = $('#image-container');
    const view = $('#compare-view');
    const img = $('#img-original');

    if (!img.naturalWidth || !img.naturalHeight) return;

    const cw = container.clientWidth - 40;  // padding
    const ch = container.clientHeight - 40;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;

    const scale = Math.min(cw / iw, ch / ih, 1.0);

    const w = Math.round(iw * scale);
    const h = Math.round(ih * scale);

    view.style.width = `${w}px`;
    view.style.height = `${h}px`;

    // Set image sizes
    $('#img-original').style.width = `${w}px`;
    $('#img-original').style.height = `${h}px`;
    $('#img-result').style.width = `${w}px`;
    $('#img-result').style.height = `${h}px`;

    // Reset slider position
    _applySlider();
  }

  return { init, resize };
})();
