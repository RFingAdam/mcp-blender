"""Tests for ComfyUI workflow template loading and parameter substitution."""

import json
from pathlib import Path

import pytest

WORKFLOWS_DIR = Path(__file__).parent.parent / "addon" / "blender_mcp_addon" / "external" / "ai_backends" / "workflows"

EXPECTED_TEMPLATES = [
    "pbr_texture",
    "reference_image",
    "inpaint",
    "controlnet_texture",
    "stable_fast_3d",
]


class TestWorkflowTemplatesExist:
    """Test that all expected workflow templates are present."""

    @pytest.mark.parametrize("template_name", EXPECTED_TEMPLATES)
    def test_template_file_exists(self, template_name):
        path = WORKFLOWS_DIR / f"{template_name}.json"
        assert path.exists(), f"Workflow template missing: {path}"


class TestWorkflowTemplatesValid:
    """Test that workflow templates are valid JSON with correct structure."""

    @pytest.mark.parametrize("template_name", EXPECTED_TEMPLATES)
    def test_template_is_valid_json(self, template_name):
        path = WORKFLOWS_DIR / f"{template_name}.json"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    @pytest.mark.parametrize("template_name", EXPECTED_TEMPLATES)
    def test_template_has_parameters(self, template_name):
        """Each template should have a _parameters metadata key."""
        path = WORKFLOWS_DIR / f"{template_name}.json"
        with open(path) as f:
            data = json.load(f)
        assert "_parameters" in data, f"Template {template_name} missing _parameters"
        assert isinstance(data["_parameters"], dict)

    @pytest.mark.parametrize("template_name", EXPECTED_TEMPLATES)
    def test_template_parameter_paths_reference_valid_nodes(self, template_name):
        """Parameter paths should reference node IDs that exist in the template."""
        path = WORKFLOWS_DIR / f"{template_name}.json"
        with open(path) as f:
            data = json.load(f)

        params = data["_parameters"]
        nodes = {k: v for k, v in data.items() if k != "_parameters"}

        for param_name, param_path in params.items():
            node_id, _, input_name = param_path.partition(".")
            assert node_id in nodes, (
                f"Template {template_name}: param '{param_name}' references "
                f"non-existent node '{node_id}'"
            )
            node = nodes[node_id]
            assert "inputs" in node, (
                f"Template {template_name}: node '{node_id}' has no 'inputs'"
            )
            assert input_name in node["inputs"], (
                f"Template {template_name}: param '{param_name}' references "
                f"non-existent input '{input_name}' in node '{node_id}'"
            )

    @pytest.mark.parametrize("template_name", EXPECTED_TEMPLATES)
    def test_template_nodes_have_class_type(self, template_name):
        """All non-metadata nodes should have a class_type field."""
        path = WORKFLOWS_DIR / f"{template_name}.json"
        with open(path) as f:
            data = json.load(f)

        for key, value in data.items():
            if key == "_parameters":
                continue
            assert "class_type" in value, (
                f"Template {template_name}: node '{key}' missing class_type"
            )


class TestWorkflowTemplateSubstitution:
    """Test parameter substitution in workflow templates."""

    def test_pbr_texture_prompt_substitution(self):
        path = WORKFLOWS_DIR / "pbr_texture.json"
        with open(path) as f:
            data = json.load(f)

        params = data.pop("_parameters")

        # The prompt param should map to node 3, input text
        assert "prompt" in params
        node_id, _, input_name = params["prompt"].partition(".")
        assert data[node_id]["inputs"][input_name] is not None

        # Simulate substitution
        import copy
        workflow = copy.deepcopy(data)
        test_prompt = "red brick wall, seamless, PBR"
        workflow[node_id]["inputs"][input_name] = test_prompt
        assert workflow[node_id]["inputs"][input_name] == test_prompt

    def test_inpaint_has_image_and_mask_params(self):
        path = WORKFLOWS_DIR / "inpaint.json"
        with open(path) as f:
            data = json.load(f)

        params = data["_parameters"]
        assert "image" in params, "Inpaint template should have 'image' parameter"
        assert "mask" in params or "mask_path" in params or any(
            "mask" in v for v in params.values()
        ), "Inpaint template should reference a mask input"

    def test_controlnet_has_control_image_param(self):
        path = WORKFLOWS_DIR / "controlnet_texture.json"
        with open(path) as f:
            data = json.load(f)

        params = data["_parameters"]
        assert "control_image" in params, "ControlNet template should have 'control_image' parameter"

    def test_stable_fast_3d_has_image_param(self):
        path = WORKFLOWS_DIR / "stable_fast_3d.json"
        with open(path) as f:
            data = json.load(f)

        params = data["_parameters"]
        assert "image" in params, "SF3D template should have 'image' parameter"


class TestPBRTextureOutputNodes:
    """Test that PBR texture template has the expected output structure."""

    def test_has_multiple_save_image_nodes(self):
        """PBR template should have multiple SaveImage nodes for different maps."""
        path = WORKFLOWS_DIR / "pbr_texture.json"
        with open(path) as f:
            data = json.load(f)

        save_nodes = [
            (k, v) for k, v in data.items()
            if k != "_parameters" and v.get("class_type") == "SaveImage"
        ]
        # Should have at least 3 SaveImage nodes (diffuse, roughness, metallic)
        assert len(save_nodes) >= 3, f"Expected >=3 SaveImage nodes, got {len(save_nodes)}"

    def test_save_nodes_have_distinct_prefixes(self):
        """Each SaveImage node should have a unique filename_prefix."""
        path = WORKFLOWS_DIR / "pbr_texture.json"
        with open(path) as f:
            data = json.load(f)

        prefixes = []
        for key, value in data.items():
            if key == "_parameters":
                continue
            if value.get("class_type") == "SaveImage":
                prefix = value["inputs"].get("filename_prefix", "")
                prefixes.append(prefix)

        assert len(prefixes) == len(set(prefixes)), f"Duplicate prefixes found: {prefixes}"
        # Should include key PBR map types
        prefix_set = set(prefixes)
        assert "diffuse" in prefix_set, "Missing 'diffuse' prefix"
        assert "roughness" in prefix_set, "Missing 'roughness' prefix"
