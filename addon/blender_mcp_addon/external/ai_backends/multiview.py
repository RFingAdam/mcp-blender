"""Multi-view reconstruction backend routed through ComfyUI.

Uses Zero123Plus for multi-view generation followed by InstantMesh for
3D reconstruction. Produces the best structural detail for mechanical
objects and vehicles.
"""

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


class MultiviewBackend(BaseBackend):
    """Multi-view reconstruction via ComfyUI (Zero123Plus + InstantMesh)."""

    name = "multiview"
    display_name = "Multi-View Reconstruction"
    description = "Best quality image-to-3D via Zero123Plus multi-view + InstantMesh reconstruction"

    capabilities = {
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.LOCAL,
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 10.0

    SUPPORTED_FORMATS = ["glb", "obj"]

    def __init__(self, config: BackendConfig | None = None):
        super().__init__(config)
        self._comfyui = None

    def _get_comfyui(self):
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
        return (
            comfyui.has_node("[Comfy3D] Zero123Plus Diffusion Model")
            and comfyui.has_node("[Comfy3D] Load InstantMesh Reconstruction Model")
        )

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        if not image_path:
            return GenerationResult(
                success=False,
                error="Multi-view reconstruction requires an input image (image_path)",
                status=GenerationStatus.FAILED,
            )

        if not Path(image_path).exists():
            return GenerationResult(
                success=False,
                error=f"Image not found: {image_path}",
                status=GenerationStatus.FAILED,
            )

        comfyui = self._get_comfyui()

        server_name = comfyui._upload_image(image_path)
        if not server_name:
            return GenerationResult(
                success=False,
                error="Failed to upload image to ComfyUI",
                status=GenerationStatus.FAILED,
            )

        from .comfyui import WorkflowTemplate, WorkflowType

        try:
            template = WorkflowTemplate(WorkflowType.MULTIVIEW_TO_3D)
        except FileNotFoundError as e:
            return GenerationResult(
                success=False, error=str(e), status=GenerationStatus.FAILED,
            )

        workflow = template.build(image=server_name)
        template.resolve_fallbacks(workflow, comfyui.has_node)

        client_id = str(uuid.uuid4())
        result = comfyui._queue_workflow(workflow, client_id)

        if not result["success"]:
            return GenerationResult(
                success=False,
                error=result.get("error", "Failed to queue multi-view workflow"),
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
            message="Multi-view reconstruction workflow queued in ComfyUI",
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
        has_zero123 = comfyui.has_node("[Comfy3D] Zero123Plus Diffusion Model") if available else False
        has_instantmesh = comfyui.has_node("[Comfy3D] Load InstantMesh Reconstruction Model") if available else False
        info.update({
            "comfyui_host": comfyui._get_host(),
            "comfyui_status": status,
            "zero123plus_available": has_zero123,
            "instantmesh_available": has_instantmesh,
            "note": "Routes through ComfyUI with Zero123Plus + InstantMesh nodes",
        })
        return info
