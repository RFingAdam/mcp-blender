"""The wire constants live in two files that must never drift apart."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON_WIRE = ROOT / "addon" / "blender_mcp_addon" / "wire.py"
SERVER_WIRE = ROOT / "src" / "mcp_blender" / "wire.py"


def test_wire_copies_are_identical():
    assert ADDON_WIRE.read_bytes() == SERVER_WIRE.read_bytes()


def test_wire_imports_nothing():
    # It is loaded by the add-on inside Blender and by the server outside it.
    for line in ADDON_WIRE.read_text().splitlines():
        assert not line.startswith(("import ", "from "))


def test_error_codes():
    namespace: dict = {}
    exec(compile(ADDON_WIRE.read_text(), str(ADDON_WIRE), "exec"), namespace)
    assert namespace["E_PARSE"] == -32700
    assert namespace["E_TOO_MANY"] == -32003
    assert namespace["E_TOO_LARGE"] == -32004
    assert namespace["E_REPLY_TOO_LARGE"] == -32005
