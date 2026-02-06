"""AI model generation integration with multi-backend support.

This module provides a unified interface for AI-based 3D model generation,
supporting multiple backends including:
- Hyper3D Rodin (cloud)
- Meshy.ai (cloud)
- Tripo AI (cloud)
- TripoSR (local)
- Hunyuan3D (local)
- ComfyUI (local)

The module maintains backward compatibility with the original Rodin-only API
while providing access to the new multi-backend features.

API Documentation: https://hyperhuman.deemos.com/docs (Rodin)
"""

import tempfile
import time
from pathlib import Path
from typing import Any

import bpy

from .ai_backends import (
    GenerationStatus,
    get_backend_manager,
)
from .cache import cache_asset, get_cached_path, is_cached
from .job_queue import get_job_queue

# Re-export for backward compatibility
SUPPORTED_FORMATS = ["glb", "gltf", "fbx", "obj", "usdz"]
GENERATION_STYLES = ["realistic", "cartoon", "low_poly", "sculpture", "anime"]


# =============================================================================
# Backward-Compatible API (Original Functions)
# =============================================================================


def get_api_key() -> str | None:
    """Get the Rodin API key from environment or addon preferences.

    Maintained for backward compatibility.
    """
    import os

    api_key = os.environ.get("RODIN_API_KEY")
    if api_key:
        return api_key

    try:
        prefs = bpy.context.preferences.addons.get("blender_mcp_addon")
        if prefs and hasattr(prefs, "preferences"):
            api_key = getattr(prefs.preferences, "rodin_api_key", None)
            if api_key:
                return api_key
    except Exception:
        pass

    return None


def generate_model(
    prompt: str,
    style: str | None = None,
    quality: str = "medium",
    output_format: str = "glb",
    backend: str | None = None,
) -> dict[str, Any]:
    """Start generating a 3D model from a text prompt.

    This function uses the multi-backend system when available,
    falling back to the original Rodin implementation if needed.

    Args:
        prompt: Text description of the desired model.
        style: Optional style modifier (realistic, cartoon, etc.).
        quality: Generation quality (draft, medium, high).
        output_format: Output format (glb, gltf, fbx, obj, usdz).
        backend: Optional specific backend to use.

    Returns:
        Dictionary with job_id, status, and metadata.
    """
    if not prompt or not prompt.strip():
        return {"success": False, "error": "Prompt cannot be empty"}

    if output_format not in SUPPORTED_FORMATS:
        return {
            "success": False,
            "error": f"Unsupported format: {output_format}. Use: {', '.join(SUPPORTED_FORMATS)}",
        }

    if style and style not in GENERATION_STYLES:
        return {
            "success": False,
            "error": f"Unknown style: {style}. Available: {', '.join(GENERATION_STYLES)}",
        }

    # Use backend manager
    manager = get_backend_manager()
    result = manager.generate(
        prompt=prompt.strip(),
        style=style,
        quality=quality,
        output_format=output_format,
        backend=backend,
    )

    if not result.success:
        return {"success": False, "error": result.error}

    # Create job in queue for tracking
    queue = get_job_queue()
    job = queue.create_job(
        backend=backend or "auto",
        prompt=prompt,
        style=style,
        quality=quality,
        output_format=output_format,
        metadata={"external_job_id": result.job_id},
    )

    return {
        "success": True,
        "job_id": result.job_id,
        "internal_job_id": job.id,
        "status": result.status.value,
        "prompt": prompt,
        "style": style,
        "quality": quality,
        "output_format": output_format,
        "backend": result.metadata.get("backend", "unknown"),
        "message": "Model generation started. Use check_status to monitor progress.",
    }


def generate_model_from_image(
    image_path: str,
    prompt: str | None = None,
    style: str | None = None,
    quality: str = "medium",
    output_format: str = "glb",
    backend: str | None = None,
) -> dict[str, Any]:
    """Start generating a 3D model from an image.

    Args:
        image_path: Path to the input image.
        prompt: Optional text prompt to guide generation.
        style: Optional style modifier.
        quality: Generation quality (draft, medium, high).
        output_format: Output format (glb, gltf, fbx, obj, usdz).
        backend: Optional specific backend to use.

    Returns:
        Dictionary with job_id, status, and metadata.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return {"success": False, "error": f"Image not found: {image_path}"}

    if output_format not in SUPPORTED_FORMATS:
        return {
            "success": False,
            "error": f"Unsupported format: {output_format}. Use: {', '.join(SUPPORTED_FORMATS)}",
        }

    # Use backend manager
    manager = get_backend_manager()
    result = manager.generate(
        prompt=prompt or "",
        image_path=str(image_path),
        style=style,
        quality=quality,
        output_format=output_format,
        backend=backend,
    )

    if not result.success:
        return {"success": False, "error": result.error}

    # Create job in queue for tracking
    queue = get_job_queue()
    job = queue.create_job(
        backend=backend or "auto",
        prompt=prompt or f"Image-to-3D: {image_path.name}",
        image_path=str(image_path),
        style=style,
        quality=quality,
        output_format=output_format,
        metadata={"external_job_id": result.job_id},
    )

    return {
        "success": True,
        "job_id": result.job_id,
        "internal_job_id": job.id,
        "status": result.status.value,
        "source_image": str(image_path),
        "prompt": prompt,
        "style": style,
        "quality": quality,
        "output_format": output_format,
        "backend": result.metadata.get("backend", "unknown"),
        "message": "Image-to-3D generation started. Use check_status to monitor progress.",
    }


def check_status(job_id: str, auto_import: bool = True, backend: str | None = None) -> dict[str, Any]:
    """Check the status of an AI model generation job.

    Args:
        job_id: The job ID from generate_model or generate_model_from_image.
        auto_import: If True, automatically import completed models into Blender.
        backend: Optional backend hint for faster lookup.

    Returns:
        Dictionary with status, progress, and import info if completed.
    """
    if not job_id:
        return {"success": False, "error": "Job ID is required"}

    # Check if already cached
    if is_cached("ai_models", job_id):
        cached_path = get_cached_path("ai_models", job_id)
        if cached_path and auto_import:
            import_result = _import_model_file(cached_path, job_id)
            return {
                "success": True,
                "job_id": job_id,
                "status": "completed",
                "cached": True,
                "imported": import_result,
            }
        return {
            "success": True,
            "job_id": job_id,
            "status": "completed",
            "cached": True,
            "cached_path": str(cached_path) if cached_path else None,
        }

    # Get status from backend manager
    manager = get_backend_manager()
    result = manager.get_status(job_id, backend=backend)

    response = {
        "success": result.success,
        "job_id": job_id,
        "status": result.status.value,
        "progress": result.progress,
    }

    if result.message:
        response["message"] = result.message

    # Add ETA if available
    if "eta_seconds" in result.metadata:
        response["eta_seconds"] = result.metadata["eta_seconds"]

    # Handle completed jobs
    if result.status == GenerationStatus.COMPLETED:
        if result.model_path:
            # Local backend - model already available
            if auto_import:
                import_result = download_and_import(job_id, result.model_path, use_cache=True, is_local=True)
                response["imported"] = import_result
            else:
                response["model_path"] = result.model_path
        elif result.download_url and auto_import:
            # Cloud backend - need to download
            import_result = download_and_import(job_id, result.download_url)
            response["imported"] = import_result
        elif result.download_url:
            response["download_url"] = result.download_url

    # Handle failed jobs
    elif result.status in (GenerationStatus.FAILED,):
        response["success"] = False
        response["error"] = result.error or "Generation failed"

    # Update job queue
    queue = get_job_queue()
    queue.update_job(
        job_id,
        status=result.status.value,
        progress=result.progress,
        error=result.error,
    )

    return response


def download_and_import(
    job_id: str,
    source: str,
    use_cache: bool = True,
    is_local: bool = False,
) -> dict[str, Any]:
    """Download and import an AI-generated model.

    Args:
        job_id: Job ID for caching.
        source: URL to download from, or local path if is_local=True.
        use_cache: Whether to cache the downloaded file.
        is_local: If True, source is a local file path.

    Returns:
        Dictionary with import results.
    """
    import urllib.request

    try:
        if is_local:
            source_path = Path(source)
            ext = source_path.suffix
            import_path = source_path
        else:
            # Determine format from URL
            url_lower = source.lower()
            if ".obj" in url_lower:
                ext = ".obj"
            elif ".fbx" in url_lower:
                ext = ".fbx"
            elif ".gltf" in url_lower:
                ext = ".gltf"
            elif ".usdz" in url_lower:
                ext = ".usdz"
            else:
                ext = ".glb"

            # Download to temporary location
            temp_dir = tempfile.mkdtemp()
            temp_path = Path(temp_dir) / f"ai_model_{job_id}{ext}"

            urllib.request.urlretrieve(source, str(temp_path))

            if not temp_path.exists() or temp_path.stat().st_size == 0:
                return {"success": False, "error": "Download failed - empty file"}

            import_path = temp_path

        # Cache the file
        if use_cache:
            cached_path = cache_asset(
                source="ai_models",
                asset_id=job_id,
                file_path=import_path,
                metadata={
                    "source_url": source if not is_local else None,
                    "format": ext[1:],
                },
            )
            import_path = cached_path

        # Import into Blender
        return _import_model_file(import_path, job_id)

    except Exception as e:
        return {"success": False, "error": f"Download/import failed: {e}"}


def _import_model_file(filepath: Path, job_id: str) -> dict[str, Any]:
    """Import a model file into Blender.

    Args:
        filepath: Path to the model file.
        job_id: Job ID for naming.

    Returns:
        Dictionary with import results.
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    # Track objects before import
    objects_before = set(bpy.data.objects.keys())

    try:
        if ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=str(filepath))
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=str(filepath))
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(filepath))
        elif ext == ".usdz":
            if hasattr(bpy.ops.wm, "usd_import"):
                bpy.ops.wm.usd_import(filepath=str(filepath))
            else:
                return {"success": False, "error": "USD import not available in this Blender version"}
        elif ext == ".ply":
            bpy.ops.wm.ply_import(filepath=str(filepath))
        else:
            return {"success": False, "error": f"Unsupported format: {ext}"}

        # Find newly imported objects
        objects_after = set(bpy.data.objects.keys())
        new_objects = list(objects_after - objects_before)

        # Rename root objects to include job ID for identification
        for obj_name in new_objects:
            obj = bpy.data.objects.get(obj_name)
            if obj and obj.parent is None:
                obj.name = f"AI_Model_{job_id[:8]}_{obj_name}"

        # Update job queue
        queue = get_job_queue()
        queue.update_job(job_id, result_path=str(filepath), status="completed")

        return {
            "success": True,
            "imported": True,
            "filepath": str(filepath),
            "format": ext[1:],
            "objects": new_objects,
            "object_count": len(new_objects),
        }

    except Exception as e:
        return {"success": False, "error": f"Import failed: {e}", "imported": False}


def poll_until_complete(
    job_id: str,
    max_wait: float = 300.0,
    poll_interval: float = 5.0,
    auto_import: bool = True,
    backend: str | None = None,
) -> dict[str, Any]:
    """Poll a job until it completes or times out.

    Args:
        job_id: The job ID to poll.
        max_wait: Maximum time to wait in seconds.
        poll_interval: Time between polls in seconds.
        auto_import: Whether to auto-import when complete.
        backend: Optional backend hint.

    Returns:
        Final status dictionary.
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed >= max_wait:
            return {
                "success": False,
                "job_id": job_id,
                "status": "timeout",
                "error": f"Timed out after {max_wait} seconds",
                "elapsed_seconds": elapsed,
            }

        result = check_status(job_id, auto_import=auto_import, backend=backend)

        status = result.get("status", "unknown")
        if status in ("completed", "failed", "error", "cancelled"):
            result["elapsed_seconds"] = elapsed
            return result

        time.sleep(poll_interval)


# =============================================================================
# New Multi-Backend API
# =============================================================================


def list_backends(available_only: bool = True) -> dict[str, Any]:
    """List all available AI generation backends.

    Args:
        available_only: If True, only return backends ready to use.

    Returns:
        Dictionary with list of backends and their capabilities.
    """
    manager = get_backend_manager()
    backends = manager.list_backends(available_only=available_only)

    return {
        "success": True,
        "backends": backends,
        "count": len(backends),
        "preferred": manager._preferred_backend,
        "prefer_local": manager._prefer_local,
    }


def set_preferred_backend(backend: str | None, prefer_local: bool | None = None) -> dict[str, Any]:
    """Set the preferred backend for generation.

    Args:
        backend: Backend name or None for auto-selection.
        prefer_local: If True, prefer local backends over cloud.

    Returns:
        Dictionary confirming the setting.
    """
    manager = get_backend_manager()

    try:
        manager.set_preferred_backend(backend)
        if prefer_local is not None:
            manager.set_prefer_local(prefer_local)

        return {
            "success": True,
            "preferred_backend": backend,
            "prefer_local": manager._prefer_local,
            "available_backends": manager.get_available_backends(),
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}


def get_backend_info(backend: str) -> dict[str, Any]:
    """Get detailed information about a specific backend.

    Args:
        backend: Backend name.

    Returns:
        Dictionary with backend details.
    """
    manager = get_backend_manager()
    info = manager.get_backend_info(backend)

    if info:
        return {"success": True, **info}
    return {"success": False, "error": f"Unknown backend: {backend}"}


def configure_backend(backend: str, config: dict[str, Any]) -> dict[str, Any]:
    """Configure a specific backend.

    Args:
        backend: Backend name.
        config: Configuration dictionary.

    Returns:
        Dictionary confirming the configuration.
    """
    manager = get_backend_manager()

    if manager.configure_backend(backend, config):
        return {
            "success": True,
            "backend": backend,
            "configured": True,
        }
    return {"success": False, "error": f"Unknown backend: {backend}"}


def cancel_generation(job_id: str, backend: str | None = None) -> dict[str, Any]:
    """Cancel an in-progress generation job.

    Args:
        job_id: The job ID to cancel.
        backend: Optional backend hint.

    Returns:
        Dictionary with cancellation status.
    """
    manager = get_backend_manager()
    result = manager.cancel(job_id, backend=backend)

    # Update job queue
    if result.success:
        queue = get_job_queue()
        queue.update_job(job_id, status="cancelled")

    return {
        "success": result.success,
        "job_id": job_id,
        "status": result.status.value,
        "error": result.error,
    }


def get_generation_history(limit: int = 50) -> dict[str, Any]:
    """Get generation history.

    Args:
        limit: Maximum number of entries to return.

    Returns:
        Dictionary with generation history.
    """
    queue = get_job_queue()
    history = queue.get_history(limit=limit)

    return {
        "success": True,
        "history": history,
        "count": len(history),
    }


def clear_generation_history(older_than_hours: float | None = None) -> dict[str, Any]:
    """Clear generation history.

    Args:
        older_than_hours: Only clear entries older than this.

    Returns:
        Dictionary with number of entries cleared.
    """
    queue = get_job_queue()
    cleared = queue.clear_completed(older_than_hours=older_than_hours)

    return {
        "success": True,
        "cleared": cleared,
    }


# =============================================================================
# Helper Functions (Backward Compatibility)
# =============================================================================


def list_styles() -> dict[str, Any]:
    """List available generation styles.

    Returns:
        Dictionary with available styles.
    """
    return {
        "success": True,
        "styles": GENERATION_STYLES,
        "description": {
            "realistic": "Photorealistic style with detailed textures",
            "cartoon": "Stylized cartoon/toon shading",
            "low_poly": "Low polygon count, flat shading",
            "sculpture": "Smooth, sculpture-like appearance",
            "anime": "Anime/manga inspired style",
        },
    }


def list_formats() -> dict[str, Any]:
    """List supported output formats.

    Returns:
        Dictionary with supported formats.
    """
    return {
        "success": True,
        "formats": SUPPORTED_FORMATS,
        "recommended": "glb",
        "description": {
            "glb": "Binary glTF - recommended, compact with embedded textures",
            "gltf": "Text-based glTF with separate files",
            "fbx": "Autodesk FBX - good for other 3D software",
            "obj": "Wavefront OBJ - legacy format, no materials",
            "usdz": "Universal Scene Description - Apple ecosystem",
        },
    }
