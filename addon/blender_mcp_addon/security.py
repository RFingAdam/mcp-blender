"""Runtime security switches. Imports nothing from Blender.

``allow_python`` lives only here, as a module-level boolean. It is off every time
Blender starts. Nothing a client can send, and nothing saved in a .blend file or in
Preferences, can turn it on. The panel operator in ``__init__.py`` and the test
harness are the only callers of ``set_python_allowed``.
"""

PYTHON_OFF_ERROR = (
    "Python execution is off. In Blender, open the sidebar's Meshwire tab and "
    "turn on Allow Python. It stays on until Blender closes."
)

_python_allowed = False


def python_allowed() -> bool:
    """Return True while the user has switched Python execution on."""
    return _python_allowed


def set_python_allowed(on: bool) -> None:
    """Switch Python execution on or off. Callers: the panel operator and the harness."""
    global _python_allowed
    _python_allowed = bool(on)
