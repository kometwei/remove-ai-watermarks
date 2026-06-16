/**
 * Remove AI Watermarks — Main Application Logic
 *
 * Manages global state, file uploads, file list, settings, and coordinates
 * between the compare slider and canvas selection modules.
 */

/* global CompareSlider, CanvasTool */

const App = (() => {
  // ── State ────────────────────────────────────────────────
  const state = {
    images: [],       // [{id, name, status, width, height, detections}]
    activeId: null,   // Currently previewed image id
    mode: 'compare',  // 'compare' | 'select' | 'zoom'
    zoom: 'fit',      // 'fit' | number
    detections: [],
    settings: {
      mark: 'auto',
      method: 'reverse-alpha+inpaint',
      stripMetadata: true,
      force: false,
    },
    regions: [],      // User-drawn selection regions [{x,y,w,h}]
  };

  // ── DOM refs ─────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const el = {
    uploadZone: $('#upload-zone'),
    fileInput: $('#file-input'),
    fileList: $('#file-list'),
    markSelect: $('#mark-select'),
    methodSelect: $('#method-select'),
    toggleMeta: $('#toggle-metadata'),
    toggleForce: $('#toggle-force'),
    btnProcess: $('#btn-process'),
    btnBatch: $('#btn-batch-download'),
    btnDownload: $('#btn-download'),
    emptyState: $('#empty-state'),
    compareView: $('#compare-view'),
    selectView: $('#select-view'),
    imgOriginal: $('#img-original'),
    imgResult: $('#img-result'),
    processingOverlay: $('#processing-overlay'),
    zoomInfo: $('#zoom-info'),
    infoName: $('#info-name'),
    infoSize: $('#info-size'),
    infoDetect: $('#info-detect'),
    imageContainer: $('#image-container'),
  };

  // ── Init ─────────────────────────────────────────────────
  function init() {
    _bindUpload();
    _bindSettings();
    _bindToolbar();
    _bindActions();
    _bindKeyboard();
    CompareSlider.init();
    CanvasTool.init();
  }

  // ── Upload ───────────────────────────────────────────────
  function _bindUpload() {
    el.uploadZone.addEventListener('click', () => el.fileInput.click());

    el.fileInput.addEventListener('change', (e) => {
      if (e.target.files.length) _uploadFiles(e.target.files);
      e.target.value = '';  // reset so same file can be re-uploaded
    });

    // Drag and drop
    el.uploadZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      el.uploadZone.classList.add('dragover');
    });
    el.uploadZone.addEventListener('dragleave', () => {
      el.uploadZone.classList.remove('dragover');
    });
    el.uploadZone.addEventListener('drop', (e) => {
      e.preventDefault();
      el.uploadZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) _uploadFiles(e.dataTransfer.files);
    });
  }

  async function _uploadFiles(files) {
    const formData = new FormData();
    for (const f of files) formData.append('files', f);

    try {
      const res = await fetch('/api/upload', { method: 'POST', body: formData });
      if (!res.ok) throw new Error('Upload failed');
      const data = await res.json();

      for (const item of data) {
        state.images.push({
          id: item.id,
          name: item.name,
          status: 'pending',
          width: item.width,
          height: item.height,
          detections: [],
        });
      }

      _renderFileList();
      // Auto-select the first uploaded image if nothing is active
      if (!state.activeId && state.images.length) {
        _selectImage(state.images[0].id);
      }
      _updateBatchButton();
    } catch (err) {
      console.error('Upload error:', err);
    }
  }

  // ── File List ────────────────────────────────────────────
  function _renderFileList() {
    el.fileList.innerHTML = '';
    for (const img of state.images) {
      const item = document.createElement('div');
      item.className = `file-item${img.id === state.activeId ? ' active' : ''}`;
      item.dataset.id = img.id;

      const statusIcon = {
        pending: '<span class="status-icon pending">⏳</span>',
        processing: '<span class="status-icon processing">⏳</span>',
        done: '<span class="status-icon success">✓</span>',
        error: '<span class="status-icon error" title="Failed">!</span>',
      }[img.status] || '';

      item.innerHTML = `
        <div class="thumb"><img src="/api/images/${img.id}/original?thumb=1" alt="" loading="lazy"></div>
        <div class="name" title="${img.name}">${img.name}</div>
        ${statusIcon}
      `;

      item.addEventListener('click', () => _selectImage(img.id));
      el.fileList.appendChild(item);
    }
  }

  async function _selectImage(id) {
    state.activeId = id;
    _renderFileList();

    const img = state.images.find((i) => i.id === id);
    if (!img) return;

    // Update bottom bar info
    el.infoName.innerHTML = `文件: <strong>${img.name}</strong>`;
    el.infoSize.innerHTML = `尺寸: <strong>${img.width}×${img.height}</strong>`;
    el.infoDetect.innerHTML = '检测到: <strong>--</strong>';

    // Load original image
    el.imgOriginal.src = `/api/images/${id}/original`;
    el.emptyState.style.display = 'none';

    // Run detection
    await _detectImage(id);

    // If result exists, load it
    if (img.status === 'done') {
      el.imgResult.src = `/api/images/${id}/result`;
      el.btnDownload.disabled = false;
    } else {
      el.imgResult.src = '';
      el.btnDownload.disabled = true;
    }

    _showView(state.mode);
    el.btnProcess.disabled = false;
  }

  async function _detectImage(id) {
    try {
      const res = await fetch(`/api/detect/${id}`, { method: 'POST' });
      if (!res.ok) return;
      const detections = await res.json();

      const img = state.images.find((i) => i.id === id);
      if (img) img.detections = detections;
      state.detections = detections;

      // Update bottom bar
      const fired = detections.filter((d) => d.detected);
      if (fired.length) {
        const best = fired.reduce((a, b) => (a.confidence > b.confidence ? a : b));
        el.infoDetect.innerHTML = `检测到: <strong>${best.label} (${best.confidence.toFixed(2)})</strong>`;
      } else {
        el.infoDetect.innerHTML = '检测到: <strong>无</strong>';
      }

      // Pass detections to canvas tool for smart pre-selection
      if (typeof CanvasTool !== 'undefined') {
        CanvasTool.setDetections(detections, img);
      }
    } catch (err) {
      console.error('Detection error:', err);
    }
  }

  // ── View Switching ───────────────────────────────────────
  function _showView(mode) {
    state.mode = mode;

    // Update toolbar active states
    document.querySelectorAll('.tool-btn[data-mode]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    el.compareView.style.display = 'none';
    el.selectView.style.display = 'none';

    if (!state.activeId) {
      el.emptyState.style.display = '';
      return;
    }

    el.emptyState.style.display = 'none';

    if (mode === 'compare') {
      el.compareView.style.display = '';
      // Wait for image to load then size the compare view
      el.imgOriginal.onload = () => CompareSlider.resize();
      if (el.imgOriginal.complete) CompareSlider.resize();
    } else if (mode === 'select') {
      el.selectView.style.display = '';
      CanvasTool.loadImage(state.activeId);
    } else {
      el.compareView.style.display = '';
      el.imgOriginal.onload = () => CompareSlider.resize();
      if (el.imgOriginal.complete) CompareSlider.resize();
    }

    _updateZoomInfo();
  }

  // ── Settings ─────────────────────────────────────────────
  function _bindSettings() {
    el.markSelect.addEventListener('change', (e) => {
      state.settings.mark = e.target.value;
    });

    el.methodSelect.addEventListener('change', (e) => {
      state.settings.method = e.target.value;
    });

    el.toggleMeta.addEventListener('click', () => {
      state.settings.stripMetadata = !state.settings.stripMetadata;
      el.toggleMeta.classList.toggle('on', state.settings.stripMetadata);
    });

    el.toggleForce.addEventListener('click', () => {
      state.settings.force = !state.settings.force;
      el.toggleForce.classList.toggle('on', state.settings.force);
    });
  }

  // ── Toolbar ──────────────────────────────────────────────
  function _bindToolbar() {
    document.querySelectorAll('.tool-btn[data-mode]').forEach((btn) => {
      btn.addEventListener('click', () => _showView(btn.dataset.mode));
    });

    $('#zoom-fit').addEventListener('click', () => {
      state.zoom = 'fit';
      _showView(state.mode);
    });

    $('#zoom-100').addEventListener('click', () => {
      state.zoom = 1;
      _showView(state.mode);
    });

    // Mouse wheel zoom
    el.imageContainer.addEventListener('wheel', (e) => {
      if (!state.activeId) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      if (state.zoom === 'fit') {
        state.zoom = 0.5;
      }
      state.zoom = Math.max(0.1, Math.min(5, state.zoom + delta));
      _applyZoom();
    }, { passive: false });
  }

  function _applyZoom() {
    const target = state.mode === 'select' ? el.selectView : el.compareView;
    if (state.zoom === 'fit') {
      target.style.transform = '';
    } else {
      target.style.transform = `scale(${state.zoom})`;
      target.style.transformOrigin = 'center center';
    }
    _updateZoomInfo();
  }

  function _updateZoomInfo() {
    const img = state.images.find((i) => i.id === state.activeId);
    if (!img) {
      el.zoomInfo.textContent = '-- · 0×0';
      return;
    }
    const zoomText = state.zoom === 'fit' ? '自适应' : `${Math.round(state.zoom * 100)}%`;
    el.zoomInfo.innerHTML = `<strong>${zoomText}</strong> · ${img.width}×${img.height}`;
  }

  // ── Actions ──────────────────────────────────────────────
  function _bindActions() {
    el.btnProcess.addEventListener('click', _processActive);
    el.btnBatch.addEventListener('click', _batchDownload);
    el.btnDownload.addEventListener('click', _downloadCurrent);
  }

  async function _processActive() {
    if (!state.activeId) return;
    const img = state.images.find((i) => i.id === state.activeId);
    if (!img) return;

    img.status = 'processing';
    _renderFileList();
    el.processingOverlay.style.display = '';

    try {
      const params = new URLSearchParams({
        mark: state.settings.mark,
        method: state.settings.method,
        strip_metadata: state.settings.stripMetadata,
        force: state.settings.force,
      });

      // Add manual regions if in select mode
      if (state.mode === 'select' && state.regions.length) {
        const regionStr = state.regions.map((r) => `${r.x},${r.y},${r.w},${r.h}`).join(';');
        params.set('regions', regionStr);
      }

      const res = await fetch(`/api/process/${state.activeId}?${params}`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Processing failed');
      }

      img.status = 'done';
      _renderFileList();
      _updateBatchButton();

      // Load result into compare view
      el.imgResult.src = `/api/images/${state.activeId}/result`;
      el.btnDownload.disabled = false;

      // Switch to compare mode to show results
      _showView('compare');
    } catch (err) {
      img.status = 'error';
      _renderFileList();
      console.error('Process error:', err);
      alert(`处理失败: ${err.message}`);
    } finally {
      el.processingOverlay.style.display = 'none';
    }
  }

  function _updateBatchButton() {
    const allDone = state.images.length > 0 && state.images.every((i) => i.status === 'done');
    el.btnBatch.classList.toggle('ready', allDone);
    el.btnBatch.disabled = !allDone;
  }

  function _batchDownload() {
    window.open('/api/download-all', '_blank');
  }

  function _downloadCurrent() {
    if (!state.activeId) return;
    const img = state.images.find((i) => i.id === state.activeId);
    if (!img || img.status !== 'done') return;
    window.open(`/api/download/${state.activeId}`, '_blank');
  }

  // ── Keyboard ─────────────────────────────────────────────
  function _bindKeyboard() {
    // Space key is handled by CompareSlider for flash-original
    // Delete key to remove active image
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Delete' && state.activeId && !e.target.closest('input, select')) {
        _deleteImage(state.activeId);
      }
    });
  }

  async function _deleteImage(id) {
    try {
      await fetch(`/api/images/${id}`, { method: 'DELETE' });
    } catch (err) { /* ignore */ }

    state.images = state.images.filter((i) => i.id !== id);
    if (state.activeId === id) {
      state.activeId = state.images.length ? state.images[0].id : null;
      if (state.activeId) {
        _selectImage(state.activeId);
      } else {
        el.emptyState.style.display = '';
        el.compareView.style.display = 'none';
        el.selectView.style.display = 'none';
        el.btnProcess.disabled = true;
        el.btnDownload.disabled = true;
        el.infoName.innerHTML = '文件: --';
        el.infoSize.innerHTML = '尺寸: --';
        el.infoDetect.innerHTML = '检测到: --';
      }
    }
    _renderFileList();
    _updateBatchButton();
  }

  // ── Public API ───────────────────────────────────────────
  return {
    init,
    get state() { return state; },
    get el() { return el; },
    setRegions(regions) { state.regions = regions; },
    showView: _showView,
    applyZoom: _applyZoom,
    updateZoomInfo: _updateZoomInfo,
  };
})();

// Boot
document.addEventListener('DOMContentLoaded', App.init);
