"""AI model generation integration (Hyper3D Rodin).

This module provides integration with Hyper3D Rodin for AI-based 3D model generation.
It supports text-to-3D and image-to-3D generation with caching and status polling.

API Documentation: https://hyperhuman.deemos.com/docs
"""

import base64
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import bpy

from .cache import cache_asset, get_cached_path, is_cached

# Hyper3D Rodin API configuration
RODIN_API_BASE = "https://hyperhuman.deemos.com/api"
RODIN_API_VERSION = "v1"

# Supported output formats
SUPPORTED_FORMATS = ["glb", "gltf", "fbx", "obj", "usdz"]

# Generation styles
GENERATION_STYLES = [
    "realistic",
    "cartoon",
    "low_poly",
    "sculpture",
    "anime",
]


def get_api_key() -> str | None:
    """Get the Rodin API key from environment or addon preferences."""
    # First check environment variable
    api_key = os.environ.get("RODIN_API_KEY")
    if api_key:
        return api_key

    # Check addon preferences if available
    try:
        prefs = bpy.context.preferences.addons.get("blender_mcp_addon")
        if prefs and hasattr(prefs, "preferences"):
            api_key = getattr(prefs.preferences, "rodin_api_key", None)
            if api_key:
                return api_key
    except Exception:
        pass

    return None


def _make_request(
    endpoint: str,
    method: str = "GET",
    data: dict | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Make an authenticated request to the Rodin API.

    Args:
        endpoint: API endpoint (without base URL)
        method: HTTP method (GET, POST)
        data: Request body data (for POST)
        timeout: Request timeout in seconds

    Returns:
        API response as dictionary
    """
    api_key = get_api_key()
    if not api_key:
        return {
            "success": False,
            "error": "RODIN_API_KEY environment variable not set",
            "help": "Get an API key from https://hyperhuman.deemos.com and set RODIN_API_KEY environment variable",
        }

    url = f"{RODIN_API_BASE}/{RODIN_API_VERSION}/{endpoint}"
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
        return {
            "success": False,
            "error": f"Connection error: {e.reason}",
        }

    except TimeoutError:
        return {
            "success": False,
            "error": f"Request timed out after {timeout} seconds",
        }

    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"Invalid JSON response: {e}",
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {e}",
        }


def generate_model(
    prompt: str,
    style: str | None = None,
    quality: str = "medium",
    output_format: str = "glb",
) -> dict[str, Any]:
    """Start generating a 3D model from a text prompt.

    Args:
        prompt: Text description of the desired model
        style: Optional style modifier (realistic, cartoon, low_poly, etc.)
        quality: Generation quality (draft, medium, high)
        output_format: Output format (glb, gltf, fbx, obj, usdz)

    Returns:
        Dictionary with job_id, status, and metadata
    """
    if not prompt or not prompt.strip():
        return {"success": False, "error": "Prompt cannot be empty"}

    if output_format not in SUPPORTED_FORMATS:
        return {
            "success": False,
            "error": f"Unsupported format: {output_format}. Supported: {', '.join(SUPPORTED_FORMATS)}",
        }

    if style and style not in GENERATION_STYLES:
        return {
            "success": False,
            "error": f"Unknown style: {style}. Available: {', '.join(GENERATION_STYLES)}",
        }

    request_data = {
        "prompt": prompt.strip(),
        "quality": quality,
        "output_format": output_format,
    }
    if style:
        request_data["style"] = style

    result = _make_request("rodin/generate", method="POST", data=request_data)

    if not result["success"]:
        return result

    data = result["data"]
    job_id = data.get("job_id") or data.get("uuid") or data.get("task_id")

    if not job_id:
        return {
            "success": False,
            "error": "No job ID returned from API",
            "raw_response": data,
        }

    return {
        "success": True,
        "job_id": job_id,
        "status": "processing",
        "prompt": prompt,
        "style": style,
        "quality": quality,
        "output_format": output_format,
        "message": "Model generation started. Use check_status to monitor progress.",
    }


def generate_model_from_image(
    image_path: str,
    prompt: str | None = None,
    style: str | None = None,
    quality: str = "medium",
    output_format: str = "glb",
) -> dict[str, Any]:
    """Start generating a 3D model from an image.

    Args:
        image_path: Path to the input image
        prompt: Optional text prompt to guide generation
        style: Optional style modifier
        quality: Generation quality (draft, medium, high)
        output_format: Output format (glb, gltf, fbx, obj, usdz)

    Returns:
        Dictionary with job_id, status, and metadata
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return {"success": False, "error": f"Image not found: {image_path}"}

    # Read and encode the image
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return {"success": False, "error": f"Failed to read image: {e}"}

    # Determine MIME type from extension
    ext = image_path.suffix.lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    mime_type = mime_types.get(ext, "image/png")

    if output_format not in SUPPORTED_FORMATS:
        return {
            "success": False,
            "error": f"Unsupported format: {output_format}. Supported: {', '.join(SUPPORTED_FORMATS)}",
        }

    request_data = {
        "image": f"data:{mime_type};base64,{image_data}",
        "quality": quality,
        "output_format": output_format,
    }
    if prompt:
        request_data["prompt"] = prompt.strip()
    if style:
        request_data["style"] = style

    result = _make_request("rodin/image-to-3d", method="POST", data=request_data, timeout=120.0)

    if not result["success"]:
        return result

    data = result["data"]
    job_id = data.get("job_id") or data.get("uuid") or data.get("task_id")

    if not job_id:
        return {
            "success": False,
            "error": "No job ID returned from API",
            "raw_response": data,
        }

    return {
        "success": True,
        "job_id": job_id,
        "status": "processing",
        "source_image": str(image_path),
        "prompt": prompt,
        "style": style,
        "quality": quality,
        "output_format": output_format,
        "message": "Image-to-3D generation started. Use check_status to monitor progress.",
    }


def check_status(job_id: str, auto_import: bool = True) -> dict[str, Any]:
    """Check the status of an AI model generation job.

    Args:
        job_id: The job ID from generate_model or generate_model_from_image
        auto_import: If True, automatically import completed models into Blender

    Returns:
        Dictionary with status, progress, and import info if completed
    """
    if not job_id:
        return {"success": False, "error": "Job ID is required"}

    # Check if already cached
    if is_cached("rodin", job_id):
        cached_path = get_cached_path("rodin", job_id)
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

    result = _make_request(f"rodin/status/{job_id}")

    if not result["success"]:
        return result

    data = result["data"]
    status = data.get("status", "unknown").lower()

    response = {
        "success": True,
        "job_id": job_id,
        "status": status,
    }

    # Add progress information if available
    if "progress" in data:
        response["progress"] = data["progress"]
    if "eta" in data:
        response["eta_seconds"] = data["eta"]
    if "message" in data:
        response["message"] = data["message"]

    # Handle completed jobs
    if status == "completed":
        download_url = (
            data.get("download_url")
            or data.get("model_url")
            or data.get("result", {}).get("url")
        )

        if download_url and auto_import:
            import_result = download_and_import(job_id, download_url)
            response["imported"] = import_result
        elif download_url:
            response["download_url"] = download_url
        else:
            response["warning"] = "No download URL in response"

    # Handle failed jobs
    elif status in ("failed", "error"):
        response["success"] = False
        response["error"] = data.get("error") or data.get("message") or "Generation failed"

    return response


def download_and_import(
    job_id: str,
    download_url: str,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Download and import an AI-generated model.

    Args:
        job_id: Job ID for caching
        download_url: URL to download the model from
        use_cache: Whether to cache the downloaded file

    Returns:
        Dictionary with import results
    """
    try:
        # Determine format from URL
        url_lower = download_url.lower()
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
        temp_path = Path(temp_dir) / f"rodin_{job_id}{ext}"

        # Download with progress tracking
        urllib.request.urlretrieve(download_url, str(temp_path))

        if not temp_path.exists() or temp_path.stat().st_size == 0:
            return {"success": False, "error": "Download failed - empty file"}

        # Cache the file
        if use_cache:
            cached_path = cache_asset(
                source="rodin",
                asset_id=job_id,
                file_path=temp_path,
                metadata={
                    "download_url": download_url,
                    "format": ext[1:],  # Remove leading dot
                },
            )
            import_path = cached_path
        else:
            import_path = temp_path

        # Import into Blender
        return _import_model_file(import_path, job_id)

    except Exception as e:
        return {"success": False, "error": f"Download/import failed: {e}"}


def _import_model_file(filepath: Path, job_id: str) -> dict[str, Any]:
    """Import a model file into Blender.

    Args:
        filepath: Path to the model file
        job_id: Job ID for naming

    Returns:
        Dictionary with import results
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
            # USD import requires specific Blender version
            if hasattr(bpy.ops.wm, "usd_import"):
                bpy.ops.wm.usd_import(filepath=str(filepath))
            else:
                return {"success": False, "error": "USD import not available in this Blender version"}
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
) -> dict[str, Any]:
    """Poll a job until it completes or times out.

    Args:
        job_id: The job ID to poll
        max_wait: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds
        auto_import: Whether to auto-import when complete

    Returns:
        Final status dictionary
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

        result = check_status(job_id, auto_import=auto_import)

        status = result.get("status", "unknown")
        if status in ("completed", "failed", "error"):
            result["elapsed_seconds"] = elapsed
            return result

        # Wait before next poll
        time.sleep(poll_interval)


def list_styles() -> dict[str, Any]:
    """List available generation styles.

    Returns:
        Dictionary with available styles
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
        Dictionary with supported formats
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
