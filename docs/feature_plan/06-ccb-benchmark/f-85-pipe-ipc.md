# F-85: Pipe IPC 多实例协作（UDS + LAN）

> 状态: 🟡 原语层已落地(`clawcodex_ext/services/pipe_ipc/`,553 行,6 模块);命令族 + LAN 扩展待补
> 章节: `docs/feature_plan/06-ccb-benchmark/f-85-pipe-ipc.md`
> 最后更新: 2026-06-30
> 缺口来源: [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵)

## §1 设计规划

### 1.1 目标

对标 CCB `UDS_INBOX` / `LAN_PIPES` 两层架构,在 `clawcodex_ext/services/pipe_ipc/` 已落地 UDS 原语的基础上,补齐面向用户的命名命令族(`/pipes` `/attach` `/detach` `/send` `/claim-main` `/pipe-status` `/peers`)、REPL/TUI 选择面板集成,并扩展 LAN 传输层(TCP + UDP multicast 发现),使 ClawCodex 支持本机多实例 + 局域网多机器群控。

### 1.2 背景

**已完成基础设施**(`clawcodex_ext/services/pipe_ipc/`,共 553 行):

| 模块 | 行数 | 内容 |
|------|------|------|
| `uds.py` | 198 | `UdsPipeServer` / `UdsPipeClient` / `MessageHandler` |
| `models.py` | 131 | `PipeMessageType` (10 种枚举) + `PipeMessage` + `PipePeer` |
| `registry.py` | 99 | `PipeRegistry`(线程安全 + JSON 持久化 + atomic rename) |
| `permissions.py` | 64 | `PipePermissionForwarder`(异步权限请求/响应转发) |
| `codec.py` | 39 | `PipeJsonCodec`(NDJSON 编解码) |
| `__init__.py` | 22 | 公共导出 |

**缺口**(用户面向层):

1. **命名命令族**: `/pipes` / `/attach` / `/detach` / `/send` / `/claim-main` / `/pipe-status` / `/peers` **完全缺失**;
2. **REPL/TUI 集成**: Shift+↓ 选择面板 + 路由模式切换(`selected pipes` ↔ `local main`) **未接入**;
3. **LAN 传输层**: TCP server / UDP multicast beacon / 跨机器 attach **完全缺失**;
4. **SendMessageTool 联动**: `clawcodex_ext/tool_system/tools/send_message.py:437` 的 `uds:` 分支仍是 `NotImplementedError` stub(`feature('UDS_INBOX') is off-by-default upstream`);
5. **主从角色判定**: `PipeRegistry` 缺少 `main` / `sub` 角色自动判定 + `machineId` 稳定指纹;
6. **生命周期**: Server 自动启动 / Client 自动 join / PEER_LEAVE 自动清理 **未串联**。

### 1.3 子特性分解

#### 1.3.1 UDS 子特性(本机多实例)

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P85-A | 主从角色判定(machineId + 启动顺序) | 📋 | 2-3 天 |
| P85-B | Pipe server 自动启动 + Client 自动 join | 📋 | 2-3 天 |
| P85-C | PEER_LEAVE 自动清理 + 心跳保活 | 📋 | 2-3 天 |
| P85-D | `SendMessageTool` `uds:` 分支从 stub 激活(hook 注入) | 📋 | 1-2 天 |
| P85-E | `/pipes` 命名命令(状态栏 + Shift+↓ 选择面板) | 📋 | 5-7 天 |
| P85-F | `/attach` / `/detach` 命令族(7 个子命令) | 📋 | 3-5 天 |
| P85-G | `/send <name> <msg>` + `/send tcp:host:port <msg>` | 📋 | 3-5 天 |
| P85-H | `/claim-main` / `/pipe-status` / `/peers` 命令 | 📋 | 3-5 天 |
| P85-I | 权限转发(BashTool 等需要权限的工具) | 📋 | 3-5 天 |
| P85-J | 路由模式(selected pipes ↔ local main) | 📋 | 2-3 天 |

#### 1.3.2 LAN 子特性(F-85.2,跨机器群控)

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P85-K | TCP 传输层(asyncio.start_server / open_connection) | 📋 | 3-5 天 |
| P85-L | UDP multicast beacon(组地址 224.0.71.67 端口 7101 TTL=1) | 📋 | 3-5 天 |
| P85-M | `machineId` OS 级稳定指纹(Windows 注册表 / POSIX `/etc/machine-id`) | 📋 | 2-3 天 |
| P85-N | 本机网卡自动选择(`getLocalIp()` 排除虚拟网卡) | 📋 | 2-3 天 |
| P85-O | 防火墙规则模板(Windows / macOS / Linux 三平台文档) | 📋 | 1-2 天 |
| P85-P | LAN peer 标记(`[LAN] vmwin11/192.168.50.27`) | 📋 | 1-2 天 |
| P85-Q | `tcp:` 寻址在 SendMessageTool 中的支持 | 📋 | 2-3 天 |

**估算总工时**: UDS 8-10 周,LAN 4-5 周,合计 12-15 周(单人)

### 1.4 架构设计

#### 1.4.1 进程模型与传输层

```
┌─────────────────────────────────────────────────────────────────┐
│ 本机(单台机器)                                                 │
│                                                                 │
│  ┌──────────────┐  UDS socket   ┌──────────────┐              │
│  │ cli-A (main) │◄──────────────►│ cli-B (sub)  │              │
│  │  pipe server │ ~/.clawcodex/  │  pipe client │              │
│  └──────────────┘ pipes/cli-*.sock                              │
│         │                                                       │
│         │ ~/.clawcodex/pipes/registry.json                      │
│         │ (main + subs + machineId)                            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ 局域网(多台机器,LAN_PIPES)                                     │
│                                                                 │
│  机器 A (192.168.50.22)              机器 B (192.168.50.27)   │
│  ┌──────────────────────┐            ┌──────────────────────┐  │
│  │ cli-A (main)         │            │ cli-B (main)         │  │
│  │  ├── UDS server      │◄──TCP──────►├── UDS server       │  │
│  │  ├── TCP server      │  动态端口   ├── TCP server       │  │
│  │  └── UDP beacon      │◄─multicast─►└── UDP beacon       │  │
│  └──────────────────────┘  224.0.71.67                          │
│                                7101/udp TTL=1                   │
└─────────────────────────────────────────────────────────────────┘
```

#### 1.4.2 包结构(全部解耦,不动 `src/`)

```
clawcodex_ext/services/pipe_ipc/   ← 现有原语层(扩展)
├── __init__.py                   # 公共导出扩展
├── codec.py                      # NDJSON 编解码(已有)
├── models.py                     # PipeMessage/PipePeer(已有)+ 增加 tcp_addr/machine_id 字段
├── permissions.py                # PipePermissionForwarder(已有)
├── registry.py                   # PipeRegistry(已有)+ 增加 role 判定 + machineId
├── uds.py                        # UdsPipeServer/Client(已有)
├── tcp.py                        # P85-K: TcpPipeServer / TcpPipeClient
├── transport.py                  # P85-B/D: 传输抽象 + 自动启停 + 协议路由
├── role.py                       # P85-A: main/sub 角色判定 + machineId
├── heartbeat.py                  # P85-C: 心跳保活 + PEER_LEAVE 自动清理
└── commands.py                   # P85-E/F/G/H: /pipes /attach /detach /send /claim-main /pipe-status /peers 命令族

extensions/pipe_ipc/              ← 全新 Layer 2 子系统
├── __init__.py
├── beacon.py                     # P85-L: UDP multicast beacon(beacon 编码/解码/发送/接收)
├── discovery.py                  # P85-M: machineId 指纹 + 本机网卡选择
├── lan_transport.py              # P85-K/Q: 跨机器 TCP 包装 + 寻址
├── tcp_endpoint.py               # P85-K: TCP endpoint 抽象(host:port + connect)
├── firewall.py                   # P85-O: 防火墙规则模板(3 平台,文档+辅助脚本)
├── lan_marker.py                 # P85-P: LAN peer 标记生成
└── capabilities/
    └── transport_protocol.py     # Protocol: PipeTransport / PipeClient(已存在复用)

clawcodex_ext/repl/pipe_integration.py  # P85-J: REPL 提交路径 + 路由模式(猴补丁 src/repl/)
clawcodex_ext/tui/screens/pipe_panel.py # P85-E: TUI 选择面板(Shift+↓ 展开)
clawcodex_ext/tool_system/uds_integration.py # P85-D: SendMessageTool uds: 分支激活(hook)
```

#### 1.4.3 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| UDS 原语层扩展 | `clawcodex_ext/services/pipe_ipc/`(已存在) | 镜像上游目录,猴补丁为主 |
| LAN 跨机器传输 | `extensions/pipe_ipc/`(全新子系统) | 不依赖上游具体实现 |
| Transport Protocol | `extensions/capabilities/transport_protocol.py` | Layer 2 → Layer 1 解耦 |
| `/pipes` 命令族 | `clawcodex_ext/services/pipe_ipc/commands.py` + `clawcodex_ext/command_system/builtins.py` 注册 | 避免改 `src/command_system/` |
| REPL 路由模式 | `clawcodex_ext/repl/pipe_integration.py` 猴补丁 | 不改 `src/repl/` |
| TUI 选择面板 | `clawcodex_ext/tui/screens/pipe_panel.py` | 与现有 TUI 风格一致 |
| SendMessageTool uds: 激活 | `clawcodex_ext/tool_system/uds_integration.py` 注入 | 不改 `src/tool_system/` |
| Feature Flag | F-68 `clawcodex_ext/feature_gate/registry.py` 注册 `UDS_INBOX` / `LAN_PIPES` | 复用 F-68 |

### 1.5 核心数据模型(扩展)

```python
# clawcodex_ext/services/pipe_ipc/models.py(扩展)

from dataclasses import dataclass, field
from enum import Enum

class PipeRole(str, Enum):
    MAIN = "main"           # 首个启动的实例(同 machineId 内)
    SUB = "sub"             # 同 machineId 后续启动
    MASTER = "master"       # attach 了至少一个 slave
    SLAVE = "slave"         # 被 master attach

class TransportKind(str, Enum):
    UDS = "uds"             # Unix Domain Socket / Windows Named Pipe
    TCP = "tcp"             # LAN cross-machine

@dataclass
class PipeMessage:
    """协议消息(已存在,扩展字段)"""
    type: PipeMessageType          # 已有 10 种枚举
    source_id: str                 # 已有
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    target_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    ttl: int = 16
    permission_token: str | None = None
    transport: TransportKind = TransportKind.UDS  # 新增

@dataclass
class PipePeer:
    """Peer 注册表条目(已存在,扩展 LAN 字段)"""
    instance_id: str               # 已有
    hostname: str                  # 已有
    pid: int                       # 已有
    version: str = ""              # 已有
    addr: str = ""                 # 已有: UDS socket path
    transport: TransportKind = TransportKind.UDS  # 已有,但扩展语义
    last_seen: float = field(default_factory=time.time)
    is_master: bool = False        # 已有
    capabilities: list[str] = field(default_factory=list)

    # F-85 新增字段(LAN 必需)
    machine_id: str = ""           # 操作系统级稳定指纹(Windows 注册表 / POSIX /etc/machine-id)
    role: PipeRole = PipeRole.SUB
    tcp_addr: tuple[str, int] | None = None    # (host, port) — LAN 时填
    lan_visible: bool = False      # 是否已通过 beacon 广播
    bound_to: str | None = None    # 被哪个 main/master attach(master = instance_id)
```

```python
# extensions/pipe_ipc/tcp_endpoint.py

@dataclass
class TcpEndpoint:
    host: str                      # IPv4 / hostname
    port: int                      # 0 = ephemeral
    machine_id: str | None = None  # 用于多网卡绑定校验
```

### 1.6 核心接口

#### 1.6.1 传输协议(`extensions/capabilities/transport_protocol.py`)

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class PipeTransport(Protocol):
    """Pipe 传输层抽象 — UDS / TCP 实现可互换。"""

    kind: TransportKind

    async def start(self) -> None:
        """启动 server 或建立 client 连接。"""

    async def stop(self) -> None:
        """清理 socket + 关闭 writers。"""

    async def send(self, message: PipeMessage) -> None:
        """发送单条消息。"""

    @property
    def connected(self) -> bool: ...

    @property
    def local_endpoint(self) -> str | TcpEndpoint:
        """UDS: socket path;TCP: (host, port)"""
```

#### 1.6.2 PipeHub(`clawcodex_ext/services/pipe_ipc/transport.py`)

`PipeHub` 是 UDS / TCP 统一的协调器,负责:

- 自动启动 UDS server(首个实例)
- 自动以 client 模式 join 现有 UDS server
- 自动启停 TCP server(若 `LAN_PIPES` 开启)
- 维护 `PipeRegistry`(内存 + JSON 持久化)
- 心跳保活 + PEER_LEAVE 自动清理

```python
class PipeHub:
    def __init__(
        self,
        instance_id: str,
        registry: PipeRegistry,
        *,
        enable_uds: bool = True,
        enable_tcp: bool = False,
        tcp_port: int = 0,
        machine_id: str | None = None,
    ): ...

    async def start(self) -> None:
        """启动 server(s),join 现有 server,广播 PEER_JOIN。"""

    async def stop(self) -> None:
        """广播 PEER_LEAVE,关闭 server,清理 registry。"""

    async def send(self, message: PipeMessage) -> None:
        """根据 message.transport 路由到 UDS / TCP。"""

    async def attach(self, peer_instance_id: str) -> bool:
        """建立 attach 关系(UDS 同机直接;TCP 跨机)。"""

    async def detach(self, peer_instance_id: str) -> None: ...

    @property
    def role(self) -> PipeRole: ...
    @property
    def peers(self) -> list[PipePeer]: ...
```

#### 1.6.3 Beacon(`extensions/pipe_ipc/beacon.py`)

```python
class LanBeacon:
    """UDP multicast beacon — 224.0.71.67:7101, TTL=1。"""

    MULTICAST_GROUP = "224.0.71.67"
    PORT = 7101
    TTL = 1
    ANNOUNCE_INTERVAL_SEC = 3.0
    PEER_TIMEOUT_SEC = 15.0

    def __init__(
        self,
        machine_id: str,
        local_endpoint: TcpEndpoint | None,
        *,
        interface_ip: str | None = None,
    ): ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    def on_peer_discovered(self, callback: Callable[[PipePeer], None]) -> None: ...
    def on_peer_lost(self, callback: Callable[[str], None]) -> None: ...
```

Beacon 消息格式(NDJSON over UDP):

```json
{
  "type": "beacon_announce",
  "machine_id": "205d6c3a8b...",
  "instance_id": "cli-04d67950",
  "hostname": "vmwin11",
  "ip": "192.168.50.27",
  "tcp_port": 58853,
  "version": "0.5.0",
  "capabilities": ["remoteControl", "bridge"],
  "timestamp": 1719747296.123
}
```

### 1.7 命令族(`clawcodex_ext/services/pipe_ipc/commands.py`)

| 命令 | 描述 | CCB 等价 |
|------|------|---------|
| `/pipes` | 显示所有实例(本机 + LAN);Shift+↓ 展开 TUI 选择面板 | ✅ |
| `/pipes select <name>` | 选中某 instance | ✅ |
| `/pipes all` | 全选 | ✅ |
| `/pipes none` | 取消全选 | ✅ |
| `/attach <name>` | 手动 attach(LAN peer 自动 TCP 连接) | ✅ |
| `/detach <name>` | 断开连接 | ✅ |
| `/send <name> <msg>` | 向指定 pipe 发送消息 | ✅ |
| `/send tcp:host:port <msg>` | 直接 TCP 寻址发送 | ✅ |
| `/claim-main` | 强制声明为 main(machineId 级) | ✅ |
| `/pipe-status` | 详细状态(machineId / role / uptime / peers) | ✅ |
| `/peers` | 列出所有已发现 peer | ✅ |

命令注册(`clawcodex_ext/command_system/builtins.py`):

```python
from clawcodex_ext.services.pipe_ipc.commands import (
    PIPES_COMMAND, ATTACH_COMMAND, DETACH_COMMAND, SEND_COMMAND,
    CLAIM_MAIN_COMMAND, PIPE_STATUS_COMMAND, PEERS_COMMAND,
)

def install_pipe_commands() -> None:
    """Feature-gated install(避免改 src/command_system/)。"""
    if not _is_pipe_feature_enabled():
        return
    reg = get_command_registry()
    reg.register(PIPES_COMMAND)
    reg.register(ATTACH_COMMAND)
    reg.register(DETACH_COMMAND)
    reg.register(SEND_COMMAND)
    reg.register(CLAIM_MAIN_COMMAND)
    reg.register(PIPE_STATUS_COMMAND)
    reg.register(PEERS_COMMAND)

def _is_pipe_feature_enabled() -> bool:
    from clawcodex_ext.feature_gate.registry import get_registry
    reg = get_registry()
    return reg.is_enabled("UDS_INBOX")  # LAN_PIPES 是可选叠加
```

### 1.8 路由模式 + REPL 集成

```python
# clawcodex_ext/repl/pipe_integration.py
# 猴补丁 src/repl/ 的 submit 路径

class RoutingMode(str, Enum):
    SELECTED_PIPES_ONLY = "selected_pipes_only"  # prompt 仅发送 selected
    LOCAL_MAIN = "local_main"                    # prompt 仅本地执行

class PipeRouter:
    def __init__(self, hub: PipeHub):
        self._hub = hub
        self._selected: set[str] = set()
        self._mode: RoutingMode = RoutingMode.LOCAL_MAIN

    def toggle_mode(self) -> RoutingMode:
        self._mode = (
            RoutingMode.SELECTED_PIPES_ONLY
            if self._mode is RoutingMode.LOCAL_MAIN
            else RoutingMode.LOCAL_MAIN
        )
        return self._mode

    async def route_submit(self, prompt: str) -> str | None:
        """返回 None 表示本地处理;否则表示已路由到 selected pipes。"""
        if self._mode is RoutingMode.LOCAL_MAIN or not self._selected:
            return None  # 本地处理
        # 广播到 selected pipes
        for peer_id in self._selected:
            peer = self._hub.registry.get(peer_id)
            if peer is None:
                continue
            await self._hub.send(PipeMessage(
                type=PipeMessageType.COMMAND,
                source_id=self._hub.instance_id,
                target_id=peer_id,
                payload={"prompt": prompt},
                transport=peer.transport,
            ))
        return "routed"  # 通知 REPL:已路由,本地跳过
```

### 1.9 SendMessageTool `uds:` 激活

```python
# clawcodex_ext/tool_system/uds_integration.py
# 猴补丁 clawcodex_ext/tool_system/tools/send_message.py:437 的 NotImplementedError 分支

def install_uds_sender(hub: PipeHub) -> None:
    """注入 uds: 寻址实现,替换 stub。"""
    from clawcodex_ext.tool_system.tools.send_message import _route_message

    def _route_via_uds(addr: str, message: PipeMessage) -> None:
        # addr 形如 "uds:/path/to/socket"
        socket_path = addr[len("uds:"):]
        # 通过 hub 找到对应 client 并发送
        asyncio.create_task(hub.send_to_address(socket_path, message))

    # 替换 _route_message 的 uds: 分支
    _route_message.register_handler("uds", _route_via_uds)
```

类似地,P85-Q 在 LAN 启用时注册 `tcp:` handler:

```python
def install_tcp_sender(hub: PipeHub) -> None:
    """LAN 启用时注入 tcp: 寻址。"""
    from clawcodex_ext.tool_system.tools.send_message import _route_message

    def _route_via_tcp(addr: str, message: PipeMessage) -> None:
        # addr 形如 "tcp:192.168.50.27:58853"
        host, port = addr[len("tcp:"):].split(":")
        endpoint = TcpEndpoint(host=host, port=int(port))
        asyncio.create_task(hub.send_to_tcp(endpoint, message))

    _route_message.register_handler("tcp", _route_via_tcp)
```

### 1.10 machineId 指纹

```python
# extensions/pipe_ipc/discovery.py

import platform
import subprocess
from pathlib import Path

def get_machine_id() -> str:
    """OS 级稳定机器指纹。

    Windows: HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid
    macOS:   IOPlatformSerialNumber via ioreg(对齐 CCB `pipeRegistry.ts:119-125`)
    Linux:   /etc/machine-id(优先)/ /var/lib/dbus/machine-id(兜底)
    """
    system = platform.system()
    if system == "Windows":
        return _windows_machine_guid()
    if system == "Darwin":
        return _macos_platform_uuid()
    return _linux_machine_id()

def _windows_machine_guid() -> str:
    import winreg
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
    ) as key:
        return winreg.QueryValueEx(key, "MachineGuid")[0]

def _macos_platform_uuid() -> str:
    out = subprocess.check_output(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        text=True,
    )
    for line in out.splitlines():
        if "IOPlatformSerialNumber" in line:
            return line.split('"')[1]
    raise RuntimeError("IOPlatformSerialNumber not found")

def _linux_machine_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        if Path(path).exists():
            return Path(path).read_text().strip()
    raise RuntimeError("machine-id not found")
```

### 1.11 本机网卡选择

```python
# extensions/pipe_ipc/discovery.py

import socket
import ifaddr

def get_local_ip(prefer_ipv4: bool = True) -> str:
    """选择最合适的本机 IPv4(排除 loopback / 虚拟网卡)。"""
    candidates: list[tuple[str, str]] = []  # (priority, ip)
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):
                continue  # IPv6 暂不考虑
            if ip.ip.startswith("127."):
                continue
            if ip.ip.startswith("169.254."):  # link-local
                continue
            name_lower = adapter.name.lower()
            if any(x in name_lower for x in ("virtual", "docker", "veth", "br-", "wsl", "vmware", "vbox")):
                continue  # 排除虚拟网卡
            candidates.append((adapter.name, ip.ip))

    if not candidates:
        raise RuntimeError("No suitable network interface found")

    # 优先 en* / eth*(物理网卡)
    candidates.sort(key=lambda c: 0 if c[0].startswith(("en", "eth")) else 1)
    return candidates[0][1]
```

### 1.12 防火墙规则辅助

```python
# extensions/pipe_ipc/firewall.py(纯文档/辅助函数,实际执行需要 sudo/管理员)

def print_firewall_setup_instructions() -> None:
    """打印当前平台的防火墙配置命令(Wizard 风格)。"""
    system = platform.system()
    if system == "Windows":
        # powershell
        print(__doc_windows_firewall__)
    elif system == "Darwin":
        print(__doc_macos_firewall__)
    else:
        print(__doc_linux_firewall__)

def try_auto_setup_firewall() -> bool:
    """尝试自动配置(仅 Linux firewalld / macOS pf / Windows 需要管理员)。失败返回 False,不抛异常。"""
    ...
```

### 1.13 依赖与协同

| 依赖 | 说明 |
|------|------|
| `clawcodex_ext/services/pipe_ipc/`(已存在) | UDS 原语层 |
| F-68 Feature Gate | `UDS_INBOX` / `LAN_PIPES` 注册 |
| F-85.2 LAN 扩展 | 同一 F-Number,合并实现 |
| `clawcodex_ext/repl/` | REPL 集成点 |
| `clawcodex_ext/tui/` | TUI 面板 |
| `clawcodex_ext/tool_system/` | SendMessageTool hook |

| 协同 | 说明 |
|------|------|
| F-84 Daemon | Daemon 的 `remoteControl` Worker 可通过 pipe 与 main REPL 通信 |
| F-82 Remote Control | RCS 可通过 LAN pipe 跨机器调度 |
| F-89 Proactive | Proactive Tick 可通过 pipe 通知远端 |
| F-83 Triggers | 远程 trigger 通过 LAN pipe 派发 |

### 1.14 测试策略

#### 1.14.1 单元测试

- `tests/services/pipe_ipc/test_uds.py` — server/client 双向 + 断线重连 + 大消息
- `tests/services/pipe_ipc/test_registry.py` — JSON 持久化 + atomic rename + 并发写
- `tests/services/pipe_ipc/test_role.py` — main/sub 判定 + machineId
- `tests/services/pipe_ipc/test_commands.py` — 7 个命令参数解析 + 路由
- `tests/services/pipe_ipc/test_permissions.py` — 权限转发超时 + GRANT/DENY 响应
- `tests/extensions/pipe_ipc/test_tcp.py` — TCP server / client / 端口冲突
- `tests/extensions/pipe_ipc/test_beacon.py` — multicast 发送/接收 + peer timeout
- `tests/extensions/pipe_ipc/test_discovery.py` — machineId 三平台 + 网卡选择

#### 1.14.2 集成测试(E2E)

- `tests/services/pipe_ipc/e2e_multi_instance.py`:
  1. spawn 2 个 cli 进程(同 `~/.clawcodex/pipes/` 目录)
  2. 验证第一个变 main,第二个变 sub
  3. 通过 `/send sub-1 hello` 验证消息送达
  4. kill sub-1,验证 main 在 15s 内清理 PEER_LEAVE
- `tests/extensions/pipe_ipc/e2e_lan.py`(可选,需两台机器):
  - 跨机器 attach + send + permission forward
- 参考 `tests/orchestrator/manual_e2e_f38.py` 的 LocalTracker 模式

#### 1.14.3 稳定性门禁

- `tests/stability_gate/test_stage5_extensions.py` 增补 pipe_ipc import smoke test
- 新增 `tests/stability_gate/test_stage8_pipes.py`(轻量,只验证 PipeHub 启停 round-trip)

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|----------|
| 2026-Q2 | UDS 原语层 6 模块 553 行 | `clawcodex_ext/services/pipe_ipc/` |
| 2026-Q2 | PipeMessageType(10 种)+ PipeMessage + PipePeer dataclass | `models.py` |
| 2026-Q2 | PipeRegistry(线程安全 + JSON 持久化 + atomic rename) | `registry.py` |
| 2026-Q2 | PipePermissionForwarder(异步权限转发) | `permissions.py` |
| 2026-06-30 | 详设文档 + 子特性分解 | `f-85-pipe-ipc.md`(本文) |
| 2026-06-30 | 缺口盘点纳入 [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵) | gap-analysis |

### 2.2 下一步计划

按子特性顺序(UDS → LAN):
1. P85-A 角色判定 + P85-C 心跳保活(基础设施)
2. P85-B PipeHub 串联 server/client/registry/heartbeat
3. P85-D SendMessageTool uds: 激活
4. P85-E/F/G/H 命令族实现(7 个命令)
5. P85-I 权限转发 + P85-J 路由模式
6. P85-K LAN TCP 传输 + P85-L multicast beacon
7. P85-M/N/O/P machineId + 网卡选择 + 防火墙 + 标记
8. P85-Q tcp: 寻址 + LAN peer 完整集成

## §3 验收标准

### 3.1 功能验收(UDS 子集)

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| V-1 | 同机器启动 2 个 cli 进程,首个变 main,第二个变 sub | E2E 测试 + `/pipe-status` 验证 |
| V-2 | `~/.clawcodex/pipes/registry.json` 持久化,重启后能恢复 | 单元测试 |
| V-3 | sub 进程崩溃后,main 在 15s 内清理 registry 条目 | E2E |
| V-4 | `/send <name> <msg>` 在 1s 内送达目标 instance | E2E + 单元测试 |
| V-5 | `/attach <lan-peer>` 通过 TCP 建立连接(若 LAN_PIPES 启用) | E2E |
| V-6 | BashTool 在远端执行时,权限请求转发到 main 弹出确认 UI | 集成测试 |
| V-7 | 路由模式切换后,prompt 路由行为正确 | 单元测试 |
| V-8 | `/claim-main` 强制声明为 main(同 machineId 内) | 单元测试 |
| V-9 | SendMessageTool `uds:<path>` 寻址从 stub 激活,能成功发送 | 单元测试 + E2E |
| V-10 | TUI 选择面板(Shift+↓)能展开、选中、确认 | 集成测试 |

### 3.2 功能验收(LAN 子集,F-85.2)

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| V-11 | multicast beacon 启动后,3-5s 内其他机器能发现 | E2E(两台机器) |
| V-12 | 15s 未收到 beacon → peer 标记 lost | 单元测试 |
| V-13 | `get_machine_id()` 三平台均返回稳定字符串 | 单元测试 |
| V-14 | `get_local_ip()` 排除 loopback / 虚拟网卡 | 单元测试 |
| V-15 | TCP 端口冲突时自动选择 ephemeral | 单元测试 |
| V-16 | 防火墙辅助函数在不通过时不抛异常 | 单元测试 |
| V-17 | SendMessageTool `tcp:host:port` 寻址成功 | 单元测试 + E2E |

### 3.3 非功能验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| N-1 | UDS server 启动 < 100ms | Stage 6 perf |
| N-2 | heartbeat 心跳开销 < 1% CPU(空闲时) | Stage 6 perf |
| N-3 | 大消息(1MB)序列化 + 传输 < 50ms(本机) | 单元测试 |
| N-4 | registry 持久化 atomic rename,无半写 | 单元测试 + 并发测试 |
| N-5 | multicast TTL=1,不跨路由器(包头验证) | 单元测试 |
| N-6 | beacon 每 3 秒一次,不阻塞 REPL 主循环 | Stage 6 perf |
| N-7 | 单元测试覆盖率 ≥ 75% | `pytest --cov` |

### 3.4 集成验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| I-1 | 不修改 `src/` 任何业务模块(允许 facade 桩) | `git diff --stat src/` |
| I-2 | `python3 -m pytest tests/stability_gate/ -q` 全绿 | CI |
| I-3 | `extensions/orchestrator/` 测试不受影响 | CI |
| I-4 | UDS 与 LAN 在同一进程同时启用不冲突 | 单元测试 |
| I-5 | 与 F-68 Feature Gate(`UDS_INBOX` / `LAN_PIPES`)集成 | 单元测试 |
| I-6 | 与 F-84 Daemon 的 Worker 通过 pipe 通信 | 集成测试 |
| I-7 | `/pipes` / `/attach` 等命令在 REPL + headless 模式均可用 | 单元测试 |

## §4 风险与约束

| ID | 风险 | 缓解策略 |
|:--:|------|----------|
| R-1 | UDS socket path 在 Windows 上是 Named Pipe(`\\.\pipe\...`),路径长度限制 256 | 短 hash 命名 + 路径长度校验 |
| R-2 | 同 machineId 多 daemon 实例(分别不同 name)互不干扰 | registry 用 `<name>.json` 而非全局 `peers.json` |
| R-3 | multicast 在 WSL / Docker 内可能绑到虚拟网卡 | `get_local_ip()` 自动排除虚拟网卡 + 用户配置覆盖 |
| R-4 | TCP 防火墙未开放 → 跨机 attach 超时 | 启动时 `print_firewall_setup_instructions()` 引导;E2E 测试跳过 |
| R-5 | Beacon TTL=1 不跨路由器,但同子网多路由器可能隔离 | 文档说明;P2 阶段考虑 STUN / mDNS 替代 |
| R-6 | TCP 无认证风险 — 同 LAN 内知道端口即可连接 | CCB 现状同;P2 阶段考虑可选 PSK / mTLS |
| R-7 | SendMessageTool 注入 patch 与上游版本漂移 | 通过协议 handler 注册表(`register_handler`)而非修改 `_route_message` 函数体 |
| R-8 | asyncio + threading 混用(`PipeRegistry._lock` 是 `RLock`) | 严格区分:registry 操作在锁内,I/O 不持锁 |
| R-9 | LAN discover 与 Discovery 的 race(刚启动还没 join 就收到 beacon) | `peer_join` 协议消息与 registry 同步;3s 握手重试 |
| R-10 | multicast 在 IPv6-only 网络不可用 | 当前仅 IPv4;P2 阶段加 IPv6 multicast |

## §5 与现有架构的对齐

- **三层架构**: `extensions/pipe_ipc/` 全新子系统(Layer 2),`clawcodex_ext/services/pipe_ipc/` 扩展原语(Layer 1),`src/` 不动
- **Protocol 接口**: `extensions/capabilities/transport_protocol.py` 定义 `PipeTransport`,UDS / TCP 实现可互换
- **注册模式**: `commands.register()` + `SendMessageTool._route_message.register_handler()`,避免改 `src/command_system/` 与 `src/tool_system/`
- **猴补丁**: `clawcodex_ext/repl/pipe_integration.py` 注入 REPL 提交路径;`clawcodex_ext/tool_system/uds_integration.py` 注入 SendMessageTool
- **Feature Flag**: F-68 `clawcodex_ext/feature_gate/registry.py` 注册 `UDS_INBOX`(UDS 总开关)+ `LAN_PIPES`(LAN 叠加开关)
- **稳定性门禁**: 复用 `tests/stability_gate/` 框架,新增 Stage 8 pipes smoke test

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建(UDS + LAN 双层详设,17 子特性,17 验收项,10 风险) | 派工 F-85 P0 缺口,对接 CCB UDS_INBOX + LAN_PIPES |