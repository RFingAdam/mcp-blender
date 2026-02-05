"""Meshy.ai API backend for cloud-based 3D generation.

Meshy.ai provides high-quality text-to-3D and image-to-3D generation
with a free tier available.

API Documentation: https://docs.meshy.ai
"""

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .base import (
    BackendCapability,
    BackendConfig,
    BaseBackend,
    GenerationResult,
    GenerationStatus,
)


class MeshyBackend(BaseBackend):
    """Meshy.ai cloud backend for AI 3D generation."""

    name = "meshy"
    display_name = "Meshy.ai"
    description = "Cloud-based high-quality 3D generation from Meshy.ai"

    capabilities = {
        BackendCapability.TEXT_TO_3D,
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.TEXTURE_GENERATION,
        BackendCapability.CLOUD,
    }

    requires_api_key = True
    requires_local_install = False

    # API configuration
    API_BASE = "https://api.meshy.ai"
    API_VERSION = "v2"

    SUPPORTED_FORMATS = ["glb", "fbx", "obj", "usdz"]
    SUPPORTED_STYLES = ["realistic", "cartoon", "sculpture", "pbr"]

    def __init__(self, config: BackendConfig | None = None):
        """Initialize the Meshy backend."""
        super().__init__(config)
        self._jobs: dict[str, dict] = {}

    def _get_api_key(self) -> str | None:
        """Get the API key from config or environment."""
        if self.config.api_key:
            return self.config.api_key

        api_key = os.environ.get("MESHY_API_KEY")
        if api_key:
            return api_key

        try:
            import bpy

            prefs = bpy.context.preferences.addons.get("blender_mcp_addon")
            if prefs and hasattr(prefs, "preferences"):
                return getattr(prefs.preferences, "meshy_api_key", None)
        except Exception:
            pass

        return None

    def is_available(self) -> bool:
        """Check if Meshy API is available."""
        if not self.config.enabled:
            return False
        return self._get_api_key() is not None

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Meshy API."""
        api_key = self._get_api_key()
        if not api_key:
            return {"success": False, "error": "MESHY_API_KEY not configured"}

        timeout = timeout or self.config.timeout
        url = f"{self.API_BASE}/{self.API_VERSION}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            request_data = json.dumps(data).encode("utf-8") if data else None
            req = urllib.request.Request(url, data=request_data, headers=headers, method=method)

            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_text = response.read().decode("utf-8")
                if response_text:
                    return {"success": True, "data": json.loads(response_text)}
                return {"success": True, "data": {}}

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                error_message = error_data.get("message", str(e))
            except Exception:
                error_message = error_body or str(e)
            return {"success": False, "error": f"API error ({e.code}): {error_message}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Generate a 3D model using Meshy API."""
        if not prompt and not image_path:
            return GenerationResult(
                success=False,
                error="Either prompt or image_path is required",
                status=GenerationStatus.FAILED,
            )

        # Prepare request
        if image_path:
            # Image-to-3D
            path = Path(image_path)
            if not path.exists():
                return GenerationResult(
                    success=False,
                    error=f"Image not found: {image_path}",
                    status=GenerationStatus.FAILED,
                )

            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            request_data = {
                "image_url": f"data:image/png;base64,{image_data}",
                "enable_pbr": style == "pbr",
            }
            endpoint = "image-to-3d"
        else:
            # Text-to-3D
            request_data = {
                "prompt": prompt,
                "art_style": style or "realistic",
                "negative_prompt": kwargs.get("negative_prompt", ""),
            }
            endpoint = "text-to-3d"

        result = self._make_request(endpoint, method="POST", data=request_data)

        if not result["success"]:
            return GenerationResult(
                success=False,
                error=result.get("error", "Unknown error"),
                status=GenerationStatus.FAILED,
            )

        data = result["data"]
        job_id = data.get("result")

        if not job_id:
            return GenerationResult(
                success=False,
                error="No job ID returned from API",
                status=GenerationStatus.FAILED,
            )

        self._jobs[job_id] = {
            "prompt": prompt,
            "image_path": image_path,
            "style": style,
            "output_format": output_format,
        }

        return GenerationResult(
            success=True,
            job_id=job_id,
            status=GenerationStatus.PROCESSING,
            message="Generation started",
            metadata={"backend": self.name},
        )

    def get_status(self, job_id: str) -> GenerationResult:
        """Get status of a generation job."""
        result = self._make_request(f"text-to-3d/{job_id}")

        if not result["success"]:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=result.get("error"),
                status=GenerationStatus.FAILED,
            )

        data = result["data"]
        api_status = data.get("status", "PENDING")

        status_map = {
            "PENDING": GenerationStatus.PENDING,
            "IN_PROGRESS": GenerationStatus.PROCESSING,
            "SUCCEEDED": GenerationStatus.COMPLETED,
            "FAILED": GenerationStatus.FAILED,
        }

        status = status_map.get(api_status, GenerationStatus.PROCESSING)

        gen_result = GenerationResult(
            success=status == GenerationStatus.COMPLETED,
            job_id=job_id,
            status=status,
            progress=data.get("progress", 0) / 100.0,
        )

        if status == GenerationStatus.COMPLETED:
            gen_result.download_url = data.get("model_urls", {}).get("glb")

        return gen_result

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        """Download the completed model."""
        status_result = self.get_status(job_id)
        if status_result.status != GenerationStatus.COMPLETED:
            return status_result

        if not status_result.download_url:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="No download URL available",
                status=GenerationStatus.FAILED,
            )

        try:
            urllib.request.urlretrieve(status_result.download_url, output_path)
            return GenerationResult(
                success=True,
                job_id=job_id,
                status=GenerationStatus.COMPLETED,
                model_path=output_path,
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=f"Download failed: {e}",
                status=GenerationStatus.FAILED,
            )

    def get_supported_styles(self) -> list[str]:
        return list(self.SUPPORTED_STYLES)

    def get_supported_formats(self) -> list[str]:
        return list(self.SUPPORTED_FORMATS)
