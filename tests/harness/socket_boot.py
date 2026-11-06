"""Start the addon socket server inside a GUI Blender. Imports only stdlib, bpy and the addon.

Run as: blender --factory-startup --python socket_boot.py -- --port N --scene FILE
Or, in background mode, build the fixture scene: --build-scene FILE

Two harness-only handlers are added to the live server so the lane can set up and
inspect scene state without leaning on the tools it is checking:

  harness_reset  reload the fixture scene
  harness_exec   run a snippet and return its ``result`` variable

MESHWIRE_CONFIG_DIR must point at the run's own folder: the server makes its token there.
The add-on is imported, not enabled through addon_utils, so Blender has no
preferences entry for it and the add-on runs on its preference defaults.
"""

import argparse
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
BIND_FAILED_EXIT = 4
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

    if not args.build_scene and not os.environ.get("MESHWIRE_CONFIG_DIR"):
        # The server writes a token file on start. Never let a test run write the user's.
        print("MESHWIRE_CONFIG_DIR must be set to this run's own folder", flush=True)
        os._exit(3)

    if args.build_scene:
        import scene

        scene.build(args.scene)
        return

    try:
        import blender_mcp_addon
        from blender_mcp_addon.socket_server import MCPSocketServer, TokenError

        # Register first, as Blender does when the addon is enabled, so a break in
        # class or property registration turns the lane red.
        blender_mcp_addon.register()
        # The harness measures the tools, so it turns the panel switch on as a user would.
        blender_mcp_addon.security.set_python_allowed(True)
        server = MCPSocketServer(host="127.0.0.1", port=args.port)
        _install_harness_handlers(server, args.scene)
        try:
            started = server.start()
        except TokenError as exc:
            # Not a taken port: exit with a different code so the lane does not retry.
            print(str(exc), flush=True)
            os._exit(3)
        if not started:
            print(f"server failed to start on port {args.port}", flush=True)
            os._exit(BIND_FAILED_EXIT)
        # The panel's operators find the running server here, as they do in a real session.
        blender_mcp_addon._server = server
    except BaseException:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(3)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
