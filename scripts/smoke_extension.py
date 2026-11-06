#!/usr/bin/env python3
"""Test the built extension ZIP the way a user gets it, not the source tree.

Validates the ZIP, installs it into a fresh Blender user folder, starts Blender, enables
``bl_ext.user_default.meshwire`` and starts its server. Then it connects with the real client:
the mutual HMAC handshake, followed by ``ping``.

Usage (needs the mcp_blender package on PYTHONPATH and, without a display, xvfb-run):
    python scripts/smoke_extension.py --blender BIN --zip ZIP --work DIR

DIR must not exist. It holds Blender's user folder and Meshwire's config folder, and is
created here so the token folder gets mode 0700 from ensure_token, as in a real install.
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, which only unit tests run on
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
BOOT = Path(__file__).resolve().parent / "smoke_extension_boot.py"
MODULE = "bl_ext.user_default.meshwire"
STARTUP_TIMEOUT = 120.0


def run(cmd: list[str], env: dict[str, str]) -> None:
    print("$", " ".join(cmd), flush=True)
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    print(done.stdout + done.stderr, end="", flush=True)
    if done.returncode != 0:
        raise SystemExit(f"command failed with exit code {done.returncode}")


def manifest_version(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        return tomllib.loads(zf.read("blender_manifest.toml").decode())["version"]


async def handshake(config_dir: Path, expected_version: str) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from mcp_blender.blender_client import BlenderClient

    os.environ["MESHWIRE_CONFIG_DIR"] = str(config_dir)
    os.environ.pop("MESHWIRE_TOKEN", None)
    client = BlenderClient()  # no port: find the instance file the extension wrote
    await client.connect()
    try:
        print(f"handshake ok on port {client.port}", flush=True)
        if not await client.ping():
            raise SystemExit("ping failed")
        print("ping ok", flush=True)
        info = await client.send_command("scene_info")
        print(f"scene_info ok: {json.dumps(info)[:120]}", flush=True)
        entry = json.loads((config_dir / "instances" / f"{client.port}.json").read_text())
        print(
            f"instance file: addon {entry.get('addon')}, blender {entry.get('blender')}", flush=True
        )
        if entry.get("addon") != expected_version:
            raise SystemExit(
                f"add-on reports {entry.get('addon')}, manifest says {expected_version}"
            )
    finally:
        await client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path, help="fresh folder; must not exist")
    args = parser.parse_args()

    if args.work.exists():
        raise SystemExit(f"{args.work} exists; the smoke test needs a fresh folder")
    resources = args.work / "blender"
    config_dir = args.work / "meshwire-config"  # not created: ensure_token makes it
    resources.mkdir(parents=True)

    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = str(resources)
    env["TMPDIR"] = str(args.work)
    env["MESHWIRE_CONFIG_DIR"] = str(config_dir)
    env.pop("MESHWIRE_TOKEN", None)
    env["MESHWIRE_SMOKE_MODULE"] = MODULE

    zip_path = str(args.zip.resolve())
    run([args.blender, "--command", "extension", "validate", zip_path], env)
    run(
        [args.blender, "-b", "--factory-startup", "--command", "extension", "install-file",
         "-r", "user_default", "-e", zip_path],
        env,
    )  # fmt: skip

    log_path = args.work / "blender.log"
    cmd = [args.blender, "--python", str(BOOT)]
    if not os.environ.get("DISPLAY"):
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", *cmd]
    with log_path.open("wb") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=log, env=env, start_new_session=True)
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise SystemExit(
                    f"Blender exited early; see {log_path}\n"
                    + log_path.read_text(errors="replace")[-2000:]
                )
            text = log_path.read_text(errors="replace")
            if "SMOKE_READY" in text:
                break
            time.sleep(0.5)
        else:
            raise SystemExit(f"server did not start in {STARTUP_TIMEOUT}s; see {log_path}")
        for line in text.splitlines():
            if line.startswith("SMOKE_MODULE"):
                print(line, flush=True)
        asyncio.run(handshake(config_dir, manifest_version(args.zip)))
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        # xvfb-run can exit while Blender lingers in the same group, so always finish the group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    print("SMOKE OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
