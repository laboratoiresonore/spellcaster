"""Webcam snapshot endpoint.

  GET /cam/snapshot
    Returns a base64-encoded JPEG from this host's webcam. Used by the
    Prometheus fleet-frame to paint each machine tile with a recent
    snapshot of whatever the box's camera sees — gives the operator a
    physical-presence signal at a glance.

  Implementation: shell out to ffmpeg.
    - Windows: -f dshow -i video=<device>  (device auto-discovered by
      parsing `ffmpeg -list_devices true -f dshow -i dummy` stderr).
    - Linux:   -f v4l2  -i /dev/videoN     (first existing device 0-3).

Snapshots are cached for 30 s server-side so the fleet-frame can poll
freely without hammering the camera bus.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SNAPSHOT_CACHE_S = 30.0
DEVICE_CACHE_S = 300.0
FFMPEG_TIMEOUT_S = 8.0


_camera_cache: dict[str, Any] = {"ts": 0.0, "device": None}
_snapshot_cache: dict[str, Any] = {"ts": 0.0, "jpeg": None}


def _find_video_device() -> str | None:
    """Locate a video device, cached for DEVICE_CACHE_S."""
    now = time.time()
    cached = _camera_cache.get("device")
    if cached and (now - _camera_cache.get("ts", 0)) < DEVICE_CACHE_S:
        return cached
    name: str | None = None
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-list_devices", "true",
                 "-f", "dshow", "-i", "dummy"],
                capture_output=True, text=True, timeout=4,
            )
            in_video = False
            for ln in r.stderr.splitlines():
                if "DirectShow video devices" in ln:
                    in_video = True
                    continue
                if "DirectShow audio devices" in ln:
                    in_video = False
                    continue
                if in_video and '"' in ln and "Alternative" not in ln:
                    start = ln.find('"')
                    end = ln.rfind('"')
                    if start >= 0 and end > start:
                        name = ln[start + 1: end]
                        break
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    else:
        for n in range(5):
            p = f"/dev/video{n}"
            if Path(p).exists():
                name = p
                break
    _camera_cache["device"] = name
    _camera_cache["ts"] = now
    return name


def _capture_jpeg() -> bytes | None:
    """Capture one frame as JPEG, scaled to 640px wide."""
    now = time.time()
    cached = _snapshot_cache.get("jpeg")
    if cached and (now - _snapshot_cache.get("ts", 0)) < SNAPSHOT_CACHE_S:
        return cached
    device = _find_video_device()
    if not device:
        return None
    out_path = Path(tempfile.gettempdir()) / f"antenna_cam_{os.getpid()}.jpg"
    try:
        if sys.platform == "win32":
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "dshow", "-rtbufsize", "100M",
                "-i", f"video={device}",
                "-frames:v", "1", "-vf", "scale=640:-2",
                "-f", "image2", str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "v4l2", "-i", device,
                "-frames:v", "1", "-vf", "scale=640:-2",
                "-f", "image2", str(out_path),
            ]
        subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT_S)
        if out_path.exists() and out_path.stat().st_size > 0:
            with out_path.open("rb") as f:
                blob = f.read()
            _snapshot_cache["jpeg"] = blob
            _snapshot_cache["ts"] = now
            return blob
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    finally:
        try:
            out_path.unlink()
        except OSError:
            pass
    return None


def get_snapshot(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /cam/snapshot — base64 JPEG, or 503 if no camera."""
    jpeg = _capture_jpeg()
    if not jpeg:
        return 503, {"error": "no camera or capture failed",
                     "device": _find_video_device()}
    return 200, {
        "ts": int(time.time()),
        "format": "jpeg",
        "size_bytes": len(jpeg),
        "device": _find_video_device(),
        "base64": base64.b64encode(jpeg).decode("ascii"),
    }


# ─── Recording (local file via ffmpeg) ────────────────────────────
_recording: dict[str, Any] = {"proc": None, "path": None, "started": 0.0}


def _recordings_dir() -> Path:
    p = Path(os.path.expanduser("~/.spellcaster/recordings"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def start_record(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /cam/record — start a webcam recording to a local mp4.

    No-op if one's already running (idempotent). Returns 503 if no
    camera is detected."""
    if _recording.get("proc") is not None and _recording["proc"].poll() is None:
        return 200, {"state": "already_recording",
                     "path": str(_recording.get("path") or ""),
                     "started": int(_recording.get("started", 0))}
    device = _find_video_device()
    if not device:
        return 503, {"error": "no camera detected"}
    ts = int(time.time())
    out_path = _recordings_dir() / f"cam_{ts}.mp4"
    if sys.platform == "win32":
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "dshow", "-rtbufsize", "100M",
            "-i", f"video={device}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-vf", "scale=1280:-2",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "v4l2", "-i", device,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-vf", "scale=1280:-2",
            str(out_path),
        ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,  # so we can send 'q' to stop cleanly
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as e:
        return 500, {"error": f"ffmpeg failed to launch: {type(e).__name__}: {e}"}
    _recording["proc"] = proc
    _recording["path"] = out_path
    _recording["started"] = time.time()
    return 200, {"state": "started", "path": str(out_path), "started": ts}


def stop_record(ctx: dict[str, Any]) -> tuple[int, dict]:
    """POST /cam/record_stop — stop the in-flight recording."""
    proc = _recording.get("proc")
    if proc is None or proc.poll() is not None:
        return 200, {"state": "not_recording"}
    path = _recording.get("path")
    # ffmpeg responds to a 'q' on stdin with a clean shutdown that
    # closes the container properly.
    try:
        if proc.stdin:
            proc.stdin.write(b"q")
            proc.stdin.flush()
    except (OSError, BrokenPipeError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    duration = round(time.time() - (_recording.get("started") or time.time()), 2)
    _recording["proc"] = None
    return 200, {"state": "stopped", "path": str(path or ""),
                 "duration_s": duration}


def record_status(ctx: dict[str, Any]) -> tuple[int, dict]:
    """GET /cam/record_status — is the antenna currently recording?"""
    proc = _recording.get("proc")
    rec = proc is not None and proc.poll() is None
    return 200, {
        "recording": rec,
        "path": str(_recording.get("path") or "") if rec else None,
        "started": int(_recording.get("started") or 0) if rec else 0,
        "duration_s": round(time.time() - (_recording.get("started") or time.time()), 1) if rec else 0,
    }
