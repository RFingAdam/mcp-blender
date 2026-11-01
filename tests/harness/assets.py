"""Write the input files that ``{TMP}/...`` fixtures name. Stdlib only."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

SIZE = 16


def _png(path: Path, rgb: tuple[int, int, int]) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * SIZE
    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * SIZE))
        + chunk(b"IEND", b"")
    )


def _glb(path: Path) -> None:
    """A one-triangle binary glTF."""
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "Tri"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteLength": len(positions)}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0, 0, 0],
                "max": [1, 1, 0],
            }
        ],
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(positions)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(js), b"JSON")
        + js
        + struct.pack("<I4s", len(positions), b"BIN\x00")
        + positions
    )


OBJ = "o Tri\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
STL = (
    "solid tri\nfacet normal 0 0 1\nouter loop\n"
    "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid tri\n"
)
PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\n"
    "property float z\nelement face 1\nproperty list uchar int vertex_indices\n"
    "end_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n"
)
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<path d="M0 0 L10 0 L10 10 Z"/></svg>'
)


def prepare(tmp: Path) -> None:
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    _png(tmp / "in.png", (200, 80, 40))
    _png(tmp / "mask.png", (255, 255, 255))
    _png(tmp / "render.png", (90, 90, 90))
    _glb(tmp / "in.glb")
    (tmp / "in.obj").write_text(OBJ)
    (tmp / "in.stl").write_text(STL)
    (tmp / "in.ply").write_text(PLY)
    (tmp / "in.svg").write_text(SVG)
