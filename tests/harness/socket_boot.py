"""Start the addon socket server inside a GUI Blender. Imports only stdlib, bpy and the addon.

Run as: blender --factory-startup --python socket_boot.py -- --port N --scene FILE
Or, in background mode, build the fixture scene: --build-scene FILE

Two harness-only handlers are added to the live server so the lane can set up and
inspect scene state without leaning on the tools it is checking:

  harness_reset  reload the fixture scene
  harness_exec   run a snippet and return its ``result`` variable
"""

import argparse
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "addon"))


def _install_harness_handlers(server, scene_path):
    import bpy

    def reset(params):
        bpy.ops.wm.open_mainfile(filepath=scene_path, load_ui=False)
        return {"reset": True, "object_count": len(bpy.context.scene.objects)}

    def run(params):
        namespace = {"bpy": bpy, "result": None}
        exec(params["code"], namespace)  # noqa: S102
        return namespace["result"]

    server.handlers._handlers["harness_reset"] = reset
    server.handlers._handlers["harness_exec"] = run


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--build-scene", action="store_true")
    args = parser.parse_args(argv)

    sys.path.insert(0, ADDON_DIR)
    sys.path.insert(0, HERE)

    if args.build_scene:
        import scene

        scene.build(args.scene)
        return

    try:
        from blender_mcp_addon.socket_server import MCPSocketServer

        server = MCPSocketServer(host="127.0.0.1", port=args.port)
        _install_harness_handlers(server, args.scene)
        if not server.start():
            raise RuntimeError(f"server failed to start on port {args.port}")
    except BaseException:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(3)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
