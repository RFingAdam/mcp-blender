"""AI generation backends with unified management.

This module provides a unified interface for multiple AI 3D generation backends,
including cloud APIs (Rodin, Meshy, Tripo) and local models (TripoSR, Hunyuan3D).

Example usage:
    from external.ai_backends import get_backend_manager

    manager = get_backend_manager()

    # List available backends
    backends = manager.list_backends()

    # Generate with auto-selected backend
    result = manager.generate("a red sports car")

    # Generate with specific backend
    result = manager.generate("a red sports car", backend="rodin")
"""

from typing import Any

from .base import (
    BackendCapability,
    BackendConfig,
    BaseBackend,
    GenerationResult,
    GenerationStatus,
)

# Global backend manager instance
_backend_manager: "BackendManager | None" = None


class NoBackendAvailableError(Exception):
    """Raised when no suitable backend is available for the requested operation."""

    pass


class BackendManager:
    """Manages AI generation backends with unified interface.

    The BackendManager handles:
    - Backend registration and discovery
    - Automatic backend selection based on capabilities
    - Fallback chains when preferred backends are unavailable
    - Configuration management
    """

    def __init__(self):
        """Initialize the backend manager."""
        self._backends: dict[str, BaseBackend] = {}
        self._preferred_backend: str | None = None
        self._prefer_local: bool = False
        self._fallback_chain: list[str] = [
            "rodin",
            "meshy",
            "tripo",
            "hunyuan3d",
            "triposr",
            "stable_fast_3d",
        ]
        self._auto_register_backends()

    def _auto_register_backends(self) -> None:
        """Auto-register available backends."""
        # Import and register each backend type
        # Backends handle their own availability checks

        try:
            from .rodin import RodinBackend

            self.register_backend(RodinBackend())
        except ImportError:
            pass

        try:
            from .triposr import TripoSRBackend

            self.register_backend(TripoSRBackend())
        except ImportError:
            pass

        try:
            from .hunyuan3d import Hunyuan3DBackend

            self.register_backend(Hunyuan3DBackend())
        except ImportError:
            pass

        try:
            from .stable_fast_3d import StableFast3DBackend

            self.register_backend(StableFast3DBackend())
        except ImportError:
            pass

        try:
            from .meshy import MeshyBackend

            self.register_backend(MeshyBackend())
        except ImportError:
            pass

        try:
            from .tripo_ai import TripoAIBackend

            self.register_backend(TripoAIBackend())
        except ImportError:
            pass

        try:
            from .ollama_vision import OllamaVisionBackend

            self.register_backend(OllamaVisionBackend())
        except ImportError:
            pass

        try:
            from .comfyui import ComfyUIBackend

            self.register_backend(ComfyUIBackend())
        except ImportError:
            pass

    def register_backend(self, backend: BaseBackend) -> None:
        """Register a backend with the manager.

        Args:
            backend: Backend instance to register.
        """
        self._backends[backend.name] = backend

    def unregister_backend(self, name: str) -> bool:
        """Unregister a backend.

        Args:
            name: Name of the backend to unregister.

        Returns:
            True if backend was removed, False if not found.
        """
        if name in self._backends:
            backend = self._backends.pop(name)
            backend.shutdown()
            return True
        return False

    def get_backend(self, name: str) -> BaseBackend | None:
        """Get a specific backend by name.

        Args:
            name: Backend name.

        Returns:
            Backend instance or None if not found.
        """
        return self._backends.get(name)

    def list_backends(self, available_only: bool = False) -> list[dict[str, Any]]:
        """List all registered backends.

        Args:
            available_only: If True, only return backends that are currently available.

        Returns:
            List of backend info dictionaries.
        """
        result = []
        for backend in self._backends.values():
            if available_only and not backend.is_available():
                continue
            result.append(backend.get_info())
        return result

    def get_available_backends(self) -> list[str]:
        """Get names of all available backends.

        Returns:
            List of backend names that are ready to use.
        """
        return [name for name, backend in self._backends.items() if backend.is_available()]

    def set_preferred_backend(self, name: str | None) -> None:
        """Set the preferred backend for generation.

        Args:
            name: Backend name, or None for auto-selection.
        """
        if name is not None and name not in self._backends:
            raise ValueError(f"Unknown backend: {name}")
        self._preferred_backend = name

    def set_prefer_local(self, prefer_local: bool) -> None:
        """Set whether to prefer local backends over cloud.

        Args:
            prefer_local: If True, prefer local backends when available.
        """
        self._prefer_local = prefer_local

    def select_backend(
        self,
        capabilities_needed: set[BackendCapability] | None = None,
        prefer_local: bool | None = None,
    ) -> BaseBackend:
        """Select the best available backend for the task.

        Args:
            capabilities_needed: Required capabilities for the task.
            prefer_local: Override the default local preference.

        Returns:
            Selected backend.

        Raises:
            NoBackendAvailableError: If no suitable backend is available.
        """
        if capabilities_needed is None:
            capabilities_needed = {BackendCapability.TEXT_TO_3D}

        prefer_local = prefer_local if prefer_local is not None else self._prefer_local

        # If preferred backend is set and available, use it
        if self._preferred_backend:
            backend = self._backends.get(self._preferred_backend)
            if backend and backend.is_available():
                if capabilities_needed.issubset(backend.capabilities):
                    return backend

        available = self.get_available_backends()
        if not available:
            raise NoBackendAvailableError("No AI backends are available")

        # Filter by capabilities
        candidates = []
        for name in available:
            backend = self._backends[name]
            if capabilities_needed.issubset(backend.capabilities):
                candidates.append(backend)

        if not candidates:
            raise NoBackendAvailableError(
                f"No backend supports required capabilities: {[c.value for c in capabilities_needed]}"
            )

        # Prefer local if requested
        if prefer_local:
            local_candidates = [
                b for b in candidates if BackendCapability.LOCAL in b.capabilities
            ]
            if local_candidates:
                candidates = local_candidates

        # Use fallback chain priority
        for name in self._fallback_chain:
            for candidate in candidates:
                if candidate.name == name:
                    return candidate

        # Return first available candidate
        return candidates[0]

    def generate(
        self,
        prompt: str,
        image_path: str | None = None,
        backend: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        **kwargs,
    ) -> GenerationResult:
        """Generate a 3D model using the best available backend.

        Args:
            prompt: Text description of the desired model.
            image_path: Optional path to input image for image-to-3D.
            backend: Optional specific backend name to use.
            style: Optional style modifier.
            quality: Generation quality (draft, medium, high).
            output_format: Output format (glb, gltf, fbx, obj).
            **kwargs: Backend-specific options.

        Returns:
            GenerationResult with job_id and status.
        """
        # Determine capabilities needed
        capabilities = set()
        if image_path:
            capabilities.add(BackendCapability.IMAGE_TO_3D)
        else:
            capabilities.add(BackendCapability.TEXT_TO_3D)

        # Select backend
        if backend:
            selected_backend = self._backends.get(backend)
            if not selected_backend:
                return GenerationResult(
                    success=False,
                    error=f"Unknown backend: {backend}",
                    status=GenerationStatus.FAILED,
                )
            if not selected_backend.is_available():
                return GenerationResult(
                    success=False,
                    error=f"Backend '{backend}' is not available",
                    status=GenerationStatus.FAILED,
                )
        else:
            try:
                selected_backend = self.select_backend(capabilities)
            except NoBackendAvailableError as e:
                return GenerationResult(
                    success=False, error=str(e), status=GenerationStatus.FAILED
                )

        # Generate
        return selected_backend.generate(
            prompt=prompt,
            image_path=image_path,
            style=style,
            quality=quality,
            output_format=output_format,
            **kwargs,
        )

    def get_status(self, job_id: str, backend: str | None = None) -> GenerationResult:
        """Get the status of a generation job.

        Args:
            job_id: The job ID to check.
            backend: Optional backend name (if known).

        Returns:
            GenerationResult with current status.
        """
        # If backend specified, use it directly
        if backend:
            selected_backend = self._backends.get(backend)
            if selected_backend:
                return selected_backend.get_status(job_id)
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=f"Unknown backend: {backend}",
                status=GenerationStatus.FAILED,
            )

        # Otherwise, try all available backends
        for backend_instance in self._backends.values():
            if backend_instance.is_available():
                result = backend_instance.get_status(job_id)
                if result.success or result.status != GenerationStatus.FAILED:
                    return result

        return GenerationResult(
            success=False,
            job_id=job_id,
            error="Job not found in any backend",
            status=GenerationStatus.FAILED,
        )

    def download_result(
        self, job_id: str, output_path: str, backend: str | None = None
    ) -> GenerationResult:
        """Download a completed model.

        Args:
            job_id: The job ID.
            output_path: Where to save the model.
            backend: Optional backend name.

        Returns:
            GenerationResult with model_path on success.
        """
        if backend:
            selected_backend = self._backends.get(backend)
            if selected_backend:
                return selected_backend.download_result(job_id, output_path)
            return GenerationResult(
                success=False,
                job_id=job_id,
                error=f"Unknown backend: {backend}",
                status=GenerationStatus.FAILED,
            )

        # Try all backends
        for backend_instance in self._backends.values():
            if backend_instance.is_available():
                result = backend_instance.download_result(job_id, output_path)
                if result.success:
                    return result

        return GenerationResult(
            success=False,
            job_id=job_id,
            error="Could not download from any backend",
            status=GenerationStatus.FAILED,
        )

    def cancel(self, job_id: str, backend: str | None = None) -> GenerationResult:
        """Cancel an in-progress generation.

        Args:
            job_id: The job ID to cancel.
            backend: Optional backend name.

        Returns:
            GenerationResult indicating cancellation status.
        """
        if backend:
            selected_backend = self._backends.get(backend)
            if selected_backend:
                return selected_backend.cancel(job_id)

        # Try all backends
        for backend_instance in self._backends.values():
            if backend_instance.is_available():
                result = backend_instance.cancel(job_id)
                if result.success:
                    return result

        return GenerationResult(
            success=False,
            job_id=job_id,
            error="Could not cancel job",
            status=GenerationStatus.FAILED,
        )

    def configure_backend(self, name: str, config: dict[str, Any]) -> bool:
        """Configure a specific backend.

        Args:
            name: Backend name.
            config: Configuration dictionary.

        Returns:
            True if configuration was applied.
        """
        backend = self._backends.get(name)
        if not backend:
            return False

        # Update backend config
        if "enabled" in config:
            backend.config.enabled = config["enabled"]
        if "api_key" in config:
            backend.config.api_key = config["api_key"]
        if "api_base_url" in config:
            backend.config.api_base_url = config["api_base_url"]
        if "model_path" in config:
            backend.config.model_path = config["model_path"]
        if "device" in config:
            backend.config.device = config["device"]
        if "timeout" in config:
            backend.config.timeout = config["timeout"]

        # Store any extra config
        for key, value in config.items():
            if key not in ["enabled", "api_key", "api_base_url", "model_path", "device", "timeout"]:
                backend.config.extra[key] = value

        return True

    def get_backend_info(self, name: str) -> dict[str, Any] | None:
        """Get detailed info about a specific backend.

        Args:
            name: Backend name.

        Returns:
            Backend info dictionary or None if not found.
        """
        backend = self._backends.get(name)
        if backend:
            return backend.get_info()
        return None


def get_backend_manager() -> BackendManager:
    """Get the global backend manager instance.

    Returns:
        The singleton BackendManager instance.
    """
    global _backend_manager
    if _backend_manager is None:
        _backend_manager = BackendManager()
    return _backend_manager


def reset_backend_manager() -> None:
    """Reset the global backend manager (for testing)."""
    global _backend_manager
    if _backend_manager:
        for backend in _backend_manager._backends.values():
            backend.shutdown()
    _backend_manager = None


__all__ = [
    "BackendCapability",
    "BackendConfig",
    "BackendManager",
    "BaseBackend",
    "GenerationResult",
    "GenerationStatus",
    "NoBackendAvailableError",
    "get_backend_manager",
    "reset_backend_manager",
]
