/**
 * TrajectoryCanvas — draw motion paths on a reference image.
 *
 * Usage:
 *   const tc = new TrajectoryCanvas({
 *     container: document.getElementById('traj-panel'),
 *     imageUrl: '/api/video/shots/<id>/ref',  // or a data: URL
 *     onSave: (trajectories) => { ... },       // called with array of path objects
 *   });
 *   tc.load(imageUrl);   // load a new ref image
 *   tc.clear();          // wipe all paths
 *   tc.getTrajectories(); // get current paths as JSON-ready array
 *   tc.destroy();        // remove DOM and listeners
 *
 * Each trajectory is: {
 *   label: "path-1",
 *   points: [[x,y], [x,y], ...],   // image-pixel coords
 *   colour: "#ff3366",
 * }
 *
 * No dependencies. Vanilla JS, vanilla Canvas2D.
 */

class TrajectoryCanvas {
  static COLOURS = [
    '#ff3366', '#33ccff', '#66ff33', '#ffcc00',
    '#cc33ff', '#ff6633', '#33ffcc', '#ff33cc',
  ];

  constructor({ container, imageUrl, onSave, readonly }) {
    this.container = container;
    this.onSave = onSave || (() => {});
    this.readonly = !!readonly;
    this.trajectories = [];   // completed paths
    this.currentPath = null;  // path being drawn right now
    this.drawing = false;
    this._imgNatW = 0;
    this._imgNatH = 0;
    this._scale = 1;
    this._offsetX = 0;
    this._offsetY = 0;

    this._build();
    if (imageUrl) this.load(imageUrl);
  }

  // ── DOM setup ──────────────────────────────────────────────────────

  _build() {
    this.wrapper = document.createElement('div');
    this.wrapper.style.cssText =
      'position:relative;width:100%;background:#111;border-radius:8px;overflow:hidden;';

    this.canvas = document.createElement('canvas');
    this.canvas.style.cssText = 'display:block;width:100%;cursor:crosshair;';
    this.wrapper.appendChild(this.canvas);

    // Toolbar
    this.toolbar = document.createElement('div');
    this.toolbar.style.cssText =
      'display:flex;gap:6px;padding:6px 8px;background:#1a1a2e;align-items:center;flex-wrap:wrap;';

    if (!this.readonly) {
      this._addBtn('Undo', () => this.undo());
      this._addBtn('Clear', () => this.clear());
      this._addBtn('Save', () => this._save(), '#22c55e');
    }

    // Path count badge
    this.badge = document.createElement('span');
    this.badge.style.cssText =
      'margin-left:auto;font-size:12px;color:#888;font-family:monospace;';
    this.badge.textContent = '0 paths';
    this.toolbar.appendChild(this.badge);

    this.wrapper.appendChild(this.toolbar);
    this.container.appendChild(this.wrapper);

    // Events
    if (!this.readonly) {
      this.canvas.addEventListener('mousedown', (e) => this._startDraw(e));
      this.canvas.addEventListener('mousemove', (e) => this._moveDraw(e));
      this.canvas.addEventListener('mouseup', () => this._endDraw());
      this.canvas.addEventListener('mouseleave', () => this._endDraw());
      // Touch
      this.canvas.addEventListener('touchstart', (e) => {
        e.preventDefault(); this._startDraw(e.touches[0]);
      }, { passive: false });
      this.canvas.addEventListener('touchmove', (e) => {
        e.preventDefault(); this._moveDraw(e.touches[0]);
      }, { passive: false });
      this.canvas.addEventListener('touchend', () => this._endDraw());
    }

    // Resize observer
    this._resizeObs = new ResizeObserver(() => this._onResize());
    this._resizeObs.observe(this.wrapper);
  }

  _addBtn(label, handler, bg) {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.style.cssText =
      `padding:4px 10px;border:none;border-radius:4px;cursor:pointer;` +
      `font-size:12px;color:#fff;background:${bg || '#334155'};`;
    btn.addEventListener('click', handler);
    this.toolbar.appendChild(btn);
    return btn;
  }

  // ── Image loading ──────────────────────────────────────────────────

  load(url) {
    this._img = new Image();
    this._img.crossOrigin = 'anonymous';
    this._img.onload = () => {
      this._imgNatW = this._img.naturalWidth;
      this._imgNatH = this._img.naturalHeight;
      this._onResize();
    };
    this._img.onerror = () => {
      console.warn('TrajectoryCanvas: failed to load image', url);
    };
    this._img.src = url;
  }

  _onResize() {
    if (!this._imgNatW) return;
    const w = this.wrapper.clientWidth;
    this._scale = w / this._imgNatW;
    const h = Math.round(this._imgNatH * this._scale);
    this.canvas.width = w;
    this.canvas.height = h;
    this.canvas.style.height = h + 'px';
    this._offsetX = 0;
    this._offsetY = 0;
    this._redraw();
  }

  // ── Coordinate helpers ─────────────────────────────────────────────

  _canvasXY(e) {
    const rect = this.canvas.getBoundingClientRect();
    return [
      (e.clientX - rect.left),
      (e.clientY - rect.top),
    ];
  }

  /** Convert canvas pixel to image pixel. */
  _toImageCoord(cx, cy) {
    return [
      Math.round((cx - this._offsetX) / this._scale),
      Math.round((cy - this._offsetY) / this._scale),
    ];
  }

  /** Convert image pixel to canvas pixel. */
  _toCanvasCoord(ix, iy) {
    return [
      ix * this._scale + this._offsetX,
      iy * this._scale + this._offsetY,
    ];
  }

  // ── Drawing ────────────────────────────────────────────────────────

  _startDraw(e) {
    if (this.readonly) return;
    this.drawing = true;
    const [cx, cy] = this._canvasXY(e);
    const [ix, iy] = this._toImageCoord(cx, cy);
    const idx = this.trajectories.length;
    const colour = TrajectoryCanvas.COLOURS[idx % TrajectoryCanvas.COLOURS.length];
    this.currentPath = { label: `path-${idx + 1}`, points: [[ix, iy]], colour };
  }

  _moveDraw(e) {
    if (!this.drawing || !this.currentPath) return;
    const [cx, cy] = this._canvasXY(e);
    const [ix, iy] = this._toImageCoord(cx, cy);
    this.currentPath.points.push([ix, iy]);
    this._redraw();
  }

  _endDraw() {
    if (!this.drawing || !this.currentPath) return;
    this.drawing = false;
    // Only keep paths with at least 2 points
    if (this.currentPath.points.length >= 2) {
      this.trajectories.push(this.currentPath);
    }
    this.currentPath = null;
    this._redraw();
    this._updateBadge();
  }

  // ── Rendering ──────────────────────────────────────────────────────

  _redraw() {
    const ctx = this.canvas.getContext('2d');
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    // Draw the reference image
    if (this._img && this._img.complete && this._imgNatW) {
      ctx.drawImage(
        this._img,
        this._offsetX, this._offsetY,
        this._imgNatW * this._scale,
        this._imgNatH * this._scale,
      );
    }

    // Draw completed trajectories
    for (const traj of this.trajectories) {
      this._drawPath(ctx, traj.points, traj.colour, 3);
    }
    // Draw the in-progress path
    if (this.currentPath) {
      this._drawPath(ctx, this.currentPath.points, this.currentPath.colour, 3);
    }
  }

  _drawPath(ctx, points, colour, width) {
    if (points.length < 2) return;
    ctx.beginPath();
    ctx.strokeStyle = colour;
    ctx.lineWidth = width;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const [sx, sy] = this._toCanvasCoord(points[0][0], points[0][1]);
    ctx.moveTo(sx, sy);
    for (let i = 1; i < points.length; i++) {
      const [px, py] = this._toCanvasCoord(points[i][0], points[i][1]);
      ctx.lineTo(px, py);
    }
    ctx.stroke();

    // Draw start dot
    ctx.beginPath();
    ctx.fillStyle = colour;
    ctx.arc(sx, sy, 5, 0, Math.PI * 2);
    ctx.fill();

    // Draw arrowhead at end
    const n = points.length;
    if (n >= 2) {
      const [ex, ey] = this._toCanvasCoord(points[n - 1][0], points[n - 1][1]);
      const [px, py] = this._toCanvasCoord(points[n - 2][0], points[n - 2][1]);
      const angle = Math.atan2(ey - py, ex - px);
      const headLen = 10;
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(
        ex - headLen * Math.cos(angle - Math.PI / 6),
        ey - headLen * Math.sin(angle - Math.PI / 6),
      );
      ctx.moveTo(ex, ey);
      ctx.lineTo(
        ex - headLen * Math.cos(angle + Math.PI / 6),
        ey - headLen * Math.sin(angle + Math.PI / 6),
      );
      ctx.strokeStyle = colour;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }

  // ── Actions ────────────────────────────────────────────────────────

  undo() {
    this.trajectories.pop();
    this._redraw();
    this._updateBadge();
  }

  clear() {
    this.trajectories = [];
    this.currentPath = null;
    this._redraw();
    this._updateBadge();
  }

  _save() {
    const data = this.getTrajectories();
    this.onSave(data);
  }

  getTrajectories() {
    return this.trajectories.map(t => ({
      label: t.label,
      points: t.points,
      colour: t.colour,
    }));
  }

  /** Load existing trajectories (e.g. from the server). */
  setTrajectories(trajs) {
    this.trajectories = (trajs || []).map((t, i) => ({
      label: t.label || `path-${i + 1}`,
      points: (t.points || []).map(p => [p[0], p[1]]),
      colour: t.colour || TrajectoryCanvas.COLOURS[i % TrajectoryCanvas.COLOURS.length],
    }));
    this._redraw();
    this._updateBadge();
  }

  _updateBadge() {
    const n = this.trajectories.length;
    this.badge.textContent = `${n} path${n !== 1 ? 's' : ''}`;
  }

  destroy() {
    this._resizeObs.disconnect();
    this.wrapper.remove();
  }
}

// Export for both module and script-tag usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = TrajectoryCanvas;
}
