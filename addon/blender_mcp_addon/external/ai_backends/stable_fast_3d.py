"""Stable Fast 3D local backend for fast text-to-3D generation.

Stable Fast 3D is a fast local model for text-to-3D generation.

Note: This is a placeholder implementation. The actual Stable Fast 3D
model needs to be installed separately.
"""

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from .base import (
    BackendCapability,
    BackendConfig,
    BaseBackend,
    GenerationResult,
    GenerationStatus,
)


class StableFast3DBackend(BaseBackend):
    """Stable Fast 3D local backend for fast 3D generation."""

    name = "stable_fast_3d"
    display_name = "Stable Fast 3D"
    description = "Fast local text-to-3D generation"

    capabilities = {
        BackendCapability.TEXT_TO_3D,
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.LOCAL,
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 8.0

    SUPPORTED_FORMATS = ["glb", "obj"]

    def __init__(self, config: BackendConfig | None = None):
        super().__init__(config)
        self._model = None
        self._jobs: dict[str, dict] = {}
        self._output_dir = self._get_output_dir()

    def _get_output_dir(self) -> Path:
        try:
            import bpy
            user_path = Path(bpy.utils.resource_path("USER"))
            output_dir = user_path / "mcp_blender_cache" / "ai_models" / "sf3d"
        except Exception:
            output_dir = Path.home() / ".cache" / "mcp_blender" / "ai_models" / "sf3d"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _check_dependencies(self) -> tuple[bool, str]:
        """Check if dependencies are available."""
        try:
            import torch
            if not torch.cuda.is_available():
                return False, "CUDA not available"
        except ImportError:
            return False, "PyTorch not installed"

        # Check for sf3d package (placeholder - actual package name may differ)
        try:
            import sf3d  # noqa
            return True, "All dependencies available"
        except ImportError:
            return False, "Stable Fast 3D not installed (pip install sf3d)"

    def is_available(self) -> bool:
        if not self.config.enabled:
            return False
        available, _ = self._check_dependencies()
        return available

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Generate 3D model."""
        # Placeholder - actual implementation depends on sf3d API
        return GenerationResult(
            success=False,
            error="Stable Fast 3D backend not yet fully implemented",
            status=GenerationStatus.FAILED,
        )

    def get_status(self, job_id: str) -> GenerationResult:
        job = self._jobs.get(job_id)
        if not job:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Job not found",
                status=GenerationStatus.FAILED,
            )
        return GenerationResult(
            success=job.get("status") == "completed",
            job_id=job_id,
            status=GenerationStatus.COMPLETED if job.get("status") == "completed" else GenerationStatus.FAILED,
        )

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        return GenerationResult(
            success=False,
            job_id=job_id,
            error="Not implemented",
            status=GenerationStatus.FAILED,
        )
