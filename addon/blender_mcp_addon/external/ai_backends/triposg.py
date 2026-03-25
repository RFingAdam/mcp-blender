"""TripoSG backend routed through ComfyUI.

Uses the [Comfy3D] TripoSG I23D Model node for single-image 3D generation.
Produces better structural detail than SF3D for mechanical objects.
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


class TripoSGBackend(BaseBackend):
    """TripoSG via ComfyUI's Comfy3D-Pack nodes."""

    name = "triposg"
    display_name = "TripoSG"
    description = "Single-image 3D generation via ComfyUI (TripoSG pipeline)"

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
        return comfyui.has_node("[Comfy3D] TripoSG I23D Model")

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
                error="TripoSG requires an input image (image_path)",
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
            template = WorkflowTemplate(WorkflowType.TRIPOSG)
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
                error=result.get("error", "Failed to queue TripoSG workflow"),
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
            message="TripoSG workflow queued in ComfyUI",
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
        has_node = comfyui.has_node("[Comfy3D] TripoSG I23D Model") if available else False
        info.update({
            "comfyui_host": comfyui._get_host(),
            "comfyui_status": status,
            "triposg_node_available": has_node,
            "note": "Routes through ComfyUI with TripoSG pipeline node",
        })
        return info
