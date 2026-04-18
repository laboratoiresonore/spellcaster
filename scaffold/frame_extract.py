"""
Frame extraction utilities for shot continuity.

Extracts the last frame of a video file as a PNG image so the Shotboard
can wire it as the next shot's reference image.  This is the missing
piece that makes multi-shot continuity automatic.

Strategy (in order of preference):
  1. ffmpeg via subprocess — fastest, most reliable, zero Python deps.
  2. imageio (if installed) — pure-Python fallback.
  3. PIL + a temp raw decode — last resort, limited codec support.

All functions return the absolute path to the extracted PNG, or None on
failure.  Errors are logged but never raised — the caller (VideoBridge)
should degrade gracefully if extraction fails.

Zero dependencies beyond stdlib (ffmpeg is a system tool, not a pip dep).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

log = logging.getLogger("spellcaster.frame_extract")


def extract_last_frame(video_path: str,
                       output_path: Optional[str] = None,
                       ) -> Optional[str]:
    """Extract the last frame of *video_path* as a PNG.

    Parameters
    ----------
    video_path : str
        Absolute path to the source video (.mp4, .webm, .mov, etc.).
    output_path : str, optional
        Where to write the PNG.  If omitted, writes next to the video
        as ``<stem>_lastframe.png``.

    Returns
    -------
    str or None
        Absolute path to the extracted PNG, or None on failure.
    """
    if not os.path.isfile(video_path):
        log.warning("extract_last_frame: file not found: %s", video_path)
        return None

    if output_path is None:
        stem, _ = os.path.splitext(video_path)
        output_path = f"{stem}_lastframe.png"
    output_path = os.path.abspath(output_path)

    # Strategy 1: ffmpeg
    result = _extract_ffmpeg(video_path, output_path)
    if result:
        return result

    # Strategy 2: imageio
    result = _extract_imageio(video_path, output_path)
    if result:
        return result

    log.warning("extract_last_frame: all strategies failed for %s",
                video_path)
    return None


def _ffmpeg_available() -> bool:
    """Check whether ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


def _get_duration_s(video_path: str) -> Optional[float]:
    """Use ffprobe to get video duration in seconds."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.check_output(
            [ffprobe,
             "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "format=duration",
             "-of", "csv=p=0",
             video_path],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return float(out.strip())
    except Exception:  # noqa: BLE001
        return None


def _extract_ffmpeg(video_path: str,
                    output_path: str) -> Optional[str]:
    """Extract last frame using ffmpeg."""
    if not _ffmpeg_available():
        log.debug("ffmpeg not found on PATH")
        return None

    try:
        # Get duration so we can seek near the end.
        dur = _get_duration_s(video_path)
        if dur is not None and dur > 1.0:
            # Seek to 0.1s before the end, then grab 1 frame.
            seek_s = max(0, dur - 0.1)
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{seek_s:.3f}",
                "-i", video_path,
                "-frames:v", "1",
                "-update", "1",
                output_path,
            ]
        else:
            # Short video or unknown duration — read the whole thing,
            # output only the last frame using the "update" flag.
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-frames:v", "1",
                "-update", "1",
                "-vf", "select='eq(n\\,0)'",
                output_path,
            ]
            # Actually for short/unknown, use sseof which seeks from end
            cmd = [
                "ffmpeg", "-y",
                "-sseof", "-0.1",
                "-i", video_path,
                "-frames:v", "1",
                "-update", "1",
                output_path,
            ]

        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=True,
        )
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            log.info("Extracted last frame via ffmpeg: %s", output_path)
            return output_path
        return None
    except Exception as exc:  # noqa: BLE001
        log.debug("ffmpeg extraction failed: %s", exc)
        return None


def _extract_imageio(video_path: str,
                     output_path: str) -> Optional[str]:
    """Extract last frame using imageio (if available)."""
    try:
        import imageio.v3 as iio  # type: ignore
    except ImportError:
        try:
            import imageio as iio  # type: ignore
        except ImportError:
            log.debug("imageio not available")
            return None

    try:
        # imageio v3 API
        if hasattr(iio, "imread"):
            # Read all frames — memory-heavy for long videos but works
            # as a fallback when ffmpeg is absent.  For typical WanGP
            # outputs (81-121 frames at 480p) this is fine.
            frames = iio.imread(video_path, plugin="pyav")
            if hasattr(frames, "__len__") and len(frames) > 0:
                last = frames[-1]
            else:
                log.debug("imageio returned no frames")
                return None
        else:
            log.debug("imageio API not recognised")
            return None

        # Save via PIL if available, else raw imageio write
        try:
            from PIL import Image  # type: ignore
            img = Image.fromarray(last)
            img.save(output_path)
        except ImportError:
            iio.imwrite(output_path, last)

        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            log.info("Extracted last frame via imageio: %s", output_path)
            return output_path
        return None
    except Exception as exc:  # noqa: BLE001
        log.debug("imageio extraction failed: %s", exc)
        return None
