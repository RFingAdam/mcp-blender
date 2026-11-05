"""Cases shared by the server's result_failed and the add-on's _succeeded.

The two functions are separate copies (the add-on cannot import the server
package), so both test files run the same table to keep them from drifting.
Each row is (reply, failed).
"""

RESULT_CASES = [
    ({"error": "x"}, True),
    ({"success": False}, True),
    ({"success": False, "error": None}, True),
    ({"success": True, "error": "x"}, True),
    ({"success": True, "error": None}, False),
    ({"success": True}, False),
    ({"error": None}, False),
    ({"error": ""}, False),
    ({}, False),
    (["not", "a", "dict"], False),
    ("text", False),
    (None, False),
]
