# Security

## Supported versions

Security fixes go into the latest 0.5.x release. Versions before 0.5.0 are not supported and
should not be used. See [What older versions exposed](#what-older-versions-exposed).

## Reporting a vulnerability

Use GitHub private vulnerability reporting:
<https://github.com/RFingAdam/meshwire/security/advisories/new>

Please do not open a public issue for a vulnerability. Say which version you tested, which Blender
version and operating system you used, and how to reproduce the problem.

## What older versions exposed

Every version before 0.5.0 has no authentication on the add-on's socket. The published releases are
0.2.0, 0.3.0, 0.4.0 and 0.5.0a1; an unpublished earlier version should be treated the same way. Any
process that can connect to the port can send commands to Blender. The add-on binds to 127.0.0.1 by default, so
in the default setup that means any program on the same machine, whoever it runs as. If the host was
set to a non-loopback address, it means anything that can reach that address.

`execute_script` in those versions runs any Python code it receives, with the same rights as Blender.
Together, that is arbitrary code execution as the user running Blender for any client that can reach
the port.

Version 0.5.0 fixes this with a token handshake and a panel switch for `execute_script` (see below).
Upgrade, and remove the old `blender_mcp_addon` copy first. If you cannot upgrade yet, stop the add-on's
server when you are not using it, keep the host at 127.0.0.1, and do not expose ports 9876 to 9885.

What was confirmed by testing:

- On the commit just before authentication was added, a raw `object_create` sent with no handshake was
  served and the connection stayed open.
- On v0.4.0, run in Blender 4.5.15, a raw `object_create` with no handshake created the object, and so
  did an HTTP POST. The POST was the request a browser `fetch` with `Content-Type: text/plain` sends,
  with a body of one JSON-RPC command line ending in a newline. The add-on answered the request and header
  lines with parse errors, kept the connection open, and ran the body line. A web page could therefore
  make Blender run a command, and with `execute_script`, any Python. v0.5.0a1 has the same socket code
  (only a docstring differs), so it was not run separately. Some current browsers block or ask before a
  public page requests a local address, so whether this works depends on the browser.

A shared `.blend` could also carry the host. Before 0.5.0 the host and port were Scene properties, saved
in the `.blend` file, so a file from someone else could hold a non-loopback host, and clicking Start would
bind there. In 0.5.0 they are add-on Preferences, stored per user and not in the file.

## Threat model

Meshwire is built for one person using Blender with an AI client on the same machine. It defends
against these:

- **Other users on the machine.** The token lives in a file that only you can read (mode 0600 on
  POSIX, in a folder others cannot write to). A connection must prove it holds the token before any
  command runs.
- **Websites in your browser.** A web page can send a request to a local port. Anything that is not a
  valid `hello` in the first 4 KiB within 2 seconds is closed with nothing run, and a web page cannot
  read the token. The Blender socket tests in CI send an HTTP POST with a JSON-RPC body and check
  that nothing runs and the connection closes.
- **The network, when the host is not loopback.** See the next section. The handshake keeps
  strangers from running commands, but it does not hide or protect the traffic.
- **Prompts that try to make the model run code.** `execute_script` refuses every call until you click
  **Allow Python** in the Meshwire sidebar tab. The switch is off at every Blender start, and no
  tool, socket message or `.blend` file can turn it on. Other tools still do what they say, so do not
  point an assistant at a session with work you care about while it reads untrusted text.

## What the token does not protect against

- **Other programs running as you.** They can read the token file, so they can connect. The token
  separates users and remote machines, not processes of the same user.
- **Anything you allow yourself.** Once you click **Allow Python**, the connected client can run any
  Python in Blender until Blender closes.
- **A compromised MCP client or server.** Both hold the token.

## Rotating the token

Rotate the token if you copied it somewhere you no longer trust, or if you think another user got it.

1. Stop the server in the Meshwire tab.
2. Delete the token file. On Linux it is `${XDG_CONFIG_HOME:-~/.config}/meshwire/token`, on macOS
   `~/Library/Application Support/meshwire/token`, and on Windows `%APPDATA%\meshwire\token`. If
   `MESHWIRE_CONFIG_DIR` is set, it is `token` inside that folder.
3. Start the server. It writes a new token.
4. Restart the MCP clients, and update `MESHWIRE_TOKEN` wherever you set it (use **Copy token** again).

## Remote use is plaintext

The handshake is a mutual HMAC-SHA256 challenge-response over fresh nonces. The token never crosses
the socket. After the handshake there is no encryption and no per-message integrity check: the add-on
and the server speak plain newline-delimited JSON over TCP, with no TLS.

If you bind the add-on to a non-loopback host, every command and result travels in plaintext. Someone
on the network path can read them, and can alter them or inject messages into an open connection. The
handshake does not prevent that. Do not do this on a network you do not trust. For remote use, keep the
add-on on 127.0.0.1 and reach it through an SSH tunnel (for example
`ssh -L 9876:127.0.0.1:9876 user@host`). The server must hold the token: set `MESHWIRE_TOKEN` there
(use **Copy token** in the Meshwire tab). If the server refuses the connection because the add-on
sees a different address than the tunnel's local end, its message names the value to put in
`MESHWIRE_ADDON_ADDRESS`.

`MESHWIRE_ADDON_ADDRESS` turns off the relay check: the server then compares the add-on's address with
that value instead of the address it dialled. Set it only for a tunnel or port forward you control. A
tunnel whose local and remote ports are equal (`ssh -L 9876:127.0.0.1:9876`) needs no override and keeps
the check on.
