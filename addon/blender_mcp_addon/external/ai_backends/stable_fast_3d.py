"""Stable Fast 3D backend routed through ComfyUI.

Instead of requiring a standalone sf3d package and PyTorch installation
inside Blender, this backend delegates to ComfyUI when the
``StableFast3DLoader`` node is available.
"""

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
    """Stable Fast 3D via ComfyUI's 3D-Pack nodes."""

    name = "stable_fast_3d"
    display_name = "Stable Fast 3D"
    description = "Fast image-to-3D generation via ComfyUI (StableFast3DLoader)"

    capabilities = {
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.LOCAL,
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 8.0

    SUPPORTED_FORMATS = ["glb", "obj"]

    def __init__(self, config: BackendConfig | None = None):
        super().__init__(config)
        self._comfyui = None

    def _get_comfyui(self):
        """Lazily get the ComfyUI backend instance."""
        if self._comfyui is None:
            from .comfyui import ComfyUIBackend
            self._comfyui = ComfyUIBackend(self.config)
        return self._comfyui

    def is_available(self) -> bool:
        if not self.config.enabled:
            return False
        comfyui = self._get_comfyui()
        if not comfyui.is_available():
            return False
        return comfyui.has_node("StableFast3DLoader")

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Generate a 3D model from an image via ComfyUI's SF3D nodes."""
        if not image_path:
            return GenerationResult(
                success=False,
                error="Stable Fast 3D requires an input image (image_path)",
                status=GenerationStatus.FAILED,
            )

        if not Path(image_path).exists():
            return GenerationResult(
                success=False,
                error=f"Image not found: {image_path}",
                status=GenerationStatus.FAILED,
            )

        comfyui = self._get_comfyui()

        # Upload image to ComfyUI
        server_name = comfyui._upload_image(image_path)
        if not server_name:
            return GenerationResult(
                success=False,
                error="Failed to upload image to ComfyUI",
                status=GenerationStatus.FAILED,
            )

        # Build and queue the SF3D workflow
        from .comfyui import WorkflowTemplate, WorkflowType

        try:
            template = WorkflowTemplate(WorkflowType.STABLE_FAST_3D)
        except FileNotFoundError as e:
            return GenerationResult(
                success=False,
                error=str(e),
                status=GenerationStatus.FAILED,
            )

        workflow = template.build(image=server_name)

        import uuid
        client_id = str(uuid.uuid4())
        result = comfyui._queue_workflow(workflow, client_id)

        if not result["success"]:
            return GenerationResult(
                success=False,
                error=result.get("error", "Failed to queue SF3D workflow"),
                status=GenerationStatus.FAILED,
            )

        prompt_id = result["data"].get("prompt_id")
        comfyui._jobs[prompt_id] = {
            "prompt": prompt,
            "image_path": image_path,
            "client_id": client_id,
            "output_format": output_format,
            "status": "processing",
        }

        return GenerationResult(
            success=True,
            job_id=prompt_id,
            status=GenerationStatus.PROCESSING,
            message="Stable Fast 3D workflow queued in ComfyUI",
            metadata={"backend": self.name, "client_id": client_id},
        )

    def get_status(self, job_id: str) -> GenerationResult:
        return self._get_comfyui().get_status(job_id)

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        return self._get_comfyui().download_result(job_id, output_path)

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        comfyui = self._get_comfyui()
        available, status = comfyui._check_comfyui()
        has_sf3d = comfyui.has_node("StableFast3DLoader") if available else False
        info.update({
            "comfyui_host": comfyui._get_host(),
            "comfyui_status": status,
            "sf3d_node_available": has_sf3d,
            "note": "Routes through ComfyUI with StableFast3DLoader node",
        })
        return info
