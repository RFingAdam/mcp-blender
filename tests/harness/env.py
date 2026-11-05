"""The environment every harness-launched Blender runs in."""

from __future__ import annotations

import os
from pathlib import Path

# Blender reads these to find the user's config, scripts and data. A developer's own
# settings would leak into a run through any of them, so they are dropped, and
# BLENDER_USER_RESOURCES points the whole user tree at the run instead.
_USER_DIRS = (
    "BLENDER_USER_RESOURCES",
    "BLENDER_USER_CONFIG",
    "BLENDER_USER_SCRIPTS",
    "BLENDER_USER_DATAFILES",
    "BLENDER_USER_EXTENSIONS",
)


def blender_env(tmp_dir: Path) -> dict[str, str]:
    """Environment for Blender, with its user files kept under ``tmp_dir``.

    ``--factory-startup`` leaves ``bpy.utils.resource_path("USER")`` alone, and the AI job
    history lives there, so without this a run reads and clears the developer's real history.
    """
    tmp_dir = Path(tmp_dir)
    user = tmp_dir / "user"
    user.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in _USER_DIRS}
    env.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(tmp_dir), BLENDER_USER_RESOURCES=str(user))
    return env
