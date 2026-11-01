"""Download a pinned Blender build and print the path to its binary."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

MIRRORS = (
    "https://mirrors.ocf.berkeley.edu/blender/release",
    "https://mirror.clarkson.edu/blender/release",
    "https://ftp.nluug.nl/pub/graphics/blender/release",
    "https://ftp.halifax.rwth-aachen.de/blender/release",
)

# sha256 of blender-<version>-linux-x64.tar.xz, identical on all four mirrors.
SHA256 = {
    "4.2.23": "bea0eb3146be13eae6225409a117b215184f41b7f79e799f97cb3abb8f6dc404",
    "4.5.15": "0d2b8bb2efe97e6c8eb57de6b7322f8800e1984e3125b60decca5f6771e4773e",
    "5.2.3": "78486c018b4443efe5e75ab54c290ed8c15abafd249b862c2c9ce2530a918eec",
}
CACHE = Path.home() / ".cache" / "mcp-blender"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(version: str, target: Path) -> None:
    series = ".".join(version.split(".")[:2])
    name = target.name
    errors = []
    for mirror in MIRRORS:
        url = f"{mirror}/Blender{series}/{name}"
        part = target.with_suffix(".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, part.open("wb") as out:
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
        except (OSError, http.client.HTTPException) as exc:
            errors.append(f"{url}: {exc}")
            continue
        if _sha256(part) != SHA256[version]:
            errors.append(f"{url}: sha256 mismatch")
            part.unlink()
            continue
        part.replace(target)
        return
    raise SystemExit("all mirrors failed:\n" + "\n".join(errors))


def fetch(version: str, dest: Path) -> Path:
    if version not in SHA256:
        raise SystemExit(f"unpinned version {version}; known: {', '.join(SHA256)}")
    dest = Path(dest)
    binary = dest / f"blender-{version}-linux-x64" / "blender"
    if binary.exists():
        return binary
    CACHE.mkdir(parents=True, exist_ok=True)
    tarball = CACHE / f"blender-{version}-linux-x64.tar.xz"
    if not tarball.exists() or _sha256(tarball) != SHA256[version]:
        _download(version, tarball)
    dest.mkdir(parents=True, exist_ok=True)
    top = binary.parent.name
    # Extract beside the target and rename once complete, so an interrupted
    # extraction never leaves a half-populated tree that looks finished.
    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=dest))
    try:
        with tarfile.open(tarball) as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(staging, filter="data")
            else:
                tar.extractall(staging)
        (staging / top).rename(binary.parent)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return binary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--dest", required=True, type=Path)
    args = parser.parse_args(argv)
    print(fetch(args.version, args.dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
