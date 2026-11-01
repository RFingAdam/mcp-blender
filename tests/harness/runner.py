"""Run harness cases inside Blender. Imports only stdlib, bpy and the addon."""

import argparse
import json
import os
import socket
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "addon"))
MAX_STR = 2000


def _block_network():
    def blocked(self, *args, **kwargs):
        raise RuntimeError("harness: network disabled")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked


def _expand(value, tmp):
    if isinstance(value, str):
        return value.replace("{TMP}", tmp)
    if isinstance(value, list):
        return [_expand(v, tmp) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, tmp) for k, v in value.items()}
    return value


def _truncate(value):
    if isinstance(value, str):
        return value if len(value) <= MAX_STR else value[:MAX_STR] + "...[truncated]"
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _truncate(v) for k, v in value.items()}
    return value


def _emit(fh, obj):
    fh.write(json.dumps(obj, default=repr) + "\n")
    fh.flush()
    os.fsync(fh.fileno())


def _outcome(handlers, tool, params):
    try:
        result = handlers.handle(tool, params)
        result = _truncate(json.loads(json.dumps(result, default=repr)))
        return {"status": "ok", "result": result}
    except (Exception, SystemExit) as exc:
        return {
            "status": "exception",
            "type": type(exc).__name__,
            "message": str(exc)[:MAX_STR],
        }


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--start", type=int, default=0)
    args = parser.parse_args(argv)

    import bpy

    sys.path.insert(0, ADDON_DIR)
    sys.path.insert(0, HERE)
    import scene

    if not os.path.exists(args.scene):
        scene.build(args.scene)

    from blender_mcp_addon.handlers import CommandHandlers

    _block_network()
    handlers = CommandHandlers()
    with open(args.cases) as fh:
        cases = json.load(fh)
    tmp = tempfile.mkdtemp(prefix="harness-")

    with open(args.out, "a") as out:
        for i in range(args.start, len(cases)):
            case = cases[i]
            bpy.ops.wm.open_mainfile(filepath=args.scene)
            _emit(out, {"i": i, "event": "start"})
            params = _expand(case["params"], tmp)
            _emit(
                out, {"i": i, "event": "end", "outcome": _outcome(handlers, case["tool"], params)}
            )


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
