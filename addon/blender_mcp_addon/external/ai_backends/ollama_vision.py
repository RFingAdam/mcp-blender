"""Ollama Vision backend for local image understanding.

This backend uses Ollama with vision models (like LLaVA) to understand
images and generate detailed 3D model descriptions, which can then be
passed to text-to-3D backends.

This enables a fully local pipeline: image -> description -> 3D model
"""

import base64
import json
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
            vision_keywords = [
                "llava", "bakllava", "vision", "moondream",
                "llama3.2-vision", "minicpm-v", "cogvlm",
            ]
            available_vision = [m for m in models if any(v in m.lower() for v in vision_keywords)]

            if available_vision:
                return True, f"Vision models available: {', '.join(available_vision)}"
            else:
                return False, "No vision models found. Install with: ollama pull llava"

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

    EVALUATION_PROMPT = """You are evaluating a {category} output from a 3D content pipeline.

{category_criteria}

Respond with ONLY a valid JSON object (no markdown, no extra text):
{{
  "overall_score": <float 0.0-1.0>,
  "per_element_scores": {{
    "<element_name>": <float 0.0-1.0>
  }},
  "suggestions": [
    {{
      "priority": "<high|medium|low>",
      "area": "<what to improve>",
      "action": "<specific improvement action>"
    }}
  ],
  "convergence_signal": <true if output looks good enough, false if needs more work>
}}

{user_prompt}"""

    CATEGORY_CRITERIA = {
        "model": (
            "Evaluate the 3D model for:\n"
            "1. Geometric accuracy and proportions\n"
            "2. Mesh topology and edge flow\n"
            "3. Level of detail and features\n"
            "4. Surface smoothness and artifacts\n"
            "5. Overall silhouette correctness"
        ),
        "texture": (
            "Evaluate the PBR texture for:\n"
            "1. Material realism and PBR accuracy\n"
            "2. Tiling and seam visibility\n"
            "3. Color accuracy and consistency\n"
            "4. Normal map quality and depth\n"
            "5. Roughness/metallic map correctness"
        ),
        "animation": (
            "Evaluate the animation for:\n"
            "1. Motion quality and fluidity\n"
            "2. Timing and spacing of keyframes\n"
            "3. Physics realism (weight, momentum)\n"
            "4. Easing and acceleration curves\n"
            "5. Overall believability of movement"
        ),
    }

    REFINEMENT_PROMPT = """You are analyzing renders of a 3D model from multiple angles.

Evaluate the model and respond with ONLY a valid JSON object (no markdown, no extra text):
{{
  "overall_quality": <float 0.0-1.0>,
  "issues": [
    {{
      "category": "<geometry|topology|proportion|detail|surface>",
      "severity": "<low|medium|high>",
      "description": "<what is wrong>",
      "location": "<where on the model>",
      "suggested_fix": "<bmesh/Blender operation to fix it>"
    }}
  ],
  "missing_features": ["<feature that should exist but doesn't>"],
  "proportion_issues": ["<description of proportion problem>"],
  "convergence_signal": <true if model looks good enough, false if needs more work>
}}

{user_prompt}"""

    def analyze_for_refinement(
        self,
        image_paths: list[str],
        reference_image: str | None = None,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Analyze rendered views for refinement feedback.

        Args:
            image_paths: Paths to rendered angle images.
            reference_image: Optional reference image to compare against.
            prompt: Additional context for analysis.

        Returns:
            Structured analysis with quality score and issues.
        """
        host = self._get_host()
        model = self._get_model()

        all_images = []

        # Encode reference image first if provided
        if reference_image:
            ref_path = Path(reference_image)
            if ref_path.exists():
                with open(ref_path, "rb") as f:
                    all_images.append(base64.b64encode(f.read()).decode("utf-8"))

        # Encode render images
        for img_path in image_paths:
            path = Path(img_path)
            if path.exists():
                with open(path, "rb") as f:
                    all_images.append(base64.b64encode(f.read()).decode("utf-8"))

        if not all_images:
            return {"success": False, "error": "No valid images to analyze"}

        user_prompt = prompt
        if reference_image:
            user_prompt = f"The first image is the reference. Compare the model renders against it. {prompt}"

        full_prompt = self.REFINEMENT_PROMPT.format(user_prompt=user_prompt)

        request_data = {
            "model": model,
            "prompt": full_prompt,
            "images": all_images,
            "stream": False,
        }

        try:
            req = urllib.request.Request(
                f"{host}/api/generate",
                data=json.dumps(request_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=180) as response:
                data = json.loads(response.read().decode())

            raw_response = data.get("response", "")

            # Try to parse structured JSON from response
            try:
                # Find JSON in the response (may be wrapped in markdown)
                json_str = raw_response
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0]
                analysis = json.loads(json_str.strip())
            except (json.JSONDecodeError, IndexError):
                # If parsing fails, return raw response with default score
                analysis = {
                    "overall_quality": 0.5,
                    "issues": [],
                    "missing_features": [],
                    "proportion_issues": [],
                    "convergence_signal": False,
                    "raw_response": raw_response,
                }

            analysis["success"] = True
            analysis["model_used"] = model
            return analysis

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "overall_quality": 0.0,
            }

    def evaluate_output(
        self,
        image_path: str,
        category: str = "model",
        reference_image: str | None = None,
        prompt: str = "",
    ) -> dict[str, Any]:
        """Evaluate any render/output using category-specific criteria.

        Args:
            image_path: Path to the image to evaluate.
            category: Evaluation category (model, texture, animation).
            reference_image: Optional reference image for comparison.
            prompt: Additional evaluation context.

        Returns:
            Structured evaluation with scores and suggestions.
        """
        host = self._get_host()
        model = self._get_model()

        category_criteria = self.CATEGORY_CRITERIA.get(
            category, self.CATEGORY_CRITERIA["model"],
        )

        all_images = []

        # Encode reference image first if provided
        if reference_image:
            ref_path = Path(reference_image)
            if ref_path.exists():
                with open(ref_path, "rb") as f:
                    all_images.append(base64.b64encode(f.read()).decode("utf-8"))

        # Encode the main image
        path = Path(image_path)
        if not path.exists():
            return {"success": False, "error": f"Image not found: {image_path}"}
        with open(path, "rb") as f:
            all_images.append(base64.b64encode(f.read()).decode("utf-8"))

        user_prompt = prompt
        if reference_image:
            user_prompt = f"The first image is the reference. Compare against it. {prompt}"

        full_prompt = self.EVALUATION_PROMPT.format(
            category=category,
            category_criteria=category_criteria,
            user_prompt=user_prompt,
        )

        request_data = {
            "model": model,
            "prompt": full_prompt,
            "images": all_images,
            "stream": False,
        }

        try:
            req = urllib.request.Request(
                f"{host}/api/generate",
                data=json.dumps(request_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=180) as response:
                data = json.loads(response.read().decode())

            raw_response = data.get("response", "")

            # Parse structured JSON from response
            try:
                json_str = raw_response
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0]
                evaluation = json.loads(json_str.strip())
            except (json.JSONDecodeError, IndexError):
                evaluation = {
                    "overall_score": 0.5,
                    "per_element_scores": {},
                    "suggestions": [],
                    "convergence_signal": False,
                    "raw_response": raw_response,
                }

            evaluation["success"] = True
            evaluation["model_used"] = model
            evaluation["category"] = category
            return evaluation

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "overall_score": 0.0,
            }

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
