"""Ollama Vision backend for local image understanding.

This backend uses Ollama with vision models (like LLaVA) to understand
images and generate detailed 3D model descriptions, which can then be
passed to text-to-3D backends.

This enables a fully local pipeline: image -> description -> 3D model
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


class OllamaVisionBackend(BaseBackend):
    """Ollama Vision backend for image understanding.

    This backend doesn't generate 3D models directly. Instead, it:
    1. Analyzes input images using vision models
    2. Generates detailed 3D-optimized descriptions
    3. Can be chained with text-to-3D backends

    Supported models: llava, llava:13b, bakllava, etc.
    """

    name = "ollama_vision"
    display_name = "Ollama Vision"
    description = "Local image understanding using Ollama vision models"

    capabilities = {
        BackendCapability.LOCAL,
        # Note: This doesn't have TEXT_TO_3D or IMAGE_TO_3D because
        # it generates descriptions, not 3D models directly
    }

    requires_api_key = False
    requires_local_install = True
    min_vram_gb = 8.0

    DEFAULT_HOST = "http://localhost:11434"
    DEFAULT_MODEL = "llava"

    # Prompt for generating 3D-optimized descriptions
    DESCRIPTION_PROMPT = """Analyze this image and provide a detailed description suitable for generating a 3D model.

Focus on:
1. The main subject/object(s)
2. Shape, proportions, and geometry
3. Materials and textures
4. Colors and surface details
5. Overall style (realistic, stylized, cartoon, etc.)

Be specific and descriptive. The description will be used to generate a 3D model."""

    def __init__(self, config: BackendConfig | None = None):
        super().__init__(config)
        self._host = config.extra.get("host", self.DEFAULT_HOST) if config else self.DEFAULT_HOST
        self._model = config.extra.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL

    def _get_host(self) -> str:
        return self.config.extra.get("host", self.DEFAULT_HOST) if self.config else self.DEFAULT_HOST

    def _get_model(self) -> str:
        return self.config.extra.get("model", self.DEFAULT_MODEL) if self.config else self.DEFAULT_MODEL

    def _check_ollama(self) -> tuple[bool, str]:
        """Check if Ollama is running and has a vision model."""
        host = self._get_host()

        try:
            req = urllib.request.Request(f"{host}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())

            models = [m.get("name", "") for m in data.get("models", [])]

            # Check for vision-capable models
            vision_models = ["llava", "bakllava", "llava:13b", "llava:34b"]
            available_vision = [m for m in models if any(v in m.lower() for v in vision_models)]

            if available_vision:
                return True, f"Vision models available: {', '.join(available_vision)}"
            else:
                return False, f"No vision models found. Install with: ollama pull llava"

        except urllib.error.URLError:
            return False, f"Cannot connect to Ollama at {host}. Is Ollama running?"
        except Exception as e:
            return False, f"Error checking Ollama: {e}"

    def is_available(self) -> bool:
        if not self.config.enabled:
            return False
        available, _ = self._check_ollama()
        return available

    def analyze_image(
        self,
        image_path: str,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Analyze an image and generate a 3D-optimized description.

        Args:
            image_path: Path to the image file.
            custom_prompt: Optional custom analysis prompt.

        Returns:
            Dictionary with description and analysis.
        """
        path = Path(image_path)
        if not path.exists():
            return {"success": False, "error": f"Image not found: {image_path}"}

        # Read and encode image
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        host = self._get_host()
        model = self._get_model()
        prompt = custom_prompt or self.DESCRIPTION_PROMPT

        request_data = {
            "model": model,
            "prompt": prompt,
            "images": [image_data],
            "stream": False,
        }

        try:
            req = urllib.request.Request(
                f"{host}/api/generate",
                data=json.dumps(request_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode())

            description = data.get("response", "")

            return {
                "success": True,
                "description": description,
                "model_used": model,
                "image_path": image_path,
            }

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
        """This backend doesn't generate 3D models directly.

        Use analyze_image() to get descriptions, then pass to a text-to-3D backend.
        """
        return GenerationResult(
            success=False,
            error=(
                "Ollama Vision doesn't generate 3D models directly. "
                "Use analyze_image() to get a description, then pass to a text-to-3D backend."
            ),
            status=GenerationStatus.FAILED,
            metadata={
                "suggestion": "Call analyze_image() first, then use the description with another backend",
            },
        )

    def get_status(self, job_id: str) -> GenerationResult:
        return GenerationResult(
            success=False,
            job_id=job_id,
            error="Ollama Vision doesn't track jobs",
            status=GenerationStatus.FAILED,
        )

    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        return GenerationResult(
            success=False,
            job_id=job_id,
            error="Ollama Vision doesn't generate downloadable models",
            status=GenerationStatus.FAILED,
        )

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        available, status = self._check_ollama()

        info.update({
            "ollama_host": self._get_host(),
            "model": self._get_model(),
            "ollama_status": status,
            "usage": (
                "Call analyze_image() to get descriptions from images, "
                "then use descriptions with text-to-3D backends"
            ),
        })
        return info
