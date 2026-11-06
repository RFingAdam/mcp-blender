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

Versions 0.2.0, 0.3.0, 0.4.0 and 0.5.0a1 have no authentication on the add-on's socket. Any process
that can connect to the port can send commands to Blender. The add-on binds to 127.0.0.1 by default, so
in the default setup that means any program on the same machine, whoever it runs as. If the host was
set to a non-loopback address, it means anything that can reach that address.

`execute_script` in those versions runs any Python code it receives, with the same rights as Blender.
Together, that is arbitrary code execution as the user running Blender for any client that can reach
the port.

Version 0.5.0 fixes this with a token handshake and a panel switch for `execute_script` (see below).
Upgrade, and remove the old `blender_mcp_addon` copy first. If you cannot upgrade yet, stop the add-on's
server when you are not using it, keep the host at 127.0.0.1, and do not expose ports 9876 to 9885.

What was confirmed by testing: on the commit just before authentication was added, a raw `object_create`
sent with no handshake was served and the connection stayed open. Browser-based attacks through an HTTP
POST were not confirmed on any released version. Earlier releases handled each newline-terminated line
of the stream on its own and did not close the connection after a line that was not JSON, so a request
whose body is a complete JSON-RPC line may have been processed. That is from reading the code, not from
a run.

## Threat model

Meshwire is built for one person using Blender with an AI client on the same machine. It defends
against these:

- **Other users on the machine.** The token lives in a file that only you can read (mode 0600 on
  POSIX, in a folder others cannot write to). A connection must prove it holds the token before any
  command runs.
- **Websites in your browser.** A web page can send a request to a local port. Anything that is not a
  valid `hello` in the first 4 KiB within 2 seconds is closed with nothing run, and a web page cannot
  read the token. The test suite sends an HTTP POST with a JSON-RPC body and checks that nothing runs.
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
