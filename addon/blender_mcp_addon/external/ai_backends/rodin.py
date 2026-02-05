"""Hyper3D Rodin AI backend for cloud-based 3D generation.

This backend integrates with the Hyper3D Rodin API for high-quality
text-to-3D and image-to-3D generation.

API Documentation: https://hyperhuman.deemos.com/docs
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


class RodinBackend(BaseBackend):
    """Hyper3D Rodin cloud backend for AI 3D generation."""

    name = "rodin"
    display_name = "Hyper3D Rodin"
    description = "Cloud-based high-quality 3D generation from Hyper3D"

    capabilities = {
        BackendCapability.TEXT_TO_3D,
        BackendCapability.IMAGE_TO_3D,
        BackendCapability.VARIATIONS,
        BackendCapability.CLOUD,
    }

    requires_api_key = True
    requires_local_install = False

    # API configuration
    API_BASE = "https://hyperhuman.deemos.com/api"
    API_VERSION = "v1"

    # Supported options
    SUPPORTED_FORMATS = ["glb", "gltf", "fbx", "obj", "usdz"]
    SUPPORTED_STYLES = ["realistic", "cartoon", "low_poly", "sculpture", "anime"]
    SUPPORTED_QUALITIES = ["draft", "medium", "high"]

    def __init__(self, config: BackendConfig | None = None):
        """Initialize the Rodin backend.

        Args:
            config: Optional configuration. API key can also come from
                    RODIN_API_KEY environment variable.
        """
        super().__init__(config)
        self._jobs: dict[str, dict] = {}  # Track job metadata

    def _get_api_key(self) -> str | None:
        """Get the API key from config or environment."""
        # Check config first
        if self.config.api_key:
            return self.config.api_key

        # Then environment
        api_key = os.environ.get("RODIN_API_KEY")
        if api_key:
            return api_key

        # Try Blender addon preferences
        try:
            import bpy

            prefs = bpy.context.preferences.addons.get("blender_mcp_addon")
            if prefs and hasattr(prefs, "preferences"):
                api_key = getattr(prefs.preferences, "rodin_api_key", None)
                if api_key:
                    return api_key
        except Exception:
            pass

        return None

    def is_available(self) -> bool:
        """Check if Rodin API is available."""
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
        """Make an authenticated request to the Rodin API.

        Args:
            endpoint: API endpoint (without base URL).
            method: HTTP method.
            data: Request body data.
            timeout: Request timeout in seconds.

        Returns:
            API response as dictionary.
        """
        api_key = self._get_api_key()
        if not api_key:
            return {
                "success": False,
                "error": "RODIN_API_KEY not configured",
            }

        timeout = timeout or self.config.timeout
        url = f"{self.API_BASE}/{self.API_VERSION}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
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
                error_message = error_data.get("message", error_data.get("error", str(e)))
            except Exception:
                error_message = error_body or str(e)
            return {
                "success": False,
                "error": f"API error ({e.code}): {error_message}",
                "status_code": e.code,
            }

        except urllib.error.URLError as e:
            return {"success": False, "error": f"Connection error: {e.reason}"}

        except TimeoutError:
            return {"success": False, "error": f"Request timed out after {timeout} seconds"}

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON response: {e}"}

        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {e}"}

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Start a generation job with Rodin API.

        Args:
            prompt: Text description of the desired model.
            image_path: Optional path to input image.
            style: Optional style modifier.
            quality: Generation quality.
            output_format: Output format.

        Returns:
            GenerationResult with job_id.
        """
        # Validate inputs
        if not prompt and not image_path:
            return GenerationResult(
                success=False,
                error="Either prompt or image_path is required",
                status=GenerationStatus.FAILED,
            )

        if output_format not in self.SUPPORTED_FORMATS:
            return GenerationResult(
                success=False,
                error=f"Unsupported format: {output_format}. Supported: {self.SUPPORTED_FORMATS}",
                status=GenerationStatus.FAILED,
            )

        if style and style not in self.SUPPORTED_STYLES:
            return GenerationResult(
                success=False,
                error=f"Unknown style: {style}. Supported: {self.SUPPORTED_STYLES}",
                status=GenerationStatus.FAILED,
            )

        # Prepare request
        if image_path:
            return self._generate_from_image(
                image_path, prompt, style, quality, output_format
            )
        else:
            return self._generate_from_text(prompt, style, quality, output_format)

    def _generate_from_text(
        self,
        prompt: str,
        style: str | None,
        quality: str,
        output_format: str,
    ) -> GenerationResult:
        """Generate from text prompt."""
        request_data = {
            "prompt": prompt.strip(),
            "quality": quality,
            "output_format": output_format,
        }
        if style:
            request_data["style"] = style

        result = self._make_request("rodin/generate", method="POST", data=request_data)

        if not result["success"]:
            return GenerationResult(
                success=False,
                error=result.get("error", "Unknown error"),
                status=GenerationStatus.FAILED,
            )

        data = result["data"]
        job_id = data.get("job_id") or data.get("uuid") or data.get("task_id")

        if not job_id:
            return GenerationResult(
                success=False,
                error="No job ID returned from API",
                status=GenerationStatus.FAILED,
                metadata={"raw_response": data},
            )

        # Track job metadata
        self._jobs[job_id] = {
            "prompt": prompt,
            "style": style,
            "quality": quality,
            "output_format": output_format,
            "type": "text_to_3d",
        }

        return GenerationResult(
            success=True,
            job_id=job_id,
            status=GenerationStatus.PROCESSING,
            message="Text-to-3D generation started",
            metadata={
                "prompt": prompt,
                "style": style,
                "quality": quality,
                "output_format": output_format,
                "backend": self.name,
            },
        )

    def _generate_from_image(
        self,
        image_path: str,
        prompt: str | None,
        style: str | None,
        quality: str,
        output_format: str,
    ) -> GenerationResult:
        """Generate from image."""
        path = Path(image_path)
        if not path.exists():
            return GenerationResult(
                success=False,
                error=f"Image not found: {image_path}",
                status=GenerationStatus.FAILED,
            )

        # Read and encode image
        try:
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return GenerationResult(
                success=False,
                error=f"Failed to read image: {e}",
                status=GenerationStatus.FAILED,
            )

        # Determine MIME type
        ext = path.suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(ext, "image/png")

        request_data = {
            "image": f"data:{mime_type};base64,{image_data}",
            "quality": quality,
            "output_format": output_format,
        }
        if prompt:
            request_data["prompt"] = prompt.strip()
        if style:
            request_data["style"] = style

        result = self._make_request(
            "rodin/image-to-3d", method="POST", data=request_data, timeout=120.0
        )

        if not result["success"]:
            return GenerationResult(
                success=False,
                error=result.get("error", "Unknown error"),
                status=GenerationStatus.FAILED,
            )

        data = result["data"]
        job_id = data.get("job_id") or data.get("uuid") or data.get("task_id")

        if not job_id:
            return GenerationResult(
                success=False,
                error="No job ID returned from API",
                status=GenerationStatus.FAILED,
            )

        # Track job metadata
        self._jobs[job_id] = {
            "image_path": image_path,
            "prompt": prompt,
            "style": style,
            "quality": quality,
            "output_format": output_format,
            "type": "image_to_3d",
        }

        return GenerationResult(
            success=True,
            job_id=job_id,
            status=GenerationStatus.PROCESSING,
            message="Image-to-3D generation started",
            metadata={
                "image_path": image_path,
                "prompt": prompt,
                "style": style,
                "quality": quality,
                "output_format": output_format,
                "backend": self.name,
            },
        )

    def get_status(self, job_id: str) -> GenerationResult:
        """Get status of a generation job."""
        if not job_id:
            return GenerationResult(
                success=False,
                error="Job ID is required",
                status=GenerationStatus.FAILED,
            )

        result = self._make_request(f"rodin/status/{job_id}")

        if not result["success"]:
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=result.get("error", "Unknown error"),
                status=GenerationStatus.FAILED,
            )

        data = result["data"]
        api_status = data.get("status", "unknown").lower()

        # Map API status to our status enum
        status_map = {
            "pending": GenerationStatus.PENDING,
            "queued": GenerationStatus.QUEUED,
            "processing": GenerationStatus.PROCESSING,
            "generating": GenerationStatus.PROCESSING,
            "completed": GenerationStatus.COMPLETED,
            "done": GenerationStatus.COMPLETED,
            "failed": GenerationStatus.FAILED,
            "error": GenerationStatus.FAILED,
            "cancelled": GenerationStatus.CANCELLED,
        }
        status = status_map.get(api_status, GenerationStatus.PROCESSING)

        gen_result = GenerationResult(
            success=status not in (GenerationStatus.FAILED, GenerationStatus.CANCELLED),
            job_id=job_id,
            status=status,
            progress=data.get("progress", 0.0),
            message=data.get("message", ""),
        )

        # Add download URL if completed
        if status == GenerationStatus.COMPLETED:
            download_url = (
                data.get("download_url")
                or data.get("model_url")
                or data.get("result", {}).get("url")
            )
            gen_result.download_url = download_url

        # Add error message if failed
        if status == GenerationStatus.FAILED:
            gen_result.error = data.get("error") or data.get("message") or "Generation failed"

        # Add ETA if available
        if "eta" in data:
            gen_result.metadata["eta_seconds"] = data["eta"]

        return gen_result

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        """Download the completed model."""
        # First get the download URL
        status_result = self.get_status(job_id)
        if not status_result.success:
            return status_result

        if status_result.status != GenerationStatus.COMPLETED:
            return GenerationResult(
                success=False,
                job_id=job_id,
                status=status_result.status,
                error=f"Job not completed. Current status: {status_result.status.value}",
            )

        download_url = status_result.download_url
        if not download_url:
            return GenerationResult(
                success=False,
                job_id=job_id,
                status=GenerationStatus.FAILED,
                error="No download URL available",
            )

        try:
            # Determine format from job metadata or URL
            job_meta = self._jobs.get(job_id, {})
            output_format = job_meta.get("output_format", "glb")

            # Ensure output path has correct extension
            output_path = Path(output_path)
            if not output_path.suffix:
                output_path = output_path.with_suffix(f".{output_format}")

            # Create parent directory if needed
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Download the file
            urllib.request.urlretrieve(download_url, str(output_path))

            if not output_path.exists() or output_path.stat().st_size == 0:
                return GenerationResult(
                    success=False,
                    job_id=job_id,
                    status=GenerationStatus.FAILED,
                    error="Download failed - empty file",
                )

            return GenerationResult(
                success=True,
                job_id=job_id,
                status=GenerationStatus.COMPLETED,
                model_path=str(output_path),
                message="Model downloaded successfully",
                metadata={
                    "format": output_format,
                    "size_bytes": output_path.stat().st_size,
                },
            )

        except Exception as e:
            return GenerationResult(
                success=False,
                job_id=job_id,
                status=GenerationStatus.FAILED,
                error=f"Download failed: {e}",
            )

    def cancel(self, job_id: str) -> GenerationResult:
        """Cancel an in-progress job."""
        result = self._make_request(f"rodin/cancel/{job_id}", method="POST")

        if result["success"]:
            return GenerationResult(
                success=True,
                job_id=job_id,
                status=GenerationStatus.CANCELLED,
                message="Job cancelled",
            )
        else:
            return GenerationResult(
                success=False,
                job_id=job_id,
                status=GenerationStatus.FAILED,
                error=result.get("error", "Failed to cancel job"),
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
            "style": None,
        }

    def get_info(self) -> dict[str, Any]:
        """Get backend info with additional Rodin-specific details."""
        info = super().get_info()
        info.update({
            "api_base": self.API_BASE,
            "supported_qualities": self.SUPPORTED_QUALITIES,
            "has_api_key": self._get_api_key() is not None,
        })
        return info
