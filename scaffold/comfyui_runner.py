"""
ComfyUI Runner — executes Spellcaster node configurations against
the ComfyUI API.

Takes the wizard output (node name + params dict) and:
1. Builds a minimal ComfyUI workflow JSON
2. POSTs it to /prompt
3. Polls for completion
4. Returns the result (image paths, status, etc.)

Privacy: when cleanup_inputs / cleanup_outputs is True, the runner
deletes uploaded inputs and generated outputs from the ComfyUI server
after they have been downloaded.  This uses the ComfyUI-api-tools
extension (DELETE /api-tools/v1/images/{type}/{filename}).

This module has zero dependencies beyond stdlib + urllib so it works
anywhere without pip installs.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("spellcaster.runner")


class ComfyUIRunner:
    """Thin client for ComfyUI's /prompt API.

    Privacy-aware: when cleanup_inputs or cleanup_outputs is True,
    generated files are deleted from the ComfyUI server after download.
    Deletion uses the ComfyUI-api-tools extension:

        DELETE /api-tools/v1/images/input/{filename}
        DELETE /api-tools/v1/images/output/{filename}

    If the extension is not installed, cleanup is skipped with a
    warning — no crash, no data loss.
    """

    def __init__(self, base_url: str = "http://localhost:8188",
                 timeout: int = 300,
                 cleanup_inputs: bool = True,
                 cleanup_outputs: bool = True):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cleanup_inputs = cleanup_inputs
        self.cleanup_outputs = cleanup_outputs
        self._api_tools_available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check if ComfyUI is reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/system_stats")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    def has_api_tools(self) -> bool:
        """Check whether the ComfyUI-api-tools extension is installed.

        Probes the extension once and caches the result.  A missing
        extension is not an error — cleanup simply becomes a no-op.
        """
        if self._api_tools_available is not None:
            return self._api_tools_available

        try:
            # GET on the images endpoint returns 200 if installed
            req = urllib.request.Request(
                f"{self.base_url}/api-tools/v1/images/output",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self._api_tools_available = resp.status == 200
        except Exception:
            self._api_tools_available = False

        if not self._api_tools_available:
            log.warning(
                "ComfyUI-api-tools not detected at %s — "
                "privacy cleanup will be disabled.  Install it from: "
                "https://github.com/brantje/ComfyUI-api-tools",
                self.base_url,
            )
        return self._api_tools_available

    # ------------------------------------------------------------------
    # Image upload
    # ------------------------------------------------------------------

    def upload_image(self, image_bytes: bytes, filename: str = "input.png",
                     image_type: str = "input", *,
                     validate: bool = True) -> dict:
        """Upload an image to ComfyUI's /upload/image endpoint.

        Constructs a multipart/form-data request with the image file and uploads
        it to the server. Files are always placed in the root directory (not in
        subfolders) so that api-tools DELETE can find them later during cleanup.

        This is the standard way to get images into ComfyUI for workflows that
        need to process existing images (img2img, inpainting, etc.).

        Args:
            image_bytes: Raw image data (PNG, JPG, etc.)
            filename:    Filename for the uploaded file (e.g. "input.png")
            image_type:  ComfyUI directory type — "input", "output", or "temp"
                         (default: "input"). This controls where on disk the
                         file is stored.
            validate:    When True (default), PIL-decode the bytes and
                         re-encode as PNG before upload. Catches corrupt
                         / non-image blobs up front so WAN / LTX / Klein
                         LoadImage doesn't fail 40 s into a render with
                         ``UnidentifiedImageError``. Set to False to
                         upload raw bytes unchanged (videos, intentional
                         non-image data).

        Returns:
            dict with 'name', 'subfolder', 'type' keys confirming the upload

        Raises:
            ValueError: If ``validate`` is True and the bytes don't decode.
            urllib.error.URLError: If the server is unreachable
        """
        if validate:
            try:
                from PIL import Image as _PILImage
                import io as _io
                img = _PILImage.open(_io.BytesIO(image_bytes))
                img.load()
            except Exception as e:  # noqa: BLE001
                raise ValueError(
                    f"Upload rejected: {filename!r} is not a valid image "
                    f"({type(e).__name__}: {e}). Supported: PNG, JPEG, "
                    "WebP, GIF, TIFF, BMP."
                ) from e
            # Normalize to PNG — WAN / LTX / Klein LoadImage all
            # accept JPEG/WebP/etc too but PNG is the one format
            # guaranteed across every ComfyUI LoadImage variant.
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            buf = _io.BytesIO()
            img.save(buf, format="PNG", optimize=False)
            image_bytes = buf.getvalue()
            import os as _os
            base = _os.path.splitext(filename)[0]
            filename = f"{base}.png"
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + image_bytes + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="type"\r\n\r\n'
            f"{image_type}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
            f"true\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        req = urllib.request.Request(
            f"{self.base_url}/upload/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # Workflow execution
    # ------------------------------------------------------------------

    @property
    def privacy_notice(self) -> str:
        """User-facing notice about what will happen to their images.

        Call this *before* execution so the LLM can inform the user
        what to expect.  Returns an empty string when cleanup is off.
        """
        parts = []
        if self.cleanup_inputs:
            parts.append("your uploaded image(s)")
        if self.cleanup_outputs:
            parts.append("the generated image(s)")
        if not parts:
            return ""
        return (
            "For your privacy, "
            + " and ".join(parts)
            + " will be automatically deleted from the server after "
            "delivery to you."
        )

    def run(self, workflow: dict,
            input_filenames: Optional[List[str]] = None) -> dict:
        """
        Submit a workflow and wait for results.

        Args:
            workflow: Either a raw ComfyUI workflow dict, or a wizard output
                      dict with {"node": ..., "params": ...}.
            input_filenames: Names of uploaded input files for this run,
                           used for privacy cleanup (e.g. ["gimp_12345.png"]).

        Returns:
            {"status": "ok", "outputs": [...], "cleanup": {...}}
            or {"status": "error", "message": ...}

            ``cleanup`` always contains a ``privacy_message`` string
            suitable for relaying to the end user.

        After downloading results, automatically cleans up input and output
        files from the ComfyUI server if cleanup_inputs/cleanup_outputs
        are enabled and ComfyUI-api-tools is installed.
        """
        # If it's a wizard output, wrap it in a minimal workflow
        if "node" in workflow and "params" in workflow:
            workflow = self._wizard_to_workflow(workflow)

        prompt_id = self._queue_prompt(workflow)
        if not prompt_id:
            return {"status": "error", "message": "Failed to queue prompt"}

        result = self._poll_result(prompt_id)

        # Privacy cleanup: delete inputs and outputs from server
        if result.get("status") == "ok":
            try:
                cleanup = self.cleanup_after_run(
                    result.get("outputs", []),
                    input_filenames=input_filenames,
                )
                result["cleanup"] = cleanup
            except Exception:
                result["cleanup"] = {"error": "cleanup failed",
                                     "privacy_message":
                                     "Privacy cleanup failed — your images "
                                     "may still be on the server."}

        return result

    def run_raw(self, workflow: dict,
                input_filenames: Optional[List[str]] = None) -> dict:
        """Submit an already-built ComfyUI workflow and wait for results.

        Same privacy cleanup behaviour as run().
        """
        prompt_id = self._queue_prompt(workflow)
        if not prompt_id:
            return {"status": "error", "message": "Failed to queue prompt"}

        result = self._poll_result(prompt_id)

        if result.get("status") == "ok":
            try:
                cleanup = self.cleanup_after_run(
                    result.get("outputs", []),
                    input_filenames=input_filenames,
                )
                result["cleanup"] = cleanup
            except Exception:
                result["cleanup"] = {"error": "cleanup failed",
                                     "privacy_message":
                                     "Privacy cleanup failed — your images "
                                     "may still be on the server."}

        return result

    # ------------------------------------------------------------------
    # Download result images
    # ------------------------------------------------------------------

    def download_image(self, filename: str, subfolder: str = "",
                       folder_type: str = "output") -> bytes:
        """Download a result image from ComfyUI."""
        params = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        })
        req = urllib.request.Request(f"{self.base_url}/view?{params}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    # ------------------------------------------------------------------
    # Privacy cleanup  (requires ComfyUI-api-tools extension)
    # ------------------------------------------------------------------

    def cleanup_after_run(self, outputs: List[dict],
                          input_filenames: Optional[List[str]] = None) -> dict:
        """Delete generated files from ComfyUI after they've been delivered.

        This is a core privacy feature: remote users' images should not
        persist on the server after delivery.

        Uses DELETE /api-tools/v1/images/{input|output}/{filename}
        provided by the ComfyUI-api-tools extension.

        Args:
            outputs: Output list from run()/run_raw() result["outputs"]
            input_filenames: Names of files uploaded for this run (e.g.
                           ["gimp_12345.png"]).  If None, scans for all
                           gimp_* / spellcaster_* temp files.

        Returns:
            {"inputs_cleaned": int, "outputs_cleaned": int,
             "privacy_message": str}
            The privacy_message is a short, user-facing summary suitable
            for relaying to the end user (e.g. via chat).
        """
        stats = {"inputs_cleaned": 0, "outputs_cleaned": 0,
                 "privacy_message": ""}

        if not self.has_api_tools():
            stats["privacy_message"] = (
                "Privacy cleanup unavailable — ComfyUI-api-tools extension "
                "is not installed on the server.  Your uploaded and generated "
                "images may still be on the server."
            )
            return stats

        if self.cleanup_inputs:
            stats["inputs_cleaned"] = self._delete_inputs(input_filenames)

        if self.cleanup_outputs:
            stats["outputs_cleaned"] = self._delete_outputs(outputs)

        # Build user-facing summary
        parts = []
        if stats["inputs_cleaned"]:
            parts.append(f"{stats['inputs_cleaned']} uploaded image(s)")
        if stats["outputs_cleaned"]:
            parts.append(f"{stats['outputs_cleaned']} generated image(s)")
        if parts:
            stats["privacy_message"] = (
                f"Privacy cleanup complete — {' and '.join(parts)} "
                f"deleted from the server."
            )
        elif self.cleanup_inputs or self.cleanup_outputs:
            stats["privacy_message"] = (
                "Privacy cleanup ran but found no files to delete."
            )

        return stats

    def _delete_file(self, folder_type: str, filename: str) -> bool:
        """Delete a single file via api-tools.

        DELETE /api-tools/v1/images/{folder_type}/{filename}
        """
        url = (
            f"{self.base_url}/api-tools/v1/images/"
            f"{urllib.parse.quote(folder_type)}/"
            f"{urllib.parse.quote(filename)}"
        )
        try:
            req = urllib.request.Request(url, method="DELETE")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 204):
                    log.debug("Deleted %s/%s", folder_type, filename)
                    return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                log.debug("Already gone: %s/%s", folder_type, filename)
                return True  # file already deleted — not an error
            log.warning("Failed to delete %s/%s: HTTP %s",
                        folder_type, filename, exc.code)
        except Exception as exc:
            log.warning("Failed to delete %s/%s: %s",
                        folder_type, filename, exc)
        return False

    def _delete_inputs(self,
                       filenames: Optional[List[str]] = None) -> int:
        """Delete uploaded input files from ComfyUI."""
        if filenames is None:
            filenames = self._list_temp_inputs()

        cleaned = 0
        for fname in filenames:
            if self._delete_file("input", fname):
                cleaned += 1
        return cleaned

    def _delete_outputs(self, outputs: List[dict]) -> int:
        """Delete generated output files from ComfyUI.

        Files in subfolders cannot be deleted via api-tools (it only
        handles root-level files).  All spellcaster workflows should
        use flat filename_prefix values (no '/') so this is normally
        not an issue; we log a warning if a subfolder is encountered.
        """
        cleaned = 0
        for item in outputs:
            fname = item.get("filename", "")
            if not fname:
                continue
            subfolder = item.get("subfolder", "")
            folder_type = item.get("folder_type", "output")
            if subfolder:
                log.warning(
                    "Cannot delete %s/%s/%s — api-tools does not "
                    "support subfolder paths.  Ensure workflows use "
                    "flat filename_prefix values (no '/').",
                    folder_type, subfolder, fname,
                )
                continue
            if self._delete_file(folder_type, fname):
                cleaned += 1
        return cleaned

    def _list_temp_inputs(self) -> List[str]:
        """List all temp input files (gimp_*, spellcaster_*) on ComfyUI."""
        prefixes = ("gimp_", "spellcaster_", "scaffold_")
        extensions = (".png", ".jpg", ".jpeg", ".webp")
        try:
            req = urllib.request.Request(
                f"{self.base_url}/object_info/LoadImage"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            all_inputs = (
                data.get("LoadImage", {})
                .get("input", {})
                .get("required", {})
                .get("image", [[]])[0]
            )
            if isinstance(all_inputs, str):
                all_inputs = [all_inputs]

            return [
                f for f in all_inputs
                if any(f.startswith(p) for p in prefixes)
                and any(f.lower().endswith(e) for e in extensions)
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _queue_prompt(self, workflow: dict) -> Optional[str]:
        """POST workflow to /prompt, return prompt_id."""
        payload = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/prompt",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get("prompt_id")
        except Exception:
            return None

    def _poll_result(self, prompt_id: str) -> dict:
        """Poll /history/{prompt_id} until completion or timeout."""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/history/{prompt_id}"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())

                if prompt_id in data:
                    entry = data[prompt_id]
                    status = entry.get("status", {})
                    if status.get("completed", False):
                        outputs = self._extract_outputs(entry)
                        return {"status": "ok", "outputs": outputs}
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        return {"status": "error", "message": str(msgs)}
            except Exception:
                pass

            time.sleep(2)

        return {"status": "error", "message": "Timeout waiting for result"}

    def _extract_outputs(self, history_entry: dict) -> List[dict]:
        """Extract output file info from a completed history entry."""
        outputs = []
        for node_id, node_output in history_entry.get("outputs", {}).items():
            for key in ("images", "gifs", "videos"):
                for item in node_output.get(key, []):
                    outputs.append({
                        "node_id": node_id,
                        "type": key,
                        "filename": item.get("filename"),
                        "subfolder": item.get("subfolder", ""),
                        "folder_type": item.get("type", "output"),
                    })
        return outputs

    def _wizard_to_workflow(self, wizard_output: dict) -> dict:
        """
        Convert wizard output to a minimal ComfyUI workflow.

        This creates a single-node workflow. For multi-node pipelines,
        the caller should compose workflows externally.

        The wizard output contains user-configurable params only.
        Tensor inputs (CONDITIONING, CLIP, etc.) must be wired by
        the integration layer — this method leaves placeholder
        references that the integration fills in.
        """
        node_name = wizard_output["node"]
        params = wizard_output.get("params", {})

        # Build a single-node workflow with placeholders for tensor inputs
        wf = {
            "1": {
                "class_type": node_name,
                "inputs": dict(params),
                "_meta": {
                    "title": f"Spellcaster: {node_name}",
                    "source": "scaffold",
                },
            }
        }
        return wf
