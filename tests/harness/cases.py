"""Generate harness cases from tool input schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fixtures import FIXTURES, OVERRIDES

_TYPE_DEFAULTS = {
    "string": "x",
    "number": 1,
    "integer": 1,
    "boolean": True,
    "object": {},
}


@dataclass
class Case:
    id: str
    tool: str
    pass_name: str
    params: dict = field(default_factory=dict)


def _value_for(param: str, spec: dict) -> Any:
    if param in FIXTURES:
        return FIXTURES[param]
    if "default" in spec:
        return spec["default"]
    if spec.get("enum"):
        return spec["enum"][0]
    if spec.get("type") == "array":
        return [0] * spec.get("minItems", 0)
    return _TYPE_DEFAULTS.get(spec.get("type"), "x")


def minimal_args(tool: str, schema: dict) -> dict:
    if tool in OVERRIDES:
        return dict(OVERRIDES[tool])
    props = schema.get("properties", {})
    return {p: _value_for(p, props.get(p, {})) for p in schema.get("required", [])}


def build_cases(tools: dict[str, dict]) -> list[Case]:
    cases: list[Case] = []
    for tool in sorted(tools):
        schema = tools[tool]
        base = minimal_args(tool, schema)
        cases.append(Case(f"{tool}#minimal", tool, "minimal", base))
        if schema.get("required"):
            cases.append(Case(f"{tool}#invalid", tool, "invalid", {}))
        for param, spec in schema.get("properties", {}).items():
            for value in spec.get("enum", []):
                cases.append(
                    Case(
                        f"{tool}#enum:{param}={value}",
                        tool,
                        "enum",
                        {**base, param: value},
                    )
                )
    return cases
