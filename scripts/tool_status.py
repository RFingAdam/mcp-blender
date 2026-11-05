"""Write the tool status sections of README.md from the harness baselines.

    python scripts/tool_status.py           rewrite README.md
    python scripts/tool_status.py --check   exit 1 if README.md is out of date

A tool passes on a Blender series when every harness case for it is PASS or
EXPECTED and at least one valid call passed: it ran on valid input and
rejected bad input. A tool whose valid calls all stopped at the disabled
network never ran, so it is listed as unchecked. Passing does not prove its
output is right. The socket lane checks output for some tools, and its
known failures are listed too.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness.fixtures import (  # noqa: E402
    FALSE_PASS_DEFECTS,
    KNOWN_UNREACHED,
    SOFT_FAIL_ALLOWED,
    SOFT_FAIL_DEFECTS,
)

README = ROOT / "README.md"
HANDLERS = ROOT / "addon" / "blender_mcp_addon" / "handlers"
BASELINES = ROOT / "tests" / "harness" / "baselines"
SERIES = ("4.5", "5.2")
BROKEN = {"BUG", "CRASH", "HANG"}
ISSUES = "https://github.com/RFingAdam/meshwire/issues"

# Tool-name prefixes that split a handler module into two areas.
PREFIX_AREAS = {"msfs_livery_": "msfs_livery", "polyhaven_": "polyhaven"}

# Handler module stem: (area, example tools). Order is the table order.
AREAS = {
    "scene": ("Scene", ["scene_info", "scene_new"]),
    "objects": ("Objects", ["object_create", "object_duplicate"]),
    "mesh_editing": ("Mesh, curves, booleans", ["mesh_bevel", "curve_create"]),
    "materials": ("Materials and nodes", ["material_create", "material_inspect_graph"]),
    "modifiers": ("Modifiers", ["modifier_add", "modifier_apply"]),
    "animation": ("Animation", ["keyframe_delete", "action_create"]),
    "render": ("Render", ["render_image", "render_multi_angle"]),
    "export_import": ("Import and export", ["export_fbx", "export_usd"]),
    "measurement": ("Measurement and validation", ["measure_volume", "measure_clearance"]),
    "baking": ("Baking", ["bake_pbr_batch", "bake_from_multires"]),
    "geonodes": ("Geometry nodes", ["geonode_array_grid", "geonode_extrude_profile"]),
    "sculpt": ("Sculpting", ["sculpt_setup", "sculpt_remesh_voxel", "sculpt_mesh_filter"]),
    "armature": ("Rigging", ["armature_create", "autorig_preset"]),
    "physics": ("Physics", ["physics_rigid_body_add", "physics_cloth_add"]),
    "collections": ("Collections and session", ["collection_create", "save_as"]),
    "annotations": ("Annotations", ["annotation_dimension", "annotation_text"]),
    "msfs": ("MSFS content", ["msfs_create_lod_hierarchy", "msfs_setup_material"]),
    "msfs_livery": ("MSFS livery", ["msfs_livery_transfer", "msfs_livery_create_package"]),
    "ai": ("AI generation and refinement", ["ai_mesh_remesh", "ai_auto_uv"]),
    "polyhaven": ("Poly Haven", ["polyhaven_search", "polyhaven_download"]),
}


def tool_areas() -> dict[str, str]:
    """Area for each tool, from the handler module that defines it."""
    areas = {}
    for path in sorted(HANDLERS.glob("*.py")):
        for tool in re.findall(r"def _handle_(\w+)\(", path.read_text(encoding="utf-8")):
            key = next((k for p, k in PREFIX_AREAS.items() if tool.startswith(p)), path.stem)
            if key not in AREAS:
                raise SystemExit(f"{path.name} has no entry in AREAS")
            areas[tool] = key
    return areas


def tool_states(results: dict[str, str]) -> dict[str, str]:
    """State of each tool on one Blender series.

    pass: every case passed. loose: works, but a call with no arguments was not
    rejected cleanly. unchecked: needs what headless Blender lacks. offline:
    every valid call stopped at the network, which the harness disables, so the
    tool never ran. fail: the rest.
    """
    classes, valid, loose = defaultdict(set), defaultdict(set), set()
    for case, result in results.items():
        tool, _, kind = case.partition("#")
        if kind == "invalid" and result in BROKEN:
            loose.add(tool)
        else:
            classes[tool].add(result)
        if kind != "invalid":
            valid[tool].add(result)
    states = {}
    for tool, seen in classes.items():
        if (
            seen & BROKEN
            or tool in FALSE_PASS_DEFECTS
            or ("SOFT_FAIL" in seen and tool in SOFT_FAIL_DEFECTS)
        ):
            states[tool] = "fail"
        elif "SOFT_FAIL" in seen:
            states[tool] = "unchecked"
        elif valid[tool] == {"EXPECTED"}:
            states[tool] = "offline"
        else:
            states[tool] = "loose" if tool in loose else "pass"
    return states


def works(state: str) -> bool:
    return state in ("pass", "loose")


def load() -> tuple[dict[str, dict[str, str]], list[str]]:
    states = {}
    for series in SERIES:
        results = json.loads((BASELINES / f"blender-{series}.json").read_text(encoding="utf-8"))
        states[series] = tool_states(results)
    lane = json.loads((BASELINES / "socket-lane.json").read_text(encoding="utf-8"))
    lane_fails = sorted({c for s in SERIES for c, r in lane.get(s, {}).items() if r == "FAIL"})
    return states, lane_fails


def groups(states: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    """Sort tools into the README's lists by their state across SERIES."""
    out = {"works": [], "loose": [], "fail": [], "unchecked": []}
    for tool in sorted(states[SERIES[0]]):
        seen = [states[s][tool] for s in SERIES]
        if "fail" in seen:
            out["fail"].append(tool)
        elif all(map(works, seen)):
            out["works"].append(tool)
            if "loose" in seen:
                out["loose"].append(tool)
        else:
            out["unchecked"].append(tool)
    return out


def status_section(states: dict[str, dict[str, str]]) -> str:
    g = groups(states)
    counted = [
        (
            "loose",
            "of those still accept a call that leaves out a required argument "
            "instead of returning an error.",
        ),
        (
            "unchecked",
            "need what a headless test cannot provide, such as a GUI, "
            "network access, or an earlier call.",
        ),
        ("fail", "have a known failure."),
    ]
    lines = [
        f"**Status:** every pull request runs each tool in real Blender {SERIES[0]} LTS and "
        f"{SERIES[1]} LTS.",
        f"**{len(g['works'])} of {len(states[SERIES[0]])} tools work on both.**",
        *(f"{len(g[k])} {text}" for k, text in counted if g[k]),
        f"Each list is under [Tools](#tools), and fixes are tracked in the [issues]({ISSUES}).",
    ]
    return "\n".join(f"> {line}" for line in lines)


def tools_section(states: dict[str, dict[str, str]], lane_fails: list[str]) -> str:
    areas = tool_areas()
    tools = sorted(states[SERIES[0]])
    if missing := sorted(set(tools) - set(areas)):
        raise SystemExit(f"no handler found for: {', '.join(missing)}")
    g = groups(states)

    head = ["Area", "Tools", *(f"Work on {s}" for s in SERIES), "Examples"]
    rows = []
    for key, (area, candidates) in AREAS.items():
        if wrong := [c for c in candidates if areas.get(c) != key]:
            raise SystemExit(f"examples not in {key}: {', '.join(wrong)}")
        members = [t for t in tools if areas[t] == key]
        counts = [str(sum(works(states[s][t]) for t in members)) for s in SERIES]
        shown = [f"`{c}`" for c in candidates if c in g["works"]][:2]
        rows.append([area, str(len(members)), *counts, ", ".join(shown)])
    totals = [str(sum(map(works, states[s].values()))) for s in SERIES]
    rows.append(["**Total**", f"**{len(tools)}**", *(f"**{t}**" for t in totals), ""])

    why = {**SOFT_FAIL_ALLOWED, **KNOWN_UNREACHED}
    for t in g["unchecked"]:
        if t not in why and any(states[s][t] == "offline" for s in SERIES):
            why[t] = "needs network access, which the harness turns off"
    fail_rows = [
        [f"`{t}`", ", ".join(s for s in SERIES if states[s][t] == "fail")] for t in g["fail"]
    ]
    lines = [_table(head, rows, numeric=range(1, 2 + len(SERIES))), ""]
    lines += _details(
        f"{len(g['fail'])} tools with a known failure", _table(["Tool", "Fails on"], fail_rows)
    )
    if lane_fails:
        named = ", ".join(f"`{c}`" for c in lane_fails)
        lines[-2:-2] = [f"Socket checks that still fail: {named}.", ""]
    if g["loose"]:
        lines += _details(
            f"{len(g['loose'])} tools that accept a call with a required argument missing",
            ", ".join(f"`{t}`" for t in g["loose"]),
        )
    if g["unchecked"]:
        lines += _details(
            f"{len(g['unchecked'])} tools that cannot be checked headless",
            _table(["Tool", "Why"], [[f"`{t}`", why.get(t, "")] for t in g["unchecked"]]),
        )
    return "\n".join(lines[:-1])


def _details(summary: str, body: str) -> list[str]:
    return [f"<details><summary>{summary}</summary>", "", body, "", "</details>", ""]


def _table(head: list[str], rows: list[list[str]], numeric=()) -> str:
    rule = ["---:" if i in numeric else "---" for i in range(len(head))]
    return "\n".join("| " + " | ".join(r) + " |" for r in [head, rule, *rows])


def render(text: str) -> str:
    states, lane_fails = load()
    for name, body in (
        ("status", status_section(states)),
        ("tools", tools_section(states, lane_fails)),
    ):
        start, end = f"<!-- generated:{name} -->\n", f"<!-- /generated:{name} -->"
        pattern = re.compile(re.escape(start) + ".*?" + re.escape(end), re.DOTALL)
        if not pattern.search(text):
            raise SystemExit(f"README.md has no generated:{name} markers")
        text = pattern.sub(lambda _: f"{start}{body}\n{end}", text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if README.md is out of date")
    args = parser.parse_args()
    text = README.read_text(encoding="utf-8")
    new = render(text)
    if args.check:
        if new != text:
            print("README.md is out of date: run python scripts/tool_status.py", file=sys.stderr)
            return 1
        return 0
    README.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
