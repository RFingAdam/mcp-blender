"""SECURITY.md is the reporting channel and the plaintext warning; keep both from rotting."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
ADVISORY_URL = "https://github.com/RFingAdam/meshwire/security/advisories/new"


def test_security_md_links_private_reporting_and_gives_no_email():
    assert ADVISORY_URL in SECURITY
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", SECURITY)


def test_security_md_says_remote_traffic_is_plaintext():
    # The code has no TLS and no per-message check after the handshake. If that changes,
    # this wording must change with it.
    text = " ".join(SECURITY.split())
    assert "plaintext" in text and "SSH tunnel" in text
    assert "ssl" not in (ROOT / "addon/blender_mcp_addon/socket_server.py").read_text().lower()
