## Summary

Brief description of what this PR does.

## Changes

-

## Tool Changes

- [ ] New tools added (update tool count in test_server.py)
- [ ] Existing tools modified
- [ ] Handler registrations added in `addon/blender_mcp_addon/handlers/`
- [ ] Handler implementations added

## Testing

- [ ] `pytest tests/ --ignore=tests/blender_integration_test.py` passes
- [ ] Truth harness baselines updated if any tool result class changed (see CONTRIBUTING.md)
- [ ] `ruff check .` passes
- [ ] Tested with Blender (version: )
- [ ] Tested via MCP client (client: )

## Checklist

- [ ] Tool definitions use `"type": "number"` (not `"integer"`) for numeric params
- [ ] Handler returns `{"success": True, ...}` or `{"error": "..."}`
- [ ] README updated if new tools added
- [ ] CHANGELOG updated

- [ ] I have read and agree to [CLA.md](../CLA.md) for this contribution.