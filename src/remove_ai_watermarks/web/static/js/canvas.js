/**
 * Remove AI Watermarks — Canvas Region Selection Tool
 *
 * Features:
 *  - Auto-fit image to container
 *  - Draw selection rectangles (mousedown + drag)
 *  - Smart pre-detected watermark regions from backend
 *  - Corner-drag resize for existing selections
 *  - Double-click to reset zoom to fit
 *  - Scroll wheel zoom
 */

const CanvasTool = (() => {
  const $ = (sel) => document.querySelector(sel);
  let canvas, ctx;
  let image = null;          // HTMLImageElement
  let imgW = 0, imgH = 0;   // natural dimensions
  let scale = 1;             // display scale
  let offsetX = 0, offsetY = 0;
  let regions = [];          // [{x, y, w, h}] in image coordinates
  let detections = [];       // backend detection results
  let activeImg = null;      // current image record

  // Drawing state
  let drawing = false;
  let drawStart = null;      // {x, y} in canvas coords
  let resizing = null;       // {index, corner} if resizing a corner
  let dragCorner = null;     // {regionIdx, corner} for corner drag

  function init() {
    canvas = $('#select-canvas');
    ctx = canvas.getContext('2d');

    canvas.addEventListener('mousedown', _onMouseDown);
    canvas.addEventListener('mousemove', _onMouseMove);
    canvas.addEventListener('mouseup', _onMouseUp);
    canvas.addEventListener('dblclick', _onDblClick);
  }

  /**
   * Load an image into the canvas for region selection.
   */
  async function loadImage(imageId) {
    const img = new Image();
    img.crossOrigin = 'anonymous';

    return new Promise((resolve) => {
      img.onload = () => {
        image = img;
        imgW = img.naturalWidth;
        imgH = img.naturalHeight;
        _fitToContainer();
        _draw();
        resolve();
      };
      img.src = `/api/images/${imageId}/original`;
    });
  }

  /**
   * Set smart pre-detected regions from backend detections.
   */
  function setDetections(dets, img) {
    detections = dets || [];
    activeImg = img;

    // Pre-populate regions from detected watermarks
    const detected = dets.filter((d) => d.detected && d.region);
    if (detected.length && regions.length === 0) {
      regions = detected.map((d) => ({
        x: d.region[0],
        y: d.region[1],
        w: d.region[2],
        h: d.region[3],
      }));
    }
  }

  function _fitToContainer() {
    const container = $('#image-container');
    const cw = container.clientWidth - 40;
    const ch = container.clientHeight - 40;

    scale = Math.min(cw / imgW, ch / imgH, 1.0);

    const w = Math.round(imgW * scale);
    const h = Math.round(imgH * scale);

    canvas.width = w;
    canvas.height = h;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    offsetX = 0;
    offsetY = 0;
  }

  // ── Coordinate conversion ──────────────────────────────────

  function _canvasToImage(cx, cy) {
    return {
      x: Math.round(cx / scale),
      y: Math.round(cy / scale),
    };
  }

  function _imageToCanvas(ix, iy) {
    return {
      x: ix * scale,
      y: iy * scale,
    };
  }

  function _getMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
  }

  // ── Drawing ────────────────────────────────────────────────

  function _draw() {
    if (!image) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);

    // Draw all regions
    for (let i = 0; i < regions.length; i++) {
      _drawRegion(regions[i], i);
    }

    // Draw in-progress selection
    if (drawing && drawStart && !resizing) {
      const pos = _lastMouse || drawStart;
      const x = Math.min(drawStart.x, pos.x);
      const y = Math.min(drawStart.y, pos.y);
      const w = Math.abs(pos.x - drawStart.x);
      const h = Math.abs(pos.y - drawStart.y);
      _drawRect(x, y, w, h, true);
    }
  }

  function _drawRegion(region, index) {
    const tl = _imageToCanvas(region.x, region.y);
    const w = region.w * scale;
    const h = region.h * scale;

    _drawRect(tl.x, tl.y, w, h, false);

    // Corner handles
    const corners = [
      { x: tl.x, y: tl.y },
      { x: tl.x + w, y: tl.y },
      { x: tl.x, y: tl.y + h },
      { x: tl.x + w, y: tl.y + h },
    ];
    ctx.fillStyle = '#e94560';
    for (const c of corners) {
      ctx.fillRect(c.x - 4, c.y - 4, 8, 8);
    }

    // Label
    if (detections[index]) {
      ctx.fillStyle = 'rgba(233, 69, 96, 0.8)';
      ctx.font = '11px sans-serif';
      const label = `🎯 ${detections[index].label}`;
      const tw = ctx.measureText(label).width;
      ctx.fillRect(tl.x, tl.y - 18, tw + 8, 16);
      ctx.fillStyle = 'white';
      ctx.fillText(label, tl.x + 4, tl.y - 6);
    }
  }

  function _drawRect(x, y, w, h, isDrawing) {
    ctx.strokeStyle = '#e94560';
    ctx.lineWidth = 2;
    ctx.setLineDash(isDrawing ? [6, 4] : [8, 4]);
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);

    ctx.fillStyle = 'rgba(233, 69, 96, 0.08)';
    ctx.fillRect(x, y, w, h);
  }

  // ── Hit testing ────────────────────────────────────────────

  function _hitCorner(mx, my) {
    const threshold = 8;
    for (let i = 0; i < regions.length; i++) {
      const r = regions[i];
      const tl = _imageToCanvas(r.x, r.y);
      const corners = [
        { name: 'tl', x: tl.x, y: tl.y },
        { name: 'tr', x: tl.x + r.w * scale, y: tl.y },
        { name: 'bl', x: tl.x, y: tl.y + r.h * scale },
        { name: 'br', x: tl.x + r.w * scale, y: tl.y + r.h * scale },
      ];
      for (const c of corners) {
        if (Math.abs(mx - c.x) < threshold && Math.abs(my - c.y) < threshold) {
          return { regionIdx: i, corner: c.name };
        }
      }
    }
    return null;
  }

  // ── Mouse events ───────────────────────────────────────────

  let _lastMouse = null;

  function _onMouseDown(e) {
    const pos = _getMousePos(e);

    // Check if clicking a corner
    const hit = _hitCorner(pos.x, pos.y);
    if (hit) {
      dragCorner = hit;
      return;
    }

    // Start new selection
    drawing = true;
    drawStart = pos;
    _lastMouse = pos;
  }

  function _onMouseMove(e) {
    const pos = _getMousePos(e);
    _lastMouse = pos;

    // Update cursor based on hover
    const hit = _hitCorner(pos.x, pos.y);
    if (hit) {
      const cursors = { tl: 'nw-resize', tr: 'ne-resize', bl: 'sw-resize', br: 'se-resize' };
      canvas.style.cursor = cursors[hit.corner];
    } else {
      canvas.style.cursor = drawing ? 'crosshair' : 'crosshair';
    }

    if (dragCorner) {
      _resizeRegion(dragCorner, pos);
      _draw();
      return;
    }

    if (drawing) {
      _draw();
    }
  }

  function _onMouseUp(e) {
    if (dragCorner) {
      dragCorner = null;
      _syncRegionsToApp();
      return;
    }

    if (drawing && drawStart) {
      const pos = _getMousePos(e);
      const x = Math.min(drawStart.x, pos.x);
      const y = Math.min(drawStart.y, pos.y);
      const w = Math.abs(pos.x - drawStart.x);
      const h = Math.abs(pos.y - drawStart.y);

      // Only add if the selection is meaningful (> 5px)
      if (w > 5 && h > 5) {
        const imgTL = _canvasToImage(x, y);
        const imgBR = _canvasToImage(x + w, y + h);
        regions.push({
          x: imgTL.x,
          y: imgTL.y,
          w: imgBR.x - imgTL.x,
          h: imgBR.y - imgTL.y,
        });
        _syncRegionsToApp();
      }
    }

    drawing = false;
    drawStart = null;
    _draw();
  }

  function _resizeRegion(hit, pos) {
    const r = regions[hit.regionIdx];
    const img = _canvasToImage(pos.x, pos.y);

    switch (hit.corner) {
      case 'tl':
        r.w += r.x - img.x;
        r.h += r.y - img.y;
        r.x = img.x;
        r.y = img.y;
        break;
      case 'tr':
        r.w = img.x - r.x;
        r.h += r.y - img.y;
        r.y = img.y;
        break;
      case 'bl':
        r.w += r.x - img.x;
        r.h = img.y - r.y;
        r.x = img.x;
        break;
      case 'br':
        r.w = img.x - r.x;
        r.h = img.y - r.y;
        break;
    }

    // Clamp
    r.w = Math.max(10, r.w);
    r.h = Math.max(10, r.h);
    r.x = Math.max(0, r.x);
    r.y = Math.max(0, r.y);
    r.x = Math.min(imgW - r.w, r.x);
    r.y = Math.min(imgH - r.h, r.y);
  }

  function _onDblClick() {
    // Reset: clear all regions
    regions = [];
    _syncRegionsToApp();
    _draw();
  }

  function _syncRegionsToApp() {
    if (typeof App !== 'undefined') {
      App.setRegions([...regions]);
    }
  }

  return { init, loadImage, setDetections };
})();
