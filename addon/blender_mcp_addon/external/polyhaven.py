"""Poly Haven API integration for HDRIs, textures, and models."""

import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import bpy

from .cache import (
    cache_asset,
    cache_directory,
    get_cached_path,
    is_cached,
)

POLYHAVEN_API_BASE = "https://api.polyhaven.com"
POLYHAVEN_TIMEOUT = 30


class PolyHavenError(Exception):
    """Error from Poly Haven API."""
    pass


def _api_request(endpoint: str, timeout: int = POLYHAVEN_TIMEOUT) -> dict:
    """Make an API request to Poly Haven."""
    url = f"{POLYHAVEN_API_BASE}/{endpoint}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Blender-MCP-Addon/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        raise PolyHavenError(f"API error: {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        raise PolyHavenError(f"Connection error: {e.reason}")
    except json.JSONDecodeError as e:
        raise PolyHavenError(f"Invalid API response: {e}")


def _download_file(url: str, filepath: str, timeout: int = POLYHAVEN_TIMEOUT) -> None:
    """Download a file from URL."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Blender-MCP-Addon/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            with open(filepath, "wb") as f:
                f.write(response.read())
    except urllib.error.HTTPError as e:
        raise PolyHavenError(f"Download error: {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        raise PolyHavenError(f"Connection error: {e.reason}")


def search_polyhaven(
    query: str = "",
    asset_type: str | None = None,
    categories: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Search Poly Haven for assets.

    Args:
        query: Search query string
        asset_type: Filter by type: "hdris", "textures", or "models"
        categories: Filter by categories
        limit: Maximum number of results

    Returns:
        Dictionary with search results
    """
    try:
        # Build API endpoint
        endpoint = "assets"
        if asset_type:
            valid_types = ["hdris", "textures", "models"]
            if asset_type not in valid_types:
                return {
                    "error": f"Invalid asset type: {asset_type}. Must be one of: {valid_types}",
                    "results": [],
                    "count": 0,
                }
            endpoint = f"assets?t={asset_type}"

        data = _api_request(endpoint)

        # Filter and format results
        results = []
        for asset_id, asset_info in data.items():
            # Apply query filter
            if query:
                query_lower = query.lower()
                name_match = query_lower in asset_id.lower()
                name_field_match = query_lower in asset_info.get("name", "").lower()
                tag_match = any(
                    query_lower in tag.lower()
                    for tag in asset_info.get("tags", [])
                )
                if not (name_match or name_field_match or tag_match):
                    continue

            # Apply category filter
            if categories:
                asset_cats = asset_info.get("categories", [])
                if not any(cat.lower() in [c.lower() for c in asset_cats] for cat in categories):
                    continue

            results.append({
                "id": asset_id,
                "name": asset_info.get("name", asset_id),
                "type": asset_info.get("type"),
                "categories": asset_info.get("categories", []),
                "tags": asset_info.get("tags", [])[:10],  # Limit tags
                "download_count": asset_info.get("download_count", 0),
            })

            if len(results) >= limit:
                break

        # Sort by download count (popularity)
        results.sort(key=lambda x: x.get("download_count", 0), reverse=True)

        return {
            "results": results,
            "count": len(results),
            "query": query,
            "asset_type": asset_type,
        }

    except PolyHavenError as e:
        return {"error": str(e), "results": [], "count": 0}
    except Exception as e:
        return {"error": f"Unexpected error: {e}", "results": [], "count": 0}


def get_asset_info(asset_id: str) -> dict[str, Any]:
    """
    Get detailed information about an asset.

    Args:
        asset_id: The Poly Haven asset ID

    Returns:
        Dictionary with asset details
    """
    try:
        info = _api_request(f"info/{asset_id}")
        files = _api_request(f"files/{asset_id}")

        # Get available resolutions
        resolutions = set()
        for category in files.values():
            if isinstance(category, dict):
                resolutions.update(category.keys())

        return {
            "id": asset_id,
            "name": info.get("name", asset_id),
            "type": info.get("type"),
            "authors": info.get("authors", {}),
            "categories": info.get("categories", []),
            "tags": info.get("tags", []),
            "date_published": info.get("date_published"),
            "download_count": info.get("download_count", 0),
            "resolutions": sorted(list(resolutions)),
            "files": list(files.keys()),
        }

    except PolyHavenError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


def download_polyhaven(
    asset_id: str,
    resolution: str = "2k",
    apply_to: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Download and apply a Poly Haven asset.

    Args:
        asset_id: The Poly Haven asset ID
        resolution: Resolution to download (1k, 2k, 4k, 8k)
        apply_to: For textures, the material name to apply to
        use_cache: Whether to use cached version if available

    Returns:
        Dictionary with download result
    """
    try:
        # Check cache first
        if use_cache and is_cached("polyhaven", asset_id, resolution):
            cached_path = get_cached_path("polyhaven", asset_id, resolution)
            if cached_path:
                return _use_cached_asset(asset_id, cached_path, apply_to)

        # Get asset info
        asset_info = _api_request(f"info/{asset_id}")
        asset_type = asset_info.get("type")

        # Get download URLs
        files_info = _api_request(f"files/{asset_id}")

        if asset_type == "hdris":
            return _download_hdri(asset_id, files_info, resolution, use_cache)
        elif asset_type == "textures":
            return _download_texture(asset_id, files_info, resolution, apply_to, use_cache)
        elif asset_type == "models":
            return _download_model(asset_id, files_info, resolution, use_cache)
        else:
            return {"error": f"Unknown asset type: {asset_type}"}

    except PolyHavenError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


def _use_cached_asset(asset_id: str, cached_path: Path, apply_to: str | None) -> dict:
    """Use a cached asset."""
    if cached_path.suffix.lower() in (".hdr", ".exr"):
        # HDRI
        return _apply_cached_hdri(asset_id, cached_path)
    elif cached_path.is_dir():
        # Texture directory
        return _apply_cached_textures(asset_id, cached_path, apply_to)
    elif cached_path.suffix.lower() in (".glb", ".gltf", ".blend"):
        # Model
        return _import_cached_model(asset_id, cached_path)
    else:
        return {"error": f"Unknown cached asset type: {cached_path}"}


def _apply_cached_hdri(asset_id: str, filepath: Path) -> dict:
    """Apply a cached HDRI."""
    image = bpy.data.images.load(str(filepath))
    image.name = asset_id
    _setup_hdri_world(image)
    return {
        "asset_id": asset_id,
        "type": "hdri",
        "filepath": str(filepath),
        "from_cache": True,
    }


def _apply_cached_textures(asset_id: str, dir_path: Path, apply_to: str | None) -> dict:
    """Apply cached textures."""
    texture_files = {}
    for f in dir_path.iterdir():
        if f.is_file():
            # Parse filename to get map type
            name = f.stem
            if "_" in name:
                map_type = name.split("_")[-1]
                texture_files[map_type] = str(f)

    if apply_to:
        mat = bpy.data.materials.get(apply_to)
        if mat:
            _apply_textures_to_material(mat, texture_files)

    return {
        "asset_id": asset_id,
        "type": "texture",
        "files": texture_files,
        "applied_to": apply_to,
        "from_cache": True,
    }


def _import_cached_model(asset_id: str, filepath: Path) -> dict:
    """Import a cached model."""
    ext = filepath.suffix.lower()
    if ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=str(filepath))
    elif ext == ".blend":
        with bpy.data.libraries.load(str(filepath)) as (data_from, data_to):
            data_to.objects = data_from.objects
        for obj in data_to.objects:
            if obj:
                bpy.context.collection.objects.link(obj)

    return {
        "asset_id": asset_id,
        "type": "model",
        "filepath": str(filepath),
        "from_cache": True,
    }


def _download_hdri(
    asset_id: str,
    files_info: dict,
    resolution: str,
    use_cache: bool,
) -> dict:
    """Download and apply an HDRI."""
    # Get HDR file URL
    hdri_files = files_info.get("hdri", {})
    res_files = hdri_files.get(resolution, {})

    if not res_files:
        # Fallback to available resolutions
        available = list(hdri_files.keys())
        if not available:
            return {"error": "No HDRI files available"}
        res_files = hdri_files.get(available[0], {})
        resolution = available[0]

    # Prefer HDR format, then EXR
    hdr_info = res_files.get("hdr") or res_files.get("exr")
    if not hdr_info:
        return {"error": "Could not find HDRI download URL"}

    url = hdr_info.get("url")
    if not url:
        return {"error": "Missing download URL"}

    # Download
    ext = ".hdr" if "hdr" in res_files else ".exr"
    temp_dir = tempfile.mkdtemp()
    filepath = os.path.join(temp_dir, f"{asset_id}{ext}")

    _download_file(url, filepath)

    # Cache the file
    if use_cache:
        cached_path = cache_asset(
            "polyhaven", asset_id, filepath, resolution,
            metadata={"type": "hdri", "resolution": resolution}
        )
        filepath = str(cached_path)

    # Load and apply
    image = bpy.data.images.load(filepath)
    image.name = asset_id
    _setup_hdri_world(image)

    return {
        "asset_id": asset_id,
        "type": "hdri",
        "resolution": resolution,
        "filepath": filepath,
        "from_cache": False,
    }


def _setup_hdri_world(image):
    """Set up world nodes for HDRI."""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world

    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    nodes.clear()

    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    env_tex = nodes.new("ShaderNodeTexEnvironment")
    env_tex.image = image

    output.location = (300, 0)
    background.location = (0, 0)
    env_tex.location = (-300, 0)

    links.new(env_tex.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])


def _download_texture(
    asset_id: str,
    files_info: dict,
    resolution: str,
    apply_to: str | None,
    use_cache: bool,
) -> dict:
    """Download texture maps and optionally apply to a material."""
    temp_dir = tempfile.mkdtemp()
    texture_files = {}

    # Map types to download
    texture_maps = {
        "diffuse": "Base Color",
        "diff": "Base Color",
        "nor_gl": "Normal",
        "nor_dx": "Normal",
        "rough": "Roughness",
        "disp": "Displacement",
        "ao": "AO",
        "arm": "ARM",
        "metal": "Metallic",
    }

    for map_type in texture_maps.keys():
        map_files = files_info.get(map_type, {})
        res_files = map_files.get(resolution, {})

        if not res_files:
            continue

        # Try formats in order of preference
        for fmt in ["jpg", "png", "exr"]:
            if fmt in res_files:
                url = res_files[fmt].get("url")
                if url:
                    filepath = os.path.join(temp_dir, f"{asset_id}_{map_type}.{fmt}")
                    try:
                        _download_file(url, filepath)
                        texture_files[map_type] = filepath
                    except PolyHavenError:
                        pass  # Skip failed downloads
                    break

    if not texture_files:
        return {"error": "No texture files could be downloaded"}

    # Cache the texture directory
    if use_cache:
        cached_dir = cache_directory(
            "polyhaven", asset_id, temp_dir, resolution,
            metadata={"type": "texture", "resolution": resolution, "maps": list(texture_files.keys())}
        )
        # Update file paths to cached locations
        for map_type in texture_files:
            original = Path(texture_files[map_type])
            texture_files[map_type] = str(cached_dir / original.name)

    # Apply to material if specified
    if apply_to:
        mat = bpy.data.materials.get(apply_to)
        if mat:
            _apply_textures_to_material(mat, texture_files)
        else:
            return {
                "error": f"Material not found: {apply_to}",
                "files": texture_files,
            }

    return {
        "asset_id": asset_id,
        "type": "texture",
        "resolution": resolution,
        "files": texture_files,
        "maps_downloaded": list(texture_files.keys()),
        "applied_to": apply_to,
        "from_cache": False,
    }


def _apply_textures_to_material(mat, texture_files: dict):
    """Apply downloaded textures to a material's Principled BSDF."""
    if not mat.use_nodes:
        mat.use_nodes = True

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Find or create Principled BSDF
    principled = None
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            principled = node
            break

    if not principled:
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (0, 0)

    # Create texture coordinate and mapping nodes
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-800, 0)

    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-600, 0)
    links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])

    y_offset = 300

    # Load and connect textures
    for map_type, filepath in texture_files.items():
        image = bpy.data.images.load(filepath)
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = image
        tex_node.location = (-400, y_offset)
        links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

        if map_type in ("diffuse", "diff"):
            links.new(tex_node.outputs["Color"], principled.inputs["Base Color"])
        elif map_type in ("nor_gl", "nor_dx", "normal"):
            normal_map = nodes.new("ShaderNodeNormalMap")
            normal_map.location = (-200, y_offset)
            links.new(tex_node.outputs["Color"], normal_map.inputs["Color"])
            links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
            tex_node.image.colorspace_settings.name = "Non-Color"
        elif map_type == "rough":
            links.new(tex_node.outputs["Color"], principled.inputs["Roughness"])
            tex_node.image.colorspace_settings.name = "Non-Color"
        elif map_type == "metal":
            links.new(tex_node.outputs["Color"], principled.inputs["Metallic"])
            tex_node.image.colorspace_settings.name = "Non-Color"
        elif map_type == "ao":
            # AO can be mixed with diffuse or used separately
            pass
        elif map_type == "disp":
            # Displacement needs special handling
            tex_node.image.colorspace_settings.name = "Non-Color"

        y_offset -= 300


def _download_model(
    asset_id: str,
    files_info: dict,
    resolution: str,
    use_cache: bool,
) -> dict:
    """Download and import a 3D model."""
    # Prefer glTF, then blend
    gltf_files = files_info.get("gltf", {})
    blend_files = files_info.get("blend", {})

    res_files = gltf_files.get(resolution) or blend_files.get(resolution)

    if not res_files:
        # Try any available resolution
        all_res = list(gltf_files.keys()) + list(blend_files.keys())
        if not all_res:
            return {"error": "No model files available"}

        res = all_res[0]
        res_files = gltf_files.get(res) or blend_files.get(res)
        resolution = res

    # Get download URL
    url = None
    ext = None
    for fmt, fmt_info in res_files.items():
        if isinstance(fmt_info, dict) and "url" in fmt_info:
            url = fmt_info["url"]
            ext = f".{fmt}"
            break

    if not url:
        return {"error": "Could not find model download URL"}

    temp_dir = tempfile.mkdtemp()
    filepath = os.path.join(temp_dir, f"{asset_id}{ext}")

    _download_file(url, filepath)

    # Cache the file
    if use_cache:
        cached_path = cache_asset(
            "polyhaven", asset_id, filepath, resolution,
            metadata={"type": "model", "resolution": resolution}
        )
        filepath = str(cached_path)

    # Import the model
    objects_before = set(obj.name for obj in bpy.data.objects)

    if ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif ext == ".blend":
        with bpy.data.libraries.load(filepath) as (data_from, data_to):
            data_to.objects = data_from.objects
        for obj in data_to.objects:
            if obj:
                bpy.context.collection.objects.link(obj)

    objects_after = set(obj.name for obj in bpy.data.objects)
    imported_objects = list(objects_after - objects_before)

    return {
        "asset_id": asset_id,
        "type": "model",
        "resolution": resolution,
        "filepath": filepath,
        "imported_objects": imported_objects,
        "from_cache": False,
    }
