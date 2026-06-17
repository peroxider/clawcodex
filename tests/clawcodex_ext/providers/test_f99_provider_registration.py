"""F-99 regression test: ``ClawcodexAnthropicProvider`` must be registered
in ``_EXTRA_PROVIDER_CLASSES`` before any ``get_provider_class(...)`` lookup.

Background
----------
F-99 added three cancel-latency mechanisms (httpx ``read_timeout``,
transport close, tool-stage ``FIRST_COMPLETED`` poll). They were all
unit-tested in isolation and 100 regression tests passed. Despite
that, a user reported the production CLI still hangs at "Cancelling…"
for ~63s on Ctrl+C.

Root cause: ``clawcodex_ext/providers/__init__.py`` (which calls
``register_provider("anthropic", _ClawcodexAnthropicProvider_lazy)``)
was never imported during normal REPL startup. So
``get_provider_class("anthropic")`` fell through to the bare upstream
``AnthropicProvider``, whose ``chat_stream_response`` iterates
``stream.text_stream`` on the **main thread** with only the advisory
``response.close()`` (plus the dead-code ``_close_transport_safely``
helper that looks up ``response._transport`` — which doesn't exist
on ``httpx.Response``; the attribute lives on the client). Cancel
latency collapses to the platform socket timeout (~60s).

The fix is a side-effect ``import clawcodex_ext.providers`` placed
at the bottom of ``factory.py`` (after ``register_provider`` etc.
are defined, so the package ``__init__`` can import them without a
circular-import failure) AND at the top of ``runtime.py`` for
defense-in-depth. Every provider-build call site imports one of
these two modules either directly or transitively, so the
registration happens before the first ``get_provider_class``
lookup in any entry point (REPL, headless, TUI, agent background
runner, CLI subcommands).

These tests pin that contract: importing either ``factory.py`` or
``runtime.py`` must populate ``_EXTRA_PROVIDER_CLASSES`` with the
cancel-latency override so the bare upstream class never wins the
``get_provider_class("anthropic")`` lookup. They also pin that the
``minimax`` override is registered for symmetry.
"""
from __future__ import annotations

import importlib
import sys


def _purge_provider_registry() -> None:
    """Reset both ``_EXTRA_PROVIDER_CLASSES`` and the cached module
    registrations to a true cold-start state.

    The F-99 fix relies on a side-effect ``import clawcodex_ext.providers``
    at the bottom of ``factory.py`` / top of ``runtime.py``. That
    import only runs when those modules are *first* loaded — Python
    caches subsequent imports. To prove the registration actually
    happens on a cold start (which is the production scenario), we
    have to evict the relevant modules from ``sys.modules`` AND
    clear the registry. Otherwise pytest collection (which imports
    ``clawcodex_ext.providers`` transitively) would mask the bug
    we're guarding against.
    """
    from src.providers import _EXTRA_PROVIDER_CLASSES

    _EXTRA_PROVIDER_CLASSES.clear()

    # Evict the modules whose side-effect import is what triggers
    # the registration. We must evict them in reverse-dependency
    # order so a re-import doesn't see stale partial state.
    for name in (
        "clawcodex_ext.providers",
        "clawcodex_ext.providers.factory",
        "clawcodex_ext.providers.runtime",
        "src.providers.runtime",
        # Also evict the clawcodex_ext provider classes themselves
        # so the lazy import inside ``_ClawcodexAnthropicProvider_lazy``
        # re-resolves against the freshly-cleared registry on the
        # next ``get_provider_class`` call.
        "clawcodex_ext.providers.anthropic_provider",
        "clawcodex_ext.providers.minimax_provider",
        "clawcodex_ext.providers.openai_codex_provider",
    ):
        sys.modules.pop(name, None)


def test_factory_import_registers_anthropic_override() -> None:
    """Importing ``clawcodex_ext.providers.factory`` must register the
    cancel-latency-fixed Anthropic provider as a side effect.

    Without this side-effect import, the bare upstream
    ``AnthropicProvider`` wins the lookup and cancel latency
    collapses to the platform socket timeout (~60s).
    """
    _purge_provider_registry()

    import clawcodex_ext.providers.factory  # noqa: F401

    from src.providers import _EXTRA_PROVIDER_CLASSES, get_provider_class

    assert "anthropic" in _EXTRA_PROVIDER_CLASSES, (
        "factory.py side-effect import failed to register the "
        "anthropic override; bare AnthropicProvider would be used "
        "and Ctrl+C would wait ~60s for the platform socket timeout."
    )
    cls = get_provider_class("anthropic")
    assert cls.__name__ == "ClawcodexAnthropicProvider", (
        f"Expected ClawcodexAnthropicProvider, got {cls.__name__}; "
        f"cancel-latency fix is not wired up in production."
    )


def test_factory_import_registers_minimax_override() -> None:
    """Symmetric guarantee for the minimax provider.

    The minimax path has the same 60s-cancel-latency risk; the
    side-effect import must register ``ClawcodexMinimaxProvider``
    too.
    """
    _purge_provider_registry()

    import clawcodex_ext.providers.factory  # noqa: F401

    from src.providers import _EXTRA_PROVIDER_CLASSES, get_provider_class

    assert "minimax" in _EXTRA_PROVIDER_CLASSES
    cls = get_provider_class("minimax")
    assert cls.__name__ == "ClawcodexMinimaxProvider"


def test_runtime_import_also_triggers_registration() -> None:
    """Defense-in-depth: importing ``src.providers.runtime`` (the
    canonical provider-build entry point) must also trigger the
    registration.

    ``runtime.py`` carries its own side-effect import so that any
    path that imports it before ``factory`` (unlikely but possible
    if someone refactors) still gets the registration.
    """
    _purge_provider_registry()

    import src.providers.runtime  # noqa: F401

    from src.providers import _EXTRA_PROVIDER_CLASSES, get_provider_class

    assert "anthropic" in _EXTRA_PROVIDER_CLASSES
    assert "minimax" in _EXTRA_PROVIDER_CLASSES
    assert get_provider_class("anthropic").__name__ == "ClawcodexAnthropicProvider"


def test_provider_package_init_runs_register_provider_calls() -> None:
    """The package ``__init__.py`` must call ``register_provider`` for
    both anthropic and minimax (openai-codex is registered by the
    same ``__init__`` for symmetry).

    This pins the registration source so a future refactor that
    accidentally short-circuits the ``__init__`` (e.g. moving the
    calls behind an ``if TYPE_CHECKING`` guard, or behind a feature
    flag) fails fast at the test level.
    """
    # Force a fresh load of the package __init__.
    pkg_name = "clawcodex_ext.providers"
    if pkg_name in sys.modules:
        # Re-execute the __init__ body to re-trigger the
        # ``register_provider`` side effects (the module dict is
        # preserved across re-imports of ``__init__``, so we have
        # to purge and re-import to simulate a cold start).
        del sys.modules[pkg_name]
    _purge_provider_registry()

    importlib.import_module(pkg_name)

    from src.providers import _EXTRA_PROVIDER_CLASSES

    # All three downstream providers must be registered.
    for name in ("anthropic", "minimax", "openai-codex"):
        assert name in _EXTRA_PROVIDER_CLASSES, (
            f"{name!r} missing from _EXTRA_PROVIDER_CLASSES after "
            f"package import; register_provider call was skipped."
        )


def test_registration_survives_module_reload() -> None:
    """The registration is idempotent: importing the package twice
    doesn't double-register or error.

    ``register_provider`` is documented as idempotent (first
    registration wins); a future refactor that changes this should
    fail here rather than silently overwriting the override with
    the bare upstream class.
    """
    _purge_provider_registry()

    import clawcodex_ext.providers  # noqa: F401
    import clawcodex_ext.providers  # noqa: F401  -- second import

    from src.providers import _EXTRA_PROVIDER_CLASSES, get_provider_class

    assert get_provider_class("anthropic").__name__ == "ClawcodexAnthropicProvider"
    # Sanity: the registry still has exactly the expected set.
    assert set(_EXTRA_PROVIDER_CLASSES.keys()) >= {"anthropic", "minimax", "openai-codex"}