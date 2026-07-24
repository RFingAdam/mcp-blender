"""ComfyUI backend for customizable 3D generation and texture workflows.

This backend integrates with ComfyUI for both 3D generation and PBR texture
generation using workflow templates.

Requires: ComfyUI running with appropriate nodes installed.
"""

import copy
import json
import random
import urllib.error
import urllib.parse
import urllib.request
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from .base import (
    BackendCapability,
    BackendConfig,
    BaseBackend,
    GenerationResult,
    GenerationStatus,
)


class WorkflowType(Enum):
    """Types of ComfyUI workflows."""

    PBR_TEXTURE = "pbr_texture"
    REFERENCE_IMAGE = "reference_image"
    INPAINT = "inpaint"
    CONTROLNET_TEXTURE = "controlnet_texture"
    STABLE_FAST_3D = "stable_fast_3d"
    MULTIVIEW_TO_3D = "multiview_to_3d"
    TRIPOSG = "triposg"


class WorkflowTemplate:
    """Loads and parameterizes ComfyUI workflow JSON templates.

    Templates live in the workflows/ directory alongside this module.
    Each template has a ``_parameters`` metadata key mapping parameter
    names to ``node_id.input_name`` paths for substitution.
    """

    _cache: dict[str, dict] = {}

    def __init__(self, workflow_type: WorkflowType):
        self.workflow_type = workflow_type
        self._template = self._load_template()
        self._param_map = self._template.pop("_parameters", {})

    @classmethod
    def _workflows_dir(cls) -> Path:
        return Path(__file__).parent / "workflows"

    def _load_template(self) -> dict:
        name = self.workflow_type.value
        if name in WorkflowTemplate._cache:
            return copy.deepcopy(WorkflowTemplate._cache[name])

        path = self._workflows_dir() / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Workflow template not found: {path}")

        with open(path, "r") as f:
            data = json.load(f)

        WorkflowTemplate._cache[name] = data
        return copy.deepcopy(data)

    def build(self, **params: Any) -> dict:
        """Build a workflow by substituting parameters into the template.

        Args:
            **params: Parameter values keyed by name from ``_parameters``.

        Returns:
            A ComfyUI-ready workflow dict (without the ``_parameters`` key).
        """
        workflow = copy.deepcopy(self._template)

        for param_name, path in self._param_map.items():
            if param_name not in params:
                continue
            node_id, _, input_name = path.partition(".")
            if node_id in workflow and "inputs" in workflow[node_id]:
                workflow[node_id]["inputs"][input_name] = params[param_name]

        return workflow

    def resolve_fallbacks(self, workflow: dict, available_checker) -> dict:
        """Resolve _fallback_class entries in a built workflow.

        For each node with a ``_fallback_class`` key, check if the primary
        ``class_type`` is available.  If not, swap to the fallback class.
        Strips all ``_fallback_class`` keys from the result.

        Args:
            workflow: A built workflow dict.
            available_checker: Callable that takes a class_type string and
                returns True if the node is available in ComfyUI.

        Returns:
            The workflow with fallbacks resolved and metadata stripped.
        """
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            fallback = node.pop("_fallback_class", None)
            if fallback and not available_checker(node.get("class_type", "")):
                node["class_type"] = fallback
        return workflow

    @property
    def parameter_names(self) -> list[str]:
        return list(self._param_map.keys())


class ComfyUIBackend(BaseBackend):
    """ComfyUI backend for customizable 3D generation and texture workflows.

    ComfyUI provides node-based workflows that can combine multiple
    generation and processing steps. This backend enables:
    - PBR texture generation from text prompts
    - Reference image generation
    - Inpainting for texture repair
    - ControlNet-guided texture generation
    - Stable Fast 3D model generation
    """

    name = "comfyui"
    display_name = "ComfyUI"
    description = "Customizable 3D generation and texture workflows via ComfyUI"

    capabilities = {
        BackendCapability.TEXT_TO_3D,
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.TEXTURE_GENERATION,
        BackendCapability.LOCAL,
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 8.0

    DEFAULT_HOST = "http://127.0.0.1:8188"
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

    def _check_comfyui(self) -> tuple[bool, str]:
        """Check if ComfyUI is running and accessible."""
        host = self._get_host()
        try:
            req = urllib.request.Request(f"{host}/system_stats")
            with urllib.request.urlopen(req, timeout=5) as response:
                response.read()
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

    def has_node(self, class_type: str) -> bool:
        """Check if a specific node type is available in ComfyUI."""
        host = self._get_host()
        try:
            encoded = urllib.parse.quote(class_type, safe='')
            req = urllib.request.Request(f"{host}/object_info/{encoded}")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                return class_type in data
        except Exception:
            return False

    # =========================================================================
    # Image upload / download helpers
    # =========================================================================

    def _upload_image(self, image_path: str, filename: str | None = None) -> str | None:
        """Upload an image to ComfyUI's input directory.

        Args:
            image_path: Local path to the image file.
            filename: Optional filename to use on the server.

        Returns:
            The server-side filename, or None on failure.
        """
        host = self._get_host()
        path = Path(image_path)
        if not path.exists():
            return None

        upload_name = filename or path.name
        boundary = uuid.uuid4().hex

        with open(path, "rb") as f:
            image_data = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{upload_name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + image_data + f"\r\n--{boundary}--\r\n".encode()

        try:
            req = urllib.request.Request(
                f"{host}/upload/image",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                return result.get("name")
        except Exception:
            return None

    def _download_image(self, filename: str, subfolder: str = "", output_path: Path | None = None) -> Path | None:
        """Download an image from ComfyUI's output directory.

        Args:
            filename: Server-side filename.
            subfolder: Optional subfolder.
            output_path: Where to save locally. Defaults to self._output_dir.

        Returns:
            Local path to downloaded file, or None on failure.
        """
        host = self._get_host()
        params = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": "output",
        })

        dest = output_path or (self._output_dir / filename)
        try:
            urllib.request.urlretrieve(f"{host}/view?{params}", str(dest))
            return dest
        except Exception:
            return None

    def _download_texture_results(self, history_outputs: dict) -> dict[str, str]:
        """Download multi-output texture results, matching filenames to map types.

        SaveImage nodes use ``filename_prefix`` to tag outputs. We match
        prefixes like ``diffuse``, ``roughness``, ``normal``, ``metallic``
        to determine the map type.

        Returns:
            Dict mapping map type (e.g. "diffuse") to local file path.
        """
        texture_maps: dict[str, str] = {}
        known_prefixes = ["diffuse", "roughness", "normal", "metallic", "inpaint", "reference", "controlnet_texture"]

        for _node_id, output in history_outputs.items():
            images = output.get("images", [])
            for img in images:
                fname = img.get("filename", "")
                subfolder = img.get("subfolder", "")

                # Determine map type from filename prefix
                map_type = "unknown"
                for prefix in known_prefixes:
                    if fname.lower().startswith(prefix):
                        map_type = prefix
                        break

                local = self._download_image(fname, subfolder)
                if local:
                    texture_maps[map_type] = str(local)

        return texture_maps

    # =========================================================================
    # Workflow execution
    # =========================================================================

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

    # =========================================================================
    # Texture generation
    # =========================================================================

    def generate_texture(
        self,
        prompt: str,
        workflow_type: WorkflowType = WorkflowType.PBR_TEXTURE,
        negative_prompt: str = "blurry, low quality, watermark, text, logo",
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        steps: int = 30,
        cfg: float = 7.0,
        image_path: str | None = None,
        mask_path: str | None = None,
        denoise: float = 0.85,
        controlnet_strength: float = 0.85,
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate textures using a ComfyUI workflow template.

        Args:
            prompt: Text description of the desired texture.
            workflow_type: Which workflow template to use.
            negative_prompt: Negative prompt for generation.
            width: Output width in pixels.
            height: Output height in pixels.
            seed: Random seed (None for random).
            steps: Number of sampling steps.
            cfg: Classifier-free guidance scale.
            image_path: Input image for inpaint/controlnet workflows.
            mask_path: Mask image for inpaint workflow.
            denoise: Denoising strength for inpaint.
            controlnet_strength: ControlNet conditioning strength.
            **kwargs: Additional workflow parameters.

        Returns:
            GenerationResult with job_id for polling.
        """
        # Convert string to WorkflowType enum if needed
        if isinstance(workflow_type, str):
            try:
                workflow_type = WorkflowType(workflow_type)
            except ValueError:
                return GenerationResult(
                    success=False,
                    error=f"Unknown workflow type: {workflow_type}",
                    status=GenerationStatus.FAILED,
                )

        if seed is None:
            seed = random.randint(0, 2**32 - 1)

        # Upload images if needed
        server_image = None
        server_mask = None
        if image_path:
            server_image = self._upload_image(image_path)
            if not server_image:
                return GenerationResult(
                    success=False,
                    error=f"Failed to upload image: {image_path}",
                    status=GenerationStatus.FAILED,
                )
        if mask_path:
            server_mask = self._upload_image(mask_path)
            if not server_mask:
                return GenerationResult(
                    success=False,
                    error=f"Failed to upload mask: {mask_path}",
                    status=GenerationStatus.FAILED,
                )

        # Build workflow from template
        try:
            template = WorkflowTemplate(workflow_type)
        except FileNotFoundError as e:
            return GenerationResult(
                success=False,
                error=str(e),
                status=GenerationStatus.FAILED,
            )

        build_params: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "denoise": denoise,
            "controlnet_strength": controlnet_strength,
        }
        if server_image:
            build_params["image"] = server_image
            build_params["control_image"] = server_image
        if server_mask:
            build_params["mask"] = server_mask

        build_params.update(kwargs)
        workflow = template.build(**build_params)

        # Resolve _fallback_class entries for unavailable nodes
        template.resolve_fallbacks(workflow, self.has_node)

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
            "workflow_type": workflow_type.value,
            "client_id": client_id,
            "status": "processing",
        }

        return GenerationResult(
            success=True,
            job_id=prompt_id,
            status=GenerationStatus.PROCESSING,
            message=f"Texture workflow ({workflow_type.value}) queued in ComfyUI",
            metadata={
                "backend": self.name,
                "client_id": client_id,
                "workflow_type": workflow_type.value,
            },
        )

    # =========================================================================
    # 3D generation (existing interface)
    # =========================================================================

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
        workflow_path = self.config.extra.get("workflow") if self.config else None

        if workflow_path and Path(workflow_path).exists():
            with open(workflow_path, "r") as f:
                workflow = json.load(f)
            workflow.pop("_parameters", None)
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

    def _get_default_workflow(self, prompt: str, image_path: str | None = None) -> dict:
        """Get a default 3D generation workflow."""
        workflow = {
            "1": {
                "class_type": "LoadImage" if image_path else "CLIPTextEncode",
                "inputs": {
                    "image": image_path if image_path else None,
                    "text": prompt if not image_path else None,
                },
            },
        }
        return workflow

    # =========================================================================
    # Status / download
    # =========================================================================

    def get_status(self, job_id: str) -> GenerationResult:
        """Get status of a ComfyUI workflow execution."""
        history = self._get_history(job_id)

        if not history:
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

        # Check for errors
        status_data = history.get("status", {})
        if status_data.get("status_str") == "error":
            msgs = status_data.get("messages", [])
            error_msg = str(msgs) if msgs else "Workflow execution failed"
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=error_msg,
                status=GenerationStatus.FAILED,
            )

        if "outputs" in history:
            outputs = history["outputs"]
            job = self._jobs.get(job_id, {})
            workflow_type = job.get("workflow_type")

            # Texture workflows: download images and return paths
            if workflow_type and workflow_type != WorkflowType.STABLE_FAST_3D.value:
                texture_maps = self._download_texture_results(outputs)
                return GenerationResult(
                    success=True,
                    job_id=job_id,
                    status=GenerationStatus.COMPLETED,
                    message="Texture generation completed",
                    metadata={"texture_maps": texture_maps, "workflow_type": workflow_type},
                )

            # 3D workflows: look for mesh outputs
            for _node_id, output in outputs.items():
                if "meshes" in output or "models" in output:
                    return GenerationResult(
                        success=True,
                        job_id=job_id,
                        status=GenerationStatus.COMPLETED,
                        metadata={"outputs": output},
                    )

            # Fallback: images present (e.g. reference image)
            for _node_id, output in outputs.items():
                if "images" in output:
                    texture_maps = self._download_texture_results(outputs)
                    return GenerationResult(
                        success=True,
                        job_id=job_id,
                        status=GenerationStatus.COMPLETED,
                        metadata={"texture_maps": texture_maps},
                    )

        return GenerationResult(
            success=True,
            job_id=job_id,
            status=GenerationStatus.COMPLETED,
            message="Workflow completed but no output found",
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

        host = self._get_host()
        for _node_id, output in history["outputs"].items():
            meshes = output.get("meshes", output.get("models", []))
            if meshes:
                mesh_info = meshes[0]
                filename = mesh_info.get("filename")
                subfolder = mesh_info.get("subfolder", "")
                try:
                    params = urllib.parse.urlencode({
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": "output",
                    })
                    urllib.request.urlretrieve(f"{host}/view?{params}", output_path)
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
            "comfyui_status": status,
            "supported_workflow_types": [wt.value for wt in WorkflowType],
        })
        return info
