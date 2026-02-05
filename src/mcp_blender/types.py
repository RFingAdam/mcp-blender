"""Shared types for MCP Blender server."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class BlenderPrimitive(str, Enum):
    """Supported primitive types for object creation."""

    CUBE = "cube"
    SPHERE = "sphere"
    CYLINDER = "cylinder"
    PLANE = "plane"
    CONE = "cone"
    TORUS = "torus"
    MONKEY = "monkey"
    CIRCLE = "circle"
    GRID = "grid"
    EMPTY = "empty"
    CAMERA = "camera"
    LIGHT = "light"


class RenderEngine(str, Enum):
    """Supported render engines."""

    CYCLES = "CYCLES"
    EEVEE = "BLENDER_EEVEE_NEXT"
    WORKBENCH = "BLENDER_WORKBENCH"


class ModifierType(str, Enum):
    """Common modifier types."""

    SUBDIVISION = "SUBSURF"
    BEVEL = "BEVEL"
    SOLIDIFY = "SOLIDIFY"
    ARRAY = "ARRAY"
    MIRROR = "MIRROR"
    BOOLEAN = "BOOLEAN"
    DECIMATE = "DECIMATE"
    SMOOTH = "SMOOTH"
    WEIGHTED_NORMAL = "WEIGHTED_NORMAL"
    TRIANGULATE = "TRIANGULATE"


class ExportFormat(str, Enum):
    """Supported export formats."""

    GLTF = "gltf"
    GLB = "glb"
    FBX = "fbx"
    OBJ = "obj"
    STL = "stl"


@dataclass
class Vector3:
    """3D vector."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @classmethod
    def from_tuple(cls, t: tuple[float, float, float]) -> "Vector3":
        return cls(x=t[0], y=t[1], z=t[2])


@dataclass
class RGBA:
    """RGBA color."""

    r: float = 1.0
    g: float = 1.0
    b: float = 1.0
    a: float = 1.0

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.r, self.g, self.b, self.a)


@dataclass
class BlenderCommand:
    """Command to send to Blender addon."""

    method: str
    params: dict[str, Any]
    id: str | None = None


@dataclass
class BlenderResponse:
    """Response from Blender addon."""

    result: Any | None = None
    error: dict[str, Any] | None = None
    id: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None
