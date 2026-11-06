"""Wire constants shared by the Meshwire add-on and the MCP server.

This file exists twice, byte for byte: once in the add-on and once in the server
package, because the two ship separately. tests/test_wire.py compares the copies.
It must import nothing from Blender or from either package.
"""

# JSON-RPC error codes the add-on sends on its own, outside any tool call.
E_PARSE = -32700  # the line was not UTF-8, not JSON, or not a JSON object
E_TOO_MANY = -32003  # all client slots are taken
E_TOO_LARGE = -32004  # a request line passed the inbound cap
E_REPLY_TOO_LARGE = -32005  # a reply would not fit in the write buffer
