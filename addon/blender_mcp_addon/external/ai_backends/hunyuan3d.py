"""Hunyuan3D 2.1 local backend for high-quality 3D generation.

Hunyuan3D is Tencent's open-source text-to-3D and image-to-3D model.
It provides high-quality results comparable to commercial APIs.

GitHub: https://github.com/Tencent/Hunyuan3D-2
"""

import os
import shutil
import subprocess
import sys
import tempfile
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


class Hunyuan3DBackend(BaseBackend):
    """Hunyuan3D 2.1 local backend for high-quality 3D generation.

    Hunyuan3D excels at:
    - High-quality text-to-3D generation
    - Image-to-3D reconstruction
    - Detailed geometry and textures
    - Multiple style options

    Requirements:
    - ~16GB VRAM for full quality
    - PyTorch with CUDA support
    - hunyuan3d package
    """

    name = "hunyuan3d"
    display_name = "Hunyuan3D 2.1"
    description = "High-quality local 3D generation using Tencent's Hunyuan3D"

    capabilities = {
        BackendCapability.TEXT_TO_3D,
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.VARIATIONS,
        BackendCapability.LOCAL,
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 16.0

    # Model configuration
    SUPPORTED_FORMATS = ["glb", "obj", "ply"]
    SUPPORTED_STYLES = ["realistic", "cartoon", "anime", "sculpture"]

    def __init__(self, config: BackendConfig | None = None):
        """Initialize the Hunyuan3D backend.

        Args:
            config: Optional configuration with model_path and device settings.
        """
        super().__init__(config)
        self._model = None
        self._text_model = None
        self._image_model = None
        self._jobs: dict[str, dict] = {}
        self._output_dir = self._get_output_dir()

    def _get_output_dir(self) -> Path:
        """Get the output directory for generated models."""
        try:
            import bpy

            user_path = Path(bpy.utils.resource_path("USER"))
            output_dir = user_path / "mcp_blender_cache" / "ai_models" / "hunyuan3d"
        except Exception:
            output_dir = Path.home() / ".cache" / "mcp_blender" / "ai_models" / "hunyuan3d"

        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _check_dependencies(self) -> tuple[bool, str]:
        """Check if all required dependencies are available.

        Returns:
            Tuple of (available, message).
        """
        missing = []

        try:
            import torch

            if not torch.cuda.is_available():
                return False, "CUDA not available. Hunyuan3D requires GPU."
        except ImportError:
            missing.append("torch")

        # Check for hunyuan3d or hy3dgen package
        hunyuan_available = False
        try:
            import hy3dgen

            hunyuan_available = True
        except ImportError:
            pass

        if not hunyuan_available:
            try:
                import hunyuan3d

                hunyuan_available = True
            except ImportError:
                pass

        if not hunyuan_available:
            missing.append("hunyuan3d (see https://github.com/Tencent/Hunyuan3D-2)")

        try:
            import PIL
        except ImportError:
            missing.append("Pillow")

        try:
            import transformers
        except ImportError:
            missing.append("transformers")

        try:
            import diffusers
        except ImportError:
            missing.append("diffusers")

        if missing:
            return False, f"Missing dependencies: {', '.join(missing)}"

        return True, "All dependencies available"

    def is_available(self) -> bool:
        """Check if Hunyuan3D is available for use."""
        if not self.config.enabled:
            return False

        available, _ = self._check_dependencies()
        return available

    def _get_device(self) -> str:
        """Get the device to use for inference."""
        device = self.config.device

        if device == "auto":
            try:
                import torch

                if torch.cuda.is_available():
                    return "cuda"
                else:
                    return "cpu"  # Will be very slow
            except ImportError:
                return "cpu"

        return device

    def _load_model(self, model_type: str = "both") -> bool:
        """Load the Hunyuan3D model(s) into memory.

        Args:
            model_type: "text", "image", or "both"

        Returns:
            True if model(s) loaded successfully.
        """
        try:
            import torch

            device = self._get_device()

            # Try to import the appropriate module
            try:
                from hy3dgen.text2mesh import Text2MeshPipeline
                from hy3dgen.image2mesh import Image2MeshPipeline

                if model_type in ("text", "both") and self._text_model is None:
                    self._text_model = Text2MeshPipeline.from_pretrained(
                        self.config.model_path or "tencent/Hunyuan3D-2",
                        torch_dtype=torch.float16,
                    )
                    self._text_model.to(device)

                if model_type in ("image", "both") and self._image_model is None:
                    self._image_model = Image2MeshPipeline.from_pretrained(
                        self.config.model_path or "tencent/Hunyuan3D-2",
                        torch_dtype=torch.float16,
                    )
                    self._image_model.to(device)

                return True

            except ImportError:
                # Fallback: try alternative import structure
                try:
                    from hunyuan3d import Hunyuan3DGenerator

                    if self._model is None:
                        self._model = Hunyuan3DGenerator(
                            model_path=self.config.model_path,
                            device=device,
                        )
                    return True
                except ImportError:
                    return False

        except Exception as e:
            print(f"Failed to load Hunyuan3D model: {e}")
            return False

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Generate a 3D model from text or image.

        Args:
            prompt: Text description of the desired model.
            image_path: Optional path to input image.
            style: Style modifier (realistic, cartoon, anime, sculpture).
            quality: Generation quality (draft, medium, high).
            output_format: Output format (glb, obj, ply).

        Returns:
            GenerationResult with job_id.
        """
        if not prompt and not image_path:
            return GenerationResult(
                success=False,
                error="Either prompt or image_path is required",
                status=GenerationStatus.FAILED,
            )

        if image_path:
            path = Path(image_path)
            if not path.exists():
                return GenerationResult(
                    success=False,
                    error=f"Image not found: {image_path}",
                    status=GenerationStatus.FAILED,
                )

        if output_format not in self.SUPPORTED_FORMATS:
            return GenerationResult(
                success=False,
                error=f"Unsupported format: {output_format}. Use: {self.SUPPORTED_FORMATS}",
                status=GenerationStatus.FAILED,
            )

        if style and style not in self.SUPPORTED_STYLES:
            return GenerationResult(
                success=False,
                error=f"Unknown style: {style}. Use: {self.SUPPORTED_STYLES}",
                status=GenerationStatus.FAILED,
            )

        # Create job
        job_id = str(uuid.uuid4())
        output_path = self._output_dir / f"{job_id}.{output_format}"

        self._jobs[job_id] = {
            "prompt": prompt,
            "image_path": image_path,
            "style": style,
            "quality": quality,
            "output_format": output_format,
            "output_path": str(output_path),
            "status": "processing",
            "progress": 0.0,
        }

        # Run generation
        try:
            result = self._run_generation(job_id)
            return result
        except Exception as e:
            self._jobs[job_id]["status"] = "failed"
            self._jobs[job_id]["error"] = str(e)
            return GenerationResult(
                success=False,
                job_id=job_id,
                status=GenerationStatus.FAILED,
                error=str(e),
            )

    def _run_generation(self, job_id: str) -> GenerationResult:
        """Run the actual generation process.

        Args:
            job_id: Job ID.

        Returns:
            GenerationResult with model path on success.
        """
        job = self._jobs.get(job_id)
        if not job:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Job not found",
                status=GenerationStatus.FAILED,
            )

        # Determine model type needed
        model_type = "image" if job.get("image_path") else "text"

        # Load model if needed
        if not self._load_model(model_type):
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Failed to load Hunyuan3D model. Check dependencies.",
                status=GenerationStatus.FAILED,
            )

        try:
            import torch
            from PIL import Image

            device = self._get_device()

            # Quality settings
            quality_settings = {
                "draft": {"steps": 25, "resolution": 128},
                "medium": {"steps": 50, "resolution": 256},
                "high": {"steps": 75, "resolution": 512},
            }
            settings = quality_settings.get(job["quality"], quality_settings["medium"])

            # Style prompt enhancement
            style_prompts = {
                "realistic": "photorealistic, highly detailed, ",
                "cartoon": "cartoon style, stylized, ",
                "anime": "anime style, japanese animation, ",
                "sculpture": "3D sculpture, smooth surfaces, ",
            }
            style_prefix = style_prompts.get(job.get("style", ""), "")
            full_prompt = style_prefix + job["prompt"]

            # Generate
            with torch.no_grad():
                if job.get("image_path"):
                    # Image-to-3D
                    image = Image.open(job["image_path"])
                    if image.mode != "RGB":
                        image = image.convert("RGB")

                    if self._image_model:
                        mesh = self._image_model(
                            image,
                            prompt=full_prompt if job["prompt"] else None,
                            num_inference_steps=settings["steps"],
                        )
                    elif self._model:
                        mesh = self._model.image_to_3d(
                            image,
                            prompt=full_prompt if job["prompt"] else None,
                            steps=settings["steps"],
                        )
                    else:
                        raise RuntimeError("No model loaded")
                else:
                    # Text-to-3D
                    if self._text_model:
                        mesh = self._text_model(
                            full_prompt,
                            num_inference_steps=settings["steps"],
                        )
                    elif self._model:
                        mesh = self._model.text_to_3d(
                            full_prompt,
                            steps=settings["steps"],
                        )
                    else:
                        raise RuntimeError("No model loaded")

            # Export mesh
            output_path = Path(job["output_path"])

            if hasattr(mesh, "export"):
                mesh.export(str(output_path))
            elif hasattr(mesh, "save"):
                mesh.save(str(output_path))
            else:
                # Try trimesh-style export
                mesh.export(str(output_path), file_type=job["output_format"])

            # Update job status
            self._jobs[job_id]["status"] = "completed"
            self._jobs[job_id]["progress"] = 1.0

            return GenerationResult(
                success=True,
                job_id=job_id,
                status=GenerationStatus.COMPLETED,
                model_path=str(output_path),
                message="Model generated successfully",
                metadata={
                    "backend": self.name,
                    "quality": job["quality"],
                    "style": job.get("style"),
                    "format": job["output_format"],
                    "steps": settings["steps"],
                },
            )

        except Exception as e:
            self._jobs[job_id]["status"] = "failed"
            self._jobs[job_id]["error"] = str(e)
            return GenerationResult(
                success=False,
                job_id=job_id,
                status=GenerationStatus.FAILED,
                error=f"Generation failed: {e}",
            )

    def get_status(self, job_id: str) -> GenerationResult:
        """Get status of a generation job."""
        job = self._jobs.get(job_id)
        if not job:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Job not found",
                status=GenerationStatus.FAILED,
            )

        status_map = {
            "pending": GenerationStatus.PENDING,
            "processing": GenerationStatus.PROCESSING,
            "completed": GenerationStatus.COMPLETED,
            "failed": GenerationStatus.FAILED,
        }

        status = status_map.get(job["status"], GenerationStatus.FAILED)

        result = GenerationResult(
            success=status == GenerationStatus.COMPLETED,
            job_id=job_id,
            status=status,
            progress=job.get("progress", 0.0),
        )

        if status == GenerationStatus.COMPLETED:
            result.model_path = job.get("output_path")
        elif status == GenerationStatus.FAILED:
            result.error = job.get("error", "Unknown error")

        return result

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        """Copy the generated model to the specified path."""
        job = self._jobs.get(job_id)
        if not job:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Job not found",
                status=GenerationStatus.FAILED,
            )

        if job["status"] != "completed":
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=f"Job not completed: {job['status']}",
                status=GenerationStatus.FAILED,
            )

        source_path = Path(job["output_path"])
        if not source_path.exists():
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Generated model file not found",
                status=GenerationStatus.FAILED,
            )

        try:
            dest_path = Path(output_path)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)

            return GenerationResult(
                success=True,
                job_id=job_id,
                status=GenerationStatus.COMPLETED,
                model_path=str(dest_path),
            )

        except Exception as e:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=f"Failed to copy file: {e}",
                status=GenerationStatus.FAILED,
            )

    def get_supported_styles(self) -> list[str]:
        """Get supported generation styles."""
        return list(self.SUPPORTED_STYLES)

    def get_supported_formats(self) -> list[str]:
        """Get supported output formats."""
        return list(self.SUPPORTED_FORMATS)

    def get_default_options(self) -> dict[str, Any]:
        """Get default generation options."""
        return {
            "quality": "medium",
            "output_format": "glb",
            "style": "realistic",
        }

    def get_info(self) -> dict[str, Any]:
        """Get detailed backend information."""
        info = super().get_info()
        available, dep_status = self._check_dependencies()

        info.update({
            "dependencies_status": dep_status,
            "device": self._get_device(),
            "model_loaded": any([self._model, self._text_model, self._image_model]),
            "output_directory": str(self._output_dir),
            "recommended_vram": "16GB+",
        })
        return info

    def initialize(self) -> bool:
        """Pre-load the model for faster generation."""
        return self._load_model("both")

    def shutdown(self) -> None:
        """Release models from memory."""
        self._model = None
        self._text_model = None
        self._image_model = None
        self._initialized = False

        # Force garbage collection
        try:
            import gc
            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
