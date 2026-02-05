"""ComfyUI backend for customizable 3D generation workflows.

This backend integrates with ComfyUI when 3D generation nodes are installed,
enabling highly customizable generation workflows.

Requires: ComfyUI running with 3D generation nodes (e.g., TripoSR, InstantMesh)
"""

import json
import urllib.error
import urllib.request
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


class ComfyUIBackend(BaseBackend):
    """ComfyUI backend for customizable 3D generation.

    ComfyUI provides node-based workflows that can combine multiple
    generation and processing steps. This backend enables:
    - Custom generation workflows
    - Multi-stage processing
    - Integration with other ComfyUI nodes
    """

    name = "comfyui"
    display_name = "ComfyUI"
    description = "Customizable 3D generation via ComfyUI workflows"

    capabilities = {
        BackendCapability.TEXT_TO_3D,
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.LOCAL,
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 8.0

    DEFAULT_HOST = "http://localhost:8188"
    SUPPORTED_FORMATS = ["glb", "obj"]

    def __init__(self, config: BackendConfig | None = None):
        super().__init__(config)
        self._jobs: dict[str, dict] = {}
        self._output_dir = self._get_output_dir()

    def _get_output_dir(self) -> Path:
        try:
            import bpy
            user_path = Path(bpy.utils.resource_path("USER"))
            output_dir = user_path / "mcp_blender_cache" / "ai_models" / "comfyui"
        except Exception:
            output_dir = Path.home() / ".cache" / "mcp_blender" / "ai_models" / "comfyui"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _get_host(self) -> str:
        return self.config.extra.get("host", self.DEFAULT_HOST) if self.config else self.DEFAULT_HOST

    def _get_workflow(self) -> str | None:
        return self.config.extra.get("workflow") if self.config else None

    def _check_comfyui(self) -> tuple[bool, str]:
        """Check if ComfyUI is running and accessible."""
        host = self._get_host()

        try:
            req = urllib.request.Request(f"{host}/system_stats")
            with urllib.request.urlopen(req, timeout=5) as response:
                response.read()  # Just verify we can read the response

            return True, "ComfyUI is running"

        except urllib.error.URLError:
            return False, f"Cannot connect to ComfyUI at {host}"
        except Exception as e:
            return False, f"Error checking ComfyUI: {e}"

    def is_available(self) -> bool:
        if not self.config.enabled:
            return False
        available, _ = self._check_comfyui()
        return available

    def _queue_workflow(self, workflow: dict, client_id: str) -> dict:
        """Queue a workflow in ComfyUI."""
        host = self._get_host()

        request_data = {
            "prompt": workflow,
            "client_id": client_id,
        }

        try:
            req = urllib.request.Request(
                f"{host}/prompt",
                data=json.dumps(request_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                return {"success": True, "data": json.loads(response.read().decode())}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_history(self, prompt_id: str) -> dict | None:
        """Get execution history for a prompt."""
        host = self._get_host()

        try:
            req = urllib.request.Request(f"{host}/history/{prompt_id}")
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                return data.get(prompt_id)
        except Exception:
            return None

    def _get_default_workflow(self, prompt: str, image_path: str | None = None) -> dict:
        """Get a default 3D generation workflow.

        This is a placeholder - actual workflows depend on installed nodes.
        """
        # Placeholder workflow structure
        workflow = {
            "1": {
                "class_type": "LoadImage" if image_path else "CLIPTextEncode",
                "inputs": {
                    "image": image_path if image_path else None,
                    "text": prompt if not image_path else None,
                },
            },
            # Additional nodes would be added based on available 3D generation nodes
        }

        return workflow

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Generate using a ComfyUI workflow."""
        # Load workflow
        workflow_path = self._get_workflow()

        if workflow_path and Path(workflow_path).exists():
            with open(workflow_path, "r") as f:
                workflow = json.load(f)
            # Would need to inject prompt/image into workflow
        else:
            workflow = self._get_default_workflow(prompt, image_path)

        client_id = str(uuid.uuid4())
        result = self._queue_workflow(workflow, client_id)

        if not result["success"]:
            return GenerationResult(
                success=False,
                error=result.get("error", "Failed to queue workflow"),
                status=GenerationStatus.FAILED,
            )

        prompt_id = result["data"].get("prompt_id")

        self._jobs[prompt_id] = {
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
            message="Workflow queued in ComfyUI",
            metadata={"backend": self.name, "client_id": client_id},
        )

    def get_status(self, job_id: str) -> GenerationResult:
        """Get status of a ComfyUI workflow execution."""
        history = self._get_history(job_id)

        if not history:
            # Still processing or not found
            job = self._jobs.get(job_id)
            if job:
                return GenerationResult(
                    success=True,
                    job_id=job_id,
                    status=GenerationStatus.PROCESSING,
                    message="Workflow is processing",
                )
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Job not found",
                status=GenerationStatus.FAILED,
            )

        if "outputs" in history:
            # Find 3D model output
            for node_id, output in history["outputs"].items():
                if "meshes" in output or "models" in output:
                    # Found output
                    return GenerationResult(
                        success=True,
                        job_id=job_id,
                        status=GenerationStatus.COMPLETED,
                        metadata={"outputs": output},
                    )

        return GenerationResult(
            success=True,
            job_id=job_id,
            status=GenerationStatus.COMPLETED,
            message="Workflow completed but no 3D output found",
        )

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        """Download the generated model from ComfyUI output."""
        history = self._get_history(job_id)

        if not history or "outputs" not in history:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="No output available",
                status=GenerationStatus.FAILED,
            )

        # Find and download the model file
        host = self._get_host()

        for node_id, output in history["outputs"].items():
            meshes = output.get("meshes", output.get("models", []))
            if meshes:
                mesh_info = meshes[0]
                filename = mesh_info.get("filename")
                subfolder = mesh_info.get("subfolder", "")

                try:
                    url = f"{host}/view?filename={filename}&subfolder={subfolder}&type=output"
                    urllib.request.urlretrieve(url, output_path)

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

        return GenerationResult(
            success=False,
            job_id=job_id,
            error="No 3D model in outputs",
            status=GenerationStatus.FAILED,
        )

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        available, status = self._check_comfyui()

        info.update({
            "comfyui_host": self._get_host(),
            "workflow_file": self._get_workflow(),
            "comfyui_status": status,
            "note": "Requires ComfyUI with 3D generation nodes installed",
        })
        return info
