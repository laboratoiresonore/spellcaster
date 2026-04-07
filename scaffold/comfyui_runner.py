"""
ComfyUI Runner — executes Spellcaster node configurations against
the ComfyUI API.

Takes the wizard output (node name + params dict) and:
1. Builds a minimal ComfyUI workflow JSON
2. POSTs it to /prompt
3. Polls for completion
4. Returns the result (image paths, status, etc.)

This module has zero dependencies beyond stdlib + urllib so it works
anywhere without pip installs.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
import uuid
from typing import Any, Dict, List, Optional, Tuple


class ComfyUIRunner:
    """Thin client for ComfyUI's /prompt API."""

    def __init__(self, base_url: str = "http://localhost:8188",
                 timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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

    # ------------------------------------------------------------------
    # Image upload
    # ------------------------------------------------------------------

    def upload_image(self, image_bytes: bytes, filename: str = "input.png",
                     subfolder: str = "input") -> dict:
        """Upload an image to ComfyUI's /upload/image endpoint."""
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + image_bytes + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="subfolder"\r\n\r\n'
            f"{subfolder}\r\n"
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

    def run(self, workflow: dict) -> dict:
        """
        Submit a workflow and wait for results.

        Args:
            workflow: Either a raw ComfyUI workflow dict, or a wizard output
                      dict with {"node": ..., "params": ...}.

        Returns:
            {"status": "ok", "outputs": [...]} or {"status": "error", "message": ...}
        """
        # If it's a wizard output, wrap it in a minimal workflow
        if "node" in workflow and "params" in workflow:
            workflow = self._wizard_to_workflow(workflow)

        prompt_id = self._queue_prompt(workflow)
        if not prompt_id:
            return {"status": "error", "message": "Failed to queue prompt"}

        return self._poll_result(prompt_id)

    def run_raw(self, workflow: dict) -> dict:
        """Submit an already-built ComfyUI workflow and wait for results."""
        prompt_id = self._queue_prompt(workflow)
        if not prompt_id:
            return {"status": "error", "message": "Failed to queue prompt"}
        return self._poll_result(prompt_id)

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
