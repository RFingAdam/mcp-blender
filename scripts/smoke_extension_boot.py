"""Runs inside Blender for scripts/smoke_extension.py: enable the installed extension, start its server.

Run as: blender --python smoke_extension_boot.py
The extension must already be installed into the repository named by MESHWIRE_SMOKE_MODULE.
"""

import os
import sys
import traceback


def main() -> None:
    import addon_utils
    import bpy

    module = os.environ["MESHWIRE_SMOKE_MODULE"]
    addon_utils.enable(module, default_set=True)
    if module not in bpy.context.preferences.addons:
        raise RuntimeError(f"{module} is not enabled after install")
    package = sys.modules[module]
    # The extension's own module, not a source tree on sys.path.
    print(f"SMOKE_MODULE {module} {package.__file__}", flush=True)
    result = bpy.ops.mcp.start_server()
    if result != {"FINISHED"}:
        raise RuntimeError(f"start_server returned {result}")
    print(f"SMOKE_READY {package.get_server().port}", flush=True)


try:
    main()
except BaseException:
    traceback.print_exc()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(3)
