"""TripoSR local backend for fast single-image-to-3D generation.

TripoSR is a fast feed-forward model for image-to-3D reconstruction
developed by Stability AI. It can generate 3D models in under 1 second.

GitHub: https://github.com/VAST-AI-Research/TripoSR
"""

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


class TripoSRBackend(BaseBackend):
    """TripoSR local backend for fast image-to-3D generation.

    TripoSR excels at:
    - Very fast inference (<1 second on GPU)
    - Good quality for prototyping
    - Minimal VRAM requirements (~4GB)
    - Single-image input

    Note: Does not support text-to-3D directly. For text prompts,
    use in combination with an image generation model.
    """

    name = "triposr"
    display_name = "TripoSR"
    description = "Fast local image-to-3D generation using TripoSR"

    capabilities = {
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.LOCAL,
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 4.0

    # Model configuration
    DEFAULT_MODEL_NAME = "stabilityai/TripoSR"
    SUPPORTED_FORMATS = ["glb", "obj", "ply"]

    def __init__(self, config: BackendConfig | None = None):
        """Initialize the TripoSR backend.

        Args:
            config: Optional configuration with model_path and device settings.
        """
        super().__init__(config)
        self._model = None
        self._jobs: dict[str, dict] = {}
        self._output_dir = self._get_output_dir()

    def _get_output_dir(self) -> Path:
        """Get the output directory for generated models."""
        try:
            import bpy

            user_path = Path(bpy.utils.resource_path("USER"))
            output_dir = user_path / "mcp_blender_cache" / "ai_models" / "triposr"
        except Exception:
            output_dir = Path.home() / ".cache" / "mcp_blender" / "ai_models" / "triposr"

        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _check_triposr_available(self) -> bool:
        """Check if TripoSR is installed and available."""
        import importlib.util

        return (
            importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("tsr") is not None
        )

    def _check_dependencies(self) -> tuple[bool, str]:
        """Check if all required dependencies are available.

        Returns:
            Tuple of (available, message).
        """
        import importlib.util

        missing = []

        if importlib.util.find_spec("torch") is not None:
            import torch

            if not torch.cuda.is_available():
                # Check for MPS (Apple Silicon) or CPU fallback
                if not (
                    hasattr(torch.backends, "mps")
                    and torch.backends.mps.is_available()
                ):
                    # CPU is available but slow
                    pass
        else:
            missing.append("torch")

        if importlib.util.find_spec("tsr") is None:
            missing.append("tsr (pip install triposr)")

        if importlib.util.find_spec("PIL") is None:
            missing.append("Pillow")

        if importlib.util.find_spec("numpy") is None:
            missing.append("numpy")

        if missing:
            return False, f"Missing dependencies: {', '.join(missing)}"

        return True, "All dependencies available"

    def is_available(self) -> bool:
        """Check if TripoSR is available for use."""
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
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    return "mps"
                else:
                    return "cpu"
            except ImportError:
                return "cpu"

        return device

    def _load_model(self) -> bool:
        """Load the TripoSR model into memory.

        Returns:
            True if model loaded successfully.
        """
        if self._model is not None:
            return True

        try:
            from tsr.system import TSR

            device = self._get_device()

            # Use configured model path or default
            model_path = self.config.model_path or self.DEFAULT_MODEL_NAME

            self._model = TSR.from_pretrained(
                model_path,
                config_name="config.yaml",
                weight_name="model.ckpt",
            )
            self._model.renderer.set_chunk_size(8192)
            self._model.to(device)

            return True

        except Exception as e:
            print(f"Failed to load TripoSR model: {e}")
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
        """Generate a 3D model from an image.

        TripoSR requires an image input. The prompt is stored for metadata
        but not used directly in generation.

        Args:
            prompt: Text description (stored in metadata).
            image_path: Path to input image (required).
            style: Not used by TripoSR.
            quality: Affects mesh resolution (draft/medium/high).
            output_format: Output format (glb, obj, ply).

        Returns:
            GenerationResult with job_id or error.
        """
        if not image_path:
            return GenerationResult(
                success=False,
                error="TripoSR requires an image input. Provide image_path parameter.",
                status=GenerationStatus.FAILED,
            )

        image_path = Path(image_path)
        if not image_path.exists():
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

        # Create job
        job_id = str(uuid.uuid4())
        output_path = self._output_dir / f"{job_id}.{output_format}"

        self._jobs[job_id] = {
            "image_path": str(image_path),
            "prompt": prompt,
            "quality": quality,
            "output_format": output_format,
            "output_path": str(output_path),
            "status": "processing",
        }

        # Run generation synchronously (TripoSR is fast)
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

        # Load model if needed
        if not self._load_model():
            return GenerationResult(
                success=False,
                job_id=job_id,
                error="Failed to load TripoSR model",
                status=GenerationStatus.FAILED,
            )

        try:
            import torch
            from PIL import Image

            # Load and preprocess image
            image = Image.open(job["image_path"])

            # Remove background if the model expects it
            # TripoSR works better with clean backgrounds
            if image.mode != "RGBA":
                image = image.convert("RGBA")

            # Process with model
            device = self._get_device()
            with torch.no_grad():
                scene_codes = self._model([image], device)

            # Quality affects mesh resolution
            quality_map = {
                "draft": 128,
                "medium": 256,
                "high": 512,
            }
            mc_resolution = quality_map.get(job["quality"], 256)

            # Extract mesh
            meshes = self._model.extract_mesh(scene_codes, resolution=mc_resolution)
            mesh = meshes[0]

            # Export to file
            output_path = Path(job["output_path"])
            output_format = job["output_format"]

            if output_format == "glb":
                mesh.export(str(output_path))
            elif output_format == "obj":
                mesh.export(str(output_path), file_type="obj")
            elif output_format == "ply":
                mesh.export(str(output_path), file_type="ply")

            # Update job status
            self._jobs[job_id]["status"] = "completed"

            return GenerationResult(
                success=True,
                job_id=job_id,
                status=GenerationStatus.COMPLETED,
                model_path=str(output_path),
                message="Model generated successfully",
                metadata={
                    "backend": self.name,
                    "resolution": mc_resolution,
                    "format": output_format,
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
        """Get status of a generation job.

        Since TripoSR runs synchronously, jobs are typically
        already complete when status is checked.
        """
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
            progress=1.0 if status == GenerationStatus.COMPLETED else 0.5,
        )

        if status == GenerationStatus.COMPLETED:
            result.model_path = job.get("output_path")
        elif status == GenerationStatus.FAILED:
            result.error = job.get("error", "Unknown error")

        return result

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        """Copy the generated model to the specified path.

        Since TripoSR generates locally, this just copies the file.
        """
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
        """TripoSR doesn't support style modifiers."""
        return []

    def get_supported_formats(self) -> list[str]:
        """Get supported output formats."""
        return list(self.SUPPORTED_FORMATS)

    def get_default_options(self) -> dict[str, Any]:
        """Get default generation options."""
        return {
            "quality": "medium",
            "output_format": "glb",
        }

    def get_info(self) -> dict[str, Any]:
        """Get detailed backend information."""
        info = super().get_info()
        available, dep_status = self._check_dependencies()

        info.update({
            "dependencies_status": dep_status,
            "device": self._get_device(),
            "model_loaded": self._model is not None,
            "output_directory": str(self._output_dir),
            "note": "TripoSR requires an input image. For text-to-3D, use a different backend.",
        })
        return info

    def initialize(self) -> bool:
        """Pre-load the model for faster generation."""
        return self._load_model()

    def shutdown(self) -> None:
        """Release model from memory."""
        self._model = None
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
