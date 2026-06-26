"""PluginManager — unified CLI command binding and lifecycle coordinator.

Provides a ``PluginManager`` class that ties together discovery, loading,
enabling/disabling, and unloading of plugins.  It also exposes convenience
methods for integrating with the ClawCodex CLI and hook systems.

Architecture alignment:
- ``docs/feature_plan/06-ccb-benchmark/f-70-plugin.md`` §1.6
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import BasePlugin, PluginContext
from .loader import (
    PluginDiscoveryResult,
    clear_loaded_plugins,
    discover_all_plugins,
    discover_entry_point_plugins,
    discover_plugins,
    get_enabled_plugins,
    get_loaded_plugin,
    get_loaded_plugins,
    load_plugin_from_directory,
    load_plugins_from_directories,
    register_plugin,
    toggle_plugin_enabled,
    unregister_plugin,
)
from .sandbox import (
    SandboxedPlugin,
    SandboxConfig,
    SandboxMode,
    clear_sandboxes,
    get_sandbox,
    register_sandbox,
    remove_sandbox,
)
from .types import LoadedPlugin, PluginError, PluginManifest

logger = logging.getLogger(__name__)


@dataclass
class PluginManager:
    """Central coordinator for the plugin system.

    Handles discovery, loading, lifecycle transitions, sandbox setup,
    and provides a unified API for interacting with the plugin ecosystem.

    Usage::

        mgr = PluginManager()
        mgr.discover()
        mgr.load_all()
        # … use plugins …
        mgr.unload_all()
    """

    #: Whether to auto-discover plugins on instantiation.
    auto_discover: bool = True
    #: Extra directories to scan beyond the defaults.
    extra_dirs: list[str | Path] = field(default_factory=list)
    #: Whether sandbox isolation is enforced for non-builtin plugins.
    sandbox_enabled: bool = False
    #: Per-plugin sandbox overrides (plugin name → SandboxConfig).
    sandbox_configs: dict[str, SandboxConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.auto_discover:
            self.discover()

    # ── Discovery ──────────────────────────────────────────────────────

    def discover(self) -> PluginDiscoveryResult:
        """Run all discovery strategies and register found plugins.

        Returns a ``PluginDiscoveryResult`` with all discovered plugins
        and any errors encountered.
        """
        result = discover_all_plugins(extra_dirs=self.extra_dirs)
        logger.info(
            'Discovered %d plugins (%d errors)',
            len(result.plugins), len(result.errors),
        )
        return result

    def discover_directory(self, directory: str | Path) -> PluginDiscoveryResult:
        """Scan a single directory for plugins."""
        result = discover_plugins(directory)
        for plugin in result.plugins:
            register_plugin(plugin)
        return result

    def discover_entry_points(self) -> list[LoadedPlugin]:
        """Discover plugins registered via Python entry_points."""
        plugins = discover_entry_point_plugins()
        for plugin in plugins:
            register_plugin(plugin)
        return plugins

    # ── Loading ────────────────────────────────────────────────────────

    def load_plugin(
        self,
        plugin: LoadedPlugin,
        tool_registry: Any = None,  # ToolRegistry — avoid circular import
        command_system: Any = None,  # forward compat for F-102
        config: dict[str, Any] | None = None,
        data_dir: Path | None = None,
    ) -> BasePlugin | None:
        """Instantiate and load a plugin's runtime logic.

        If *tool_registry* is provided the plugin's ``get_tools()`` will
        be registered automatically.

        Returns the instantiated ``BasePlugin`` or ``None`` on failure.
        """
        try:
            # Import the plugin module and look for a BasePlugin subclass.
            plugin_path = Path(plugin.path)
            init_file = plugin_path / "__init__.py"
            if not init_file.exists():
                logger.warning("No __init__.py in %s — skipping runtime load", plugin.path)
                return None

            # Resolve the module name from the plugin path.
            import importlib.util  # noqa: local import

            spec = importlib.util.spec_from_file_location(
                f"clawcodex.plugin.{plugin.name}", init_file
            )
            if spec is None or spec.loader is None:
                logger.warning("Could not load spec for %s", plugin.name)
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            # Find BasePlugin subclasses in the module.
            instances: list[BasePlugin] = []
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BasePlugin)
                    and attr is not BasePlugin
                ):
                    try:
                        instance = attr()
                    except TypeError:
                        continue
                    instances.append(instance)

            if not instances:
                logger.warning(
                    "No BasePlugin subclass found in %s", plugin.path
                )
                return None

            # Use the first found instance.
            base_plugin = instances[0]
            ctx = PluginContext(
                registry=tool_registry,  # type: ignore[arg-type]
                command_system=command_system,
                config=config or {},
                data_dir=data_dir,
            )
            # Store context on the instance for later access.
            base_plugin._plugin_context = ctx  # type: ignore[attr-defined]

            # Register tools if registry is available.
            if tool_registry is not None:
                for tool in base_plugin.get_tools():
                    try:
                        tool_registry.register(tool)
                    except Exception as exc:
                        logger.warning(
                            "Failed to register tool %s: %s",
                            getattr(tool, 'name', '?'), exc,
                        )

            # Run async on_load.
            try:
                asyncio.get_event_loop().run_until_complete(
                    base_plugin.on_load(ctx)
                )
            except RuntimeError:
                # No running loop — create one.
                asyncio.run(base_plugin.on_load(ctx))

            logger.info("Loaded plugin: %s", base_plugin.name)
            return base_plugin

        except Exception as exc:
            logger.error("Failed to load plugin %s: %s", plugin.name, exc)
            return None

    def load_all(
        self,
        tool_registry: Any = None,
        command_system: Any = None,
    ) -> dict[str, BasePlugin]:
        """Load all registered enabled plugins.

        Returns a dict mapping plugin name → BasePlugin instance.
        """
        loaded: dict[str, BasePlugin] = {}
        for plugin in get_enabled_plugins():
            instance = self.load_plugin(
                plugin,
                tool_registry=tool_registry,
                command_system=command_system,
            )
            if instance is not None:
                loaded[instance.name] = instance
        return loaded

    # ── Lifecycle ──────────────────────────────────────────────────────

    def enable_plugin(self, name: str) -> bool:
        """Enable a registered plugin."""
        result = toggle_plugin_enabled(name, True)
        if result:
            plugin = get_loaded_plugin(name)
            if plugin:
                self._setup_sandbox(plugin)
        return result

    def disable_plugin(self, name: str) -> bool:
        """Disable a registered plugin."""
        return toggle_plugin_enabled(name, False)

    def uninstall_plugin(self, name: str) -> bool:
        """Unregister and remove a plugin."""
        sandbox = get_sandbox(name)
        if sandbox is not None:
            sandbox.process.terminate() if sandbox.process else None
            remove_sandbox(name)
        return unregister_plugin(name)

    def unload_all(self) -> None:
        """Unload all registered plugins and clean up sandboxes."""
        for name in list(get_loaded_plugins()):
            plugin = get_loaded_plugin(name.name)
            if plugin:
                try:
                    asyncio.run(plugin.on_unload())
                except Exception as exc:
                    logger.error("Error unloading plugin %s: %s", name.name, exc)
        clear_loaded_plugins()
        clear_sandboxes()
        logger.info("All plugins unloaded")

    # ── Sandbox ────────────────────────────────────────────────────────

    def _setup_sandbox(self, plugin: LoadedPlugin) -> None:
        """Configure sandbox for a plugin if sandboxing is enabled."""
        if not self.sandbox_enabled:
            return
        cfg = self.sandbox_configs.get(plugin.name)
        if cfg is None:
            cfg = SandboxConfig(mode=SandboxMode.PROCESS)
        register_sandbox(plugin, cfg)

    def get_sandbox(self, plugin_name: str) -> Any | None:
        """Get the sandbox for a plugin."""
        return get_sandbox(plugin_name)

    # ── Status queries ─────────────────────────────────────────────────

    def list_plugins(self, enabled_only: bool = False) -> list[LoadedPlugin]:
        """List registered plugins."""
        if enabled_only:
            return get_enabled_plugins()
        return get_loaded_plugins()

    def get_plugin_status(self, name: str) -> dict[str, Any] | None:
        """Get detailed status for a plugin."""
        plugin = get_loaded_plugin(name)
        if plugin is None:
            return None
        return {
            "name": plugin.name,
            "version": plugin.manifest.version,
            "enabled": plugin.enabled,
            "source": plugin.source,
            "path": plugin.path,
            "has_sandbox": get_sandbox(name) is not None,
        }

    # ── Cleanup ────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Full shutdown: unload plugins, clean sandboxes, clear registry."""
        self.unload_all()


# ── Module-level helpers ──────────────────────────────────────────────


def create_manager(
    auto_discover: bool = True,
    extra_dirs: list[str | Path] | None = None,
    sandbox_enabled: bool = False,
) -> PluginManager:
    """Convenience factory for creating a PluginManager.

    Usage::

        mgr = create_manager(sandbox_enabled=True)
    """
    return PluginManager(
        auto_discover=auto_discover,
        extra_dirs=extra_dirs or [],
        sandbox_enabled=sandbox_enabled,
    )
