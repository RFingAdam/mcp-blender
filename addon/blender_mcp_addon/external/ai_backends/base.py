"""Base classes for AI generation backends.

This module defines the abstract interface that all AI backends must implement,
along with common enums and data structures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BackendCapability(Enum):
    """Capabilities that backends may support."""

    TEXT_TO_3D = "text_to_3d"
    IMAGE_TO_3D = "image_to_3d"
    MESH_REFINEMENT = "mesh_refinement"
    TEXTURE_GENERATION = "texture_generation"
    VARIATIONS = "variations"
    LOCAL = "local"
    CLOUD = "cloud"


class GenerationStatus(Enum):
    """Status of a generation job."""

    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class GenerationResult:
    """Result from a generation operation."""

    success: bool
    job_id: str | None = None
    status: GenerationStatus = GenerationStatus.PENDING
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    model_path: str | None = None
    download_url: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "job_id": self.job_id,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "model_path": self.model_path,
            "download_url": self.download_url,
            "metadata": self.metadata,
        }


@dataclass
class BackendConfig:
    """Configuration for a backend."""

    enabled: bool = True
    api_key: str | None = None
    api_base_url: str | None = None
    model_path: str | None = None
    device: str = "auto"  # auto, cuda, cpu, mps
    timeout: float = 300.0
    extra: dict = field(default_factory=dict)


class BaseBackend(ABC):
    """Abstract base class for AI generation backends.

    All AI backends (cloud APIs, local models) must implement this interface
    to be usable through the unified backend manager.
    """

    # Backend identification
    name: str = "base"
    display_name: str = "Base Backend"
    description: str = "Abstract base backend"

    # Backend capabilities
    capabilities: set[BackendCapability] = set()

    # Requirements
    requires_api_key: bool = False
    requires_local_install: bool = False
    min_vram_gb: float = 0.0

    def __init__(self, config: BackendConfig | None = None):
        """Initialize the backend with optional configuration.

        Args:
            config: Backend configuration. If None, default config is used.
        """
        self.config = config or BackendConfig()
        self._initialized = False

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is configured and available for use.

        Returns:
            True if the backend can accept generation requests.
        """
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Start a generation job.

        Args:
            prompt: Text description of the desired model.
            image_path: Optional path to input image for image-to-3D.
            style: Optional style modifier.
            quality: Generation quality (draft, medium, high).
            output_format: Output format (glb, gltf, fbx, obj, usdz).
            **kwargs: Backend-specific options.

        Returns:
            GenerationResult with job_id and initial status.
        """
        pass

    @abstractmethod
    def get_status(self, job_id: str) -> GenerationResult:
        """Get the status of a generation job.

        Args:
            job_id: The job ID from generate().

        Returns:
            GenerationResult with current status and progress.
        """
        pass

    @abstractmethod
    def download_result(self, job_id: str, output_path: str) -> GenerationResult:
        """Download the completed model.

        Args:
            job_id: The job ID from generate().
            output_path: Path where the model should be saved.

        Returns:
            GenerationResult with model_path set on success.
        """
        pass

    def cancel(self, job_id: str) -> GenerationResult:
        """Cancel an in-progress generation job.

        Args:
            job_id: The job ID to cancel.

        Returns:
            GenerationResult indicating cancellation status.
        """
        # Default implementation - not all backends support cancellation
        return GenerationResult(
            success=False,
            job_id=job_id,
            status=GenerationStatus.FAILED,
            error="Cancellation not supported by this backend",
        )

    def get_default_options(self) -> dict[str, Any]:
        """Get default generation options for this backend.

        Returns:
            Dictionary of default option values.
        """
        return {
            "quality": "medium",
            "output_format": "glb",
        }

    def get_supported_styles(self) -> list[str]:
        """Get list of supported generation styles.

        Returns:
            List of style names this backend supports.
        """
        return ["realistic", "cartoon", "low_poly", "sculpture", "anime"]

    def get_supported_formats(self) -> list[str]:
        """Get list of supported output formats.

        Returns:
            List of format extensions this backend supports.
        """
        return ["glb", "gltf", "fbx", "obj"]

    def get_info(self) -> dict[str, Any]:
        """Get detailed information about this backend.

        Returns:
            Dictionary with backend details.
        """
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "capabilities": [c.value for c in self.capabilities],
            "requires_api_key": self.requires_api_key,
            "requires_local_install": self.requires_local_install,
            "min_vram_gb": self.min_vram_gb,
            "available": self.is_available(),
            "supported_styles": self.get_supported_styles(),
            "supported_formats": self.get_supported_formats(),
            "default_options": self.get_default_options(),
        }

    def initialize(self) -> bool:
        """Initialize the backend (load models, etc).

        For local backends, this may involve loading model weights into memory.
        For cloud backends, this may verify API connectivity.

        Returns:
            True if initialization succeeded.
        """
        self._initialized = True
        return True

    def shutdown(self) -> None:
        """Shutdown the backend and release resources."""
        self._initialized = False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, available={self.is_available()})"
