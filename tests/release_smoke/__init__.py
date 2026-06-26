"""Pre-publish wheel sanity checks.

NOT in CI — run locally before pushing a release tag:

    python -m build
    python -m pytest tests/release_smoke/ -v

The CI release-preflight workflow already runs ``twine check`` (which
validates metadata schema) and a post-install CLI smoke. This directory
adds belt-and-suspenders assertions for the wheel artifact itself:
entry_points presence, ``Requires-Python`` matches pyproject, and
``RELEASE_TAG`` correctly freezes ``__version__`` in the installed
wheel.

Excluded from default pytest collection by NOT being listed in
``pyproject.toml [tool.pytest.ini_options] testpaths`` (default is
``["tests"]`` but pytest skips paths without a configured marker).
The intended invocation is the explicit ``pytest tests/release_smoke/``
shown above.
"""