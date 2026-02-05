"""Tripo AI API backend for cloud-based 3D generation.

Tripo AI provides fast cloud-based text-to-3D and image-to-3D generation.

API Documentation: https://platform.tripo3d.ai/docs
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


class TripoAIBackend(BaseBackend):
    """Tripo AI cloud backend for 3D generation."""

    name = "tripo"
    display_name = "Tripo AI"
    description = "Fast cloud-based 3D generation from Tripo AI"

    capabilities = {
        BackendCapability.TEXT_TO_3D,
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.CLOUD,
    }

    requires_api_key = True
    requires_local_install = False

    API_BASE = "https://api.tripo3d.ai/v1"
    SUPPORTED_FORMATS = ["glb", "fbx", "obj"]

    def __init__(self, config: BackendConfig | None = None):
        super().__init__(config)
        self._jobs: dict[str, dict] = {}

    def _get_api_key(self) -> str | None:
        if self.config.api_key:
            return self.config.api_key
        return os.environ.get("TRIPO_API_KEY")

    def is_available(self) -> bool:
        if not self.config.enabled:
            return False
        return self._get_api_key() is not None

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict | None = None,
    ) -> dict[str, Any]:
        api_key = self._get_api_key()
        if not api_key:
            return {"success": False, "error": "TRIPO_API_KEY not configured"}

        url = f"{self.API_BASE}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            request_data = json.dumps(data).encode("utf-8") if data else None
            req = urllib.request.Request(url, data=request_data, headers=headers, method=method)

            with urllib.request.urlopen(req, timeout=self.config.timeout) as response:
                return {"success": True, "data": json.loads(response.read().decode())}

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
        if image_path:
            path = Path(image_path)
            if not path.exists():
                return GenerationResult(
                    success=False,
                    error=f"Image not found: {image_path}",
                    status=GenerationStatus.FAILED,
                )
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()
            request_data = {"type": "image_to_model", "image": image_data}
        else:
            request_data = {"type": "text_to_model", "prompt": prompt}

        result = self._make_request("task", method="POST", data=request_data)

        if not result["success"]:
            return GenerationResult(
                success=False,
                error=result.get("error"),
                status=GenerationStatus.FAILED,
            )

        job_id = result["data"].get("task_id")
        self._jobs[job_id] = {"prompt": prompt, "output_format": output_format}

        return GenerationResult(
            success=True,
            job_id=job_id,
            status=GenerationStatus.PROCESSING,
            metadata={"backend": self.name},
        )

    def get_status(self, job_id: str) -> GenerationResult:
        result = self._make_request(f"task/{job_id}")

        if not result["success"]:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=result.get("error"),
                status=GenerationStatus.FAILED,
            )

        data = result["data"]
        status_map = {
            "queued": GenerationStatus.QUEUED,
            "running": GenerationStatus.PROCESSING,
            "success": GenerationStatus.COMPLETED,
            "failed": GenerationStatus.FAILED,
        }

        status = status_map.get(data.get("status"), GenerationStatus.PROCESSING)

        gen_result = GenerationResult(
            success=status == GenerationStatus.COMPLETED,
            job_id=job_id,
            status=status,
            progress=data.get("progress", 0) / 100.0,
        )

        if status == GenerationStatus.COMPLETED:
            gen_result.download_url = data.get("output", {}).get("model")

        return gen_result

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        status_result = self.get_status(job_id)
        if status_result.status != GenerationStatus.COMPLETED:
            return status_result

        if not status_result.download_url:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="No download URL",
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
                error=str(e),
                status=GenerationStatus.FAILED,
            )
