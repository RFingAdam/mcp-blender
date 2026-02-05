"""Asset caching system for downloaded external assets."""

import hashlib
import json
import shutil
import time
from pathlib import Path

import bpy


def get_cache_dir() -> Path:
    """
    Get the cache directory for downloaded assets.

    Uses Blender's user data path to ensure persistence across sessions.
    """
    # Use Blender's scripts directory for addon data
    user_path = Path(bpy.utils.resource_path("USER"))
    cache_dir = user_path / "mcp_blender_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_polyhaven_cache_dir() -> Path:
    """Get cache directory for Poly Haven assets."""
    cache_dir = get_cache_dir() / "polyhaven"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_ai_models_cache_dir() -> Path:
    """Get cache directory for AI-generated models."""
    cache_dir = get_cache_dir() / "ai_models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_cache_index_path() -> Path:
    """Get path to the cache index file."""
    return get_cache_dir() / "cache_index.json"


def load_cache_index() -> dict:
    """Load the cache index from disk."""
    index_path = get_cache_index_path()
    if index_path.exists():
        try:
            with open(index_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"assets": {}, "version": 1}
    return {"assets": {}, "version": 1}


def save_cache_index(index: dict) -> None:
    """Save the cache index to disk."""
    index_path = get_cache_index_path()
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


def get_cache_key(source: str, asset_id: str, variant: str = "") -> str:
    """
    Generate a cache key for an asset.

    Args:
        source: Asset source (e.g., "polyhaven", "rodin")
        asset_id: Unique asset identifier
        variant: Optional variant (e.g., resolution "2k")

    Returns:
        Cache key string
    """
    key_string = f"{source}:{asset_id}:{variant}"
    return hashlib.md5(key_string.encode()).hexdigest()[:16]


def is_cached(source: str, asset_id: str, variant: str = "") -> bool:
    """
    Check if an asset is already cached.

    Args:
        source: Asset source
        asset_id: Asset identifier
        variant: Optional variant

    Returns:
        True if asset is cached and valid
    """
    cache_key = get_cache_key(source, asset_id, variant)
    index = load_cache_index()

    if cache_key not in index["assets"]:
        return False

    asset_info = index["assets"][cache_key]
    cache_path = Path(asset_info.get("path", ""))

    # Check if file still exists
    if not cache_path.exists():
        # Remove stale entry
        del index["assets"][cache_key]
        save_cache_index(index)
        return False

    return True


def get_cached_path(source: str, asset_id: str, variant: str = "") -> Path | None:
    """
    Get the path to a cached asset.

    Args:
        source: Asset source
        asset_id: Asset identifier
        variant: Optional variant

    Returns:
        Path to cached asset or None if not cached
    """
    cache_key = get_cache_key(source, asset_id, variant)
    index = load_cache_index()

    if cache_key not in index["assets"]:
        return None

    asset_info = index["assets"][cache_key]
    cache_path = Path(asset_info.get("path", ""))

    if cache_path.exists():
        # Update last accessed time
        asset_info["last_accessed"] = time.time()
        save_cache_index(index)
        return cache_path

    return None


def cache_asset(
    source: str,
    asset_id: str,
    file_path: str | Path,
    variant: str = "",
    metadata: dict | None = None,
) -> Path:
    """
    Add an asset to the cache.

    Args:
        source: Asset source
        asset_id: Asset identifier
        file_path: Path to the file to cache
        variant: Optional variant
        metadata: Optional metadata to store

    Returns:
        Path to the cached file
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    cache_key = get_cache_key(source, asset_id, variant)

    # Determine cache subdirectory
    if source == "polyhaven":
        cache_subdir = get_polyhaven_cache_dir()
    elif source == "rodin":
        cache_subdir = get_ai_models_cache_dir()
    else:
        cache_subdir = get_cache_dir() / source
        cache_subdir.mkdir(parents=True, exist_ok=True)

    # Create cached file path
    suffix = file_path.suffix
    cached_path = cache_subdir / f"{cache_key}{suffix}"

    # Copy file to cache
    shutil.copy2(file_path, cached_path)

    # Update index
    index = load_cache_index()
    index["assets"][cache_key] = {
        "source": source,
        "asset_id": asset_id,
        "variant": variant,
        "path": str(cached_path),
        "original_name": file_path.name,
        "cached_at": time.time(),
        "last_accessed": time.time(),
        "size": cached_path.stat().st_size,
        "metadata": metadata or {},
    }
    save_cache_index(index)

    return cached_path


def cache_directory(
    source: str,
    asset_id: str,
    dir_path: str | Path,
    variant: str = "",
    metadata: dict | None = None,
) -> Path:
    """
    Cache an entire directory of asset files.

    Args:
        source: Asset source
        asset_id: Asset identifier
        dir_path: Path to directory to cache
        variant: Optional variant
        metadata: Optional metadata

    Returns:
        Path to cached directory
    """
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {dir_path}")

    cache_key = get_cache_key(source, asset_id, variant)

    # Determine cache subdirectory
    if source == "polyhaven":
        cache_subdir = get_polyhaven_cache_dir()
    else:
        cache_subdir = get_cache_dir() / source
        cache_subdir.mkdir(parents=True, exist_ok=True)

    cached_dir = cache_subdir / cache_key

    # Copy directory
    if cached_dir.exists():
        shutil.rmtree(cached_dir)
    shutil.copytree(dir_path, cached_dir)

    # Update index
    index = load_cache_index()
    total_size = sum(f.stat().st_size for f in cached_dir.rglob("*") if f.is_file())
    index["assets"][cache_key] = {
        "source": source,
        "asset_id": asset_id,
        "variant": variant,
        "path": str(cached_dir),
        "is_directory": True,
        "cached_at": time.time(),
        "last_accessed": time.time(),
        "size": total_size,
        "metadata": metadata or {},
    }
    save_cache_index(index)

    return cached_dir


def list_cached_assets(source: str | None = None) -> list[dict]:
    """
    List all cached assets.

    Args:
        source: Optional filter by source

    Returns:
        List of asset info dictionaries
    """
    index = load_cache_index()
    assets = []

    for cache_key, info in index["assets"].items():
        if source is None or info.get("source") == source:
            assets.append({
                "cache_key": cache_key,
                **info,
            })

    return assets


def get_cache_stats() -> dict:
    """Get cache statistics."""
    index = load_cache_index()

    total_size = 0
    by_source = {}

    for info in index["assets"].values():
        size = info.get("size", 0)
        total_size += size
        source = info.get("source", "unknown")
        if source not in by_source:
            by_source[source] = {"count": 0, "size": 0}
        by_source[source]["count"] += 1
        by_source[source]["size"] += size

    return {
        "total_assets": len(index["assets"]),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "by_source": by_source,
        "cache_dir": str(get_cache_dir()),
    }


def clear_cache(source: str | None = None, max_age_days: int | None = None) -> int:
    """
    Clear cached assets.

    Args:
        source: Optional - only clear assets from this source
        max_age_days: Optional - only clear assets older than this

    Returns:
        Number of assets cleared
    """
    index = load_cache_index()
    cleared = 0
    now = time.time()
    max_age_seconds = max_age_days * 86400 if max_age_days else None

    keys_to_remove = []

    for cache_key, info in index["assets"].items():
        should_remove = False

        # Filter by source
        if source and info.get("source") != source:
            continue

        # Filter by age
        if max_age_seconds:
            cached_at = info.get("cached_at", 0)
            if now - cached_at > max_age_seconds:
                should_remove = True
        else:
            should_remove = True

        if should_remove:
            # Delete file/directory
            path = Path(info.get("path", ""))
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            keys_to_remove.append(cache_key)
            cleared += 1

    # Update index
    for key in keys_to_remove:
        del index["assets"][key]
    save_cache_index(index)

    return cleared
