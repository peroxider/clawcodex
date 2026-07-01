# F-98: SSH_REMOTE 远程模式(协同 F-74)

> 状态: 📋 规划中(无既有实现;F-74 Sandbox 为通用 SSH/Docker 抽象,本特性专注 SSH 专属能力)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-98-ssh-remote.md`
> 最后更新: 2026-07-01
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-98: SSH_REMOTE 远程模式`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-98 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

无既有 SSH backend,agent 只在本地 worktree 运行:

- `extensions/orchestrator/agent_runner.py` 等只在本地 worktree 上跑;
- `clawcodex_ext/agent/background_runner.py` 没有 remote 模式;
- 无 SSH key 管理抽象,直接 `subprocess.run(["ssh", ...])` 需 key 在 PATH 且无法恢复会话;
- 无端口转发 / 反向代理 / SOCKS 支持;
- 无 SSH config discover(`~/.ssh/config`)与 host key fingerprint 校验。

可借鉴原语:`team_file.py`(team host 列表)、`extensions/remote_api/`(connection lifecycle)、F-74 `SandboxBackend` / `SandboxSession` Protocol、`background_runner.py`(本地后台 runner 状态机)。

### 0.2 对标

- CCB `SSH_REMOTE` 完整连接管理(密码 / 公私钥 / ssh-agent / ConfigFile / ProxyJump);
- CCB 远程命令流式执行 + 终止语义 + exit code;
- CCB ControlMaster / mux 长连接优化 + 自动重连;
- CCB 与后台会话(F-94)协同的远程 BG session;
- CCB 与 F-74 Sandbox 抽象协同(SSH 只是其中一个 backend)。

### 0.3 解耦落地路径(全部 `clawcodex_ext/services/sandbox_backends/ssh.py`,F-74 backend)

- `models.py` — `SshProfile` / `SshConnection` / `SshExecRequest` / `SshFileTransfer`;
- `auth.py` — password / private key / ssh-agent / config file / proxyjump;
- `connection_pool.py:SshConnectionPool` — ControlMaster / mux + reconnect;
- `exec_stream.py` — 实时 stdout/stderr + 终止信号 + exit code;
- `file_transfer.py` — scp / sftp;
- `tunnel.py` — local / remote forward + dynamic SOCKS;
- `ssh.py:SshSandboxBackend implements SandboxBackend`(F-74 adapter);
- `clawcodex_ext/agent/background_runner.py` 复用 `--ssh-profile`(F-94 协同);
- `clawcodex_ext/command_system/ssh_commands.py` — `/ssh profiles` 命令族。

### 0.4 依赖

- F-74 Sandbox(`SandboxBackend` / `SandboxSession` Protocol,F-98 实现 SSH 版);
- 现有 `team_file.py` host binding / `extensions/remote_api/` connection lifecycle;
- F-94 BG_SESSIONS(远程后台会话 marker 通过 sftp 拉取);
- F-99 DIRECT_CONNECT(远端 session 命名空间);
- F-82 Remote Control(可选 dashboard)。

### 0.5 估算工时

1 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `SSH_REMOTE` 能力,与 [F-74 Sandbox](./f-74-sandbox.md) 协同把 ClawCodex agent 接入**远程 SSH 工作机或远程主机集群**,承担以下职责:

1. SSH 连接管理(密码 / 公私钥 / ssh-agent / ConfigFile 复用);
2. 远程命令执行 + 流式输出 + 终止语义;
3. 远程文件上传/下载 + 路径 mapping;
4. 远程 shell 解释器适配(bash / zsh / fish / sh)与跨平台路径处理;
5. 长连接优化(ControlMaster / 复用 mux);
6. 远程后台会话(F-94 协同);
7. 健康探测 + 自动重连 + 半关闭清理。

F-98 与 F-74 的边界:

- **F-74** = 通用 Sandbox 抽象(Docker / SSH / Firejail / bwrap / 自定义 backend),负责**跨 backend 的统一执行模型**;
- **F-98** = SSH backend 专属实现,**只在 SSH profile 启用**,提供 F-74 抽象的 SSH backend;
- 业务 Tool(`Bash` / `SnipTool` / `Edit` / `BG_SESSIONS`)在两种模式下都需要保持 API 透明,F-98 主要在 `clawcodex_ext/services/sandbox_backends/ssh.py` 实现。

### 1.2 背景

ClawCodex 在以下场景中需要 SSH 后端:

1. **本地弱算力**:开发者用 Mac/Win,把代码提到远程 Linux GPU 机跑(模型推理、CI 命令);
2. **多机协同**:Team lead 在控制节点,worker 在 N 个 worker node 上,F-94 后台会话调度;
3. **统一环境**:不同开发者共用 sandbox 镜像/配置,SSH 远程模板可复用;
4. **审计与合规**:远程主机在合规边界内,本地零数据落地;
5. **教育 / 教学**:学员登录到一台共享教师机。

当前缺口:

- `extensions/orchestrator/agent_runner.py` 等只在本地 worktree 上跑;
- `clawcodex_ext/agent/background_runner.py` 没有 remote 模式;
- 没有 SSH key 管理抽象,直接调用 `subprocess.run(["ssh", ...])` 需要 key 在 PATH,且无法恢复会话;
- 没有端口转发 / 反向代理 / SOCKS 协议支持;
- 没有 SSH config discover(`~/.ssh/config`) 和 host key fingerprint 校验。

借鉴已有原语:

- `clawcodex_ext/services/swarm/team_file.py`:team host 列表(已有 host binding 思路);
- `extensions/remote_api/`:远程 API 抽象,可参考 connection lifecycle;
- F-74 在做协议层(此处简述:F-74 定义 `SandboxBackend` Protocol + `SandboxSession` Protocol,F-98 实现 SSH 版);
- `clawcodex_ext/agent/background_runner.py`:本地后台 runner,F-98 在 SSH 上复用同一状态机。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P98-A | 数据模型(`SshProfile`, `SshConnection`, `SshExecRequest`, `SshFileTransfer`) | 1 天 |
| P98-B | Auth 层:password / private key / ssh-agent / config file / proxyjump | 1.5 天 |
| P98-C | Connection 层:`SshConnectionPool`(ControlMaster / mux)+ reconnect | 2 天 |
| P98-D | Exec/Stream:实时 stdout/stderr 转发 + 终止信号 + exit code | 1.5 天 |
| P98-E | File transfer:`scp` / `sftp`(基于 ssh transport)| 1 天 |
| P98-F | Tunnel:`local forward` / `remote forward` / `dynamic SOCKS` | 1 天 |
| P98-G | F-74 backend adapter:`SshSandboxBackend implements SandboxBackend` | 1.5 天 |
| P98-H | F-94 BG sessions 远程模式:`bg_runner.py --ssh-profile` | 1 天 |
| P98-I | CLI 接入:`/ssh profiles` + `ssh-cli` 子命令 | 0.5 天 |
| P98-J | 单元 + 集成测试(用 paramiko mock + 真实 sshd container) | 2 天 |

**估算总工时**:1 周。

### 1.4 架构设计

```
SSH profile config (~/.clawcodex/ssh/profiles.yaml)
        │
        ▼
SshConnectionPool
  ├─ load ~/.ssh/config
  ├─ mux (ControlMaster / ControlPath)
  ├─ reconnect with exponential backoff
  └─ host key fingerprint enforcement
        │
        ▼
┌──────────────────────┐                ┌──────────────────────┐
│ Local exec / stream  │                │ Remote sandbox       │
│  (clawcodex_ext)     │                │ (F-74 backend)       │
│   - tool execution   │                │   - worktree         │
│   - background run   │                │   - container/bwrap  │
│   - file transfer    │                │   - bg session       │
└──────────────────────┘                └──────────────────────┘
        │
        ▼
F-94 BG_SESSIONS / F-82 Remote Control
```

#### 包结构

```
clawcodex_ext/services/sandbox_backends/
├── __init__.py
├── ssh_backend.py                       # P98-G: F-74 SSH backend
├── ssh_pool.py                          # P98-C: 连接池 + mux
├── ssh_exec.py                          # P98-D: 远程执行 / 流
├── ssh_transfer.py                      # P98-E: scp / sftp
├── ssh_tunnel.py                        # P98-F: 端口转发
└── ssh_auth.py                          # P98-B: 认证策略

clawcodex_ext/services/ssh_profiles/
├── models.py                            # P98-A: 数据模型
├── config_loader.py                     # 读 ~/.clawcodex/ssh/profiles.yaml
└── fingerprint_store.py                 # host key 校验

clawcodex_ext/command_system/
└── ssh_commands.py                      # P98-I: /ssh 命令族

tests/clawcodex_ext/services/sandbox_backends/
├── test_ssh_pool.py
├── test_ssh_exec.py
├── test_ssh_transfer.py
├── test_ssh_backend_f74.py
└── test_ssh_bg_session.py
```

### 1.5 核心数据模型

```python
SshAuthMethod = Literal[
    "password",
    "private_key",
    "agent",
    "config_file",        # 复用 ~/.ssh/config + ControlMaster
    "external",           # 调用 ssh 客户端(轻量级)
]


@dataclass(frozen=True)
class SshProfile:
    name: str
    host: str
    port: int = 22
    user: str = "root"
    auth: SshAuthMethod = "config_file"
    private_key_path: str | None = None
    private_key_passphrase: str | None = None       # 主进程内存,不入文件
    password: str | None = None                     # 同上
    proxy_jump: tuple[str, ...] = ()                # ["bastion:22"]
    forward_agent: bool = False
    strict_host_key: Literal["yes", "no", "ask", "auto"] = "auto"
    known_hosts_path: str | None = None
    connect_timeout_s: float = 10.0
    keepalive_interval_s: float = 15.0
    control_master: bool = True
    control_path: str | None = None                 # 默认 ~/.ssh/cm-%h-%p-%r.sock
    default_shell: Literal["bash", "zsh", "sh", "fish"] = "bash"
    remote_workdir: str | None = None
    remote_env: Mapping[str, str] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()              # ["bg_session", "scp", "tunnel"]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SshConnection:
    profile_name: str
    transport_id: str
    host_fingerprint: str
    mux_socket: str | None
    local_channel_id: str
    opened_at: str
    last_used_at: str
    is_healthy: bool


@dataclass(frozen=True)
class SshExecRequest:
    command: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    stdin_payload: bytes | None = None
    timeout_s: float = 60.0
    capture_stderr: bool = True
    on_stdout: Callable[[bytes], None] | None = None
    on_stderr: Callable[[bytes], None] | None = None
    signal_on_cancel: int = 15                       # 默认 SIGTERM


@dataclass(frozen=True)
class SshExecResult:
    exit_code: int
    duration_ms: int
    stdout_bytes: int
    stderr_bytes: int
    stdout_tail: bytes                              # 最近 ~4 KiB
    stderr_tail: bytes
    timed_out: bool = False
    signal: int | None = None


@dataclass(frozen=True)
class SshFileTransfer:
    op: Literal["upload", "download", "mkdir", "stat", "remove"]
    local_path: Path
    remote_path: str
    mode: int | None = None
    preserve_attrs: bool = True
```

### 1.6 核心接口

```python
class SshConnectionPool:
    """基于 paramiko/asyncssh 的连接复用 + mux."""

    def __init__(self, *, profiles_dir: Path) -> None: ...

    async def connect(self, profile: SshProfile) -> SshConnection: ...

    async def acquire(self, profile_name: str) -> SshConnection: ...

    async def release(self, connection_id: str) -> None: ...

    async def stats(self) -> PoolStats: ...

    async def close(self) -> None: ...


class SshExecClient:
    """远程命令执行与流转发."""

    def __init__(self, pool: SshConnectionPool) -> None: ...

    async def run(self, profile_name: str, request: SshExecRequest) -> SshExecResult: ...

    async def stream(
        self,
        profile_name: str,
        request: SshExecRequest,
    ) -> AsyncIterator[bytes]: ...

    async def cancel(self, run_id: str, *, signal: int = 15) -> bool: ...


class SshTransferClient:
    """scp/sftp 高层 API."""

    async def upload(self, profile_name: str, transfer: SshFileTransfer) -> None: ...
    async def download(self, profile_name: str, transfer: SshFileTransfer) -> None: ...
    async def listdir(self, profile_name: str, remote_path: str) -> list[RemoteDirEntry]: ...


class SshTunnelClient:
    """local / remote / dynamic 转发."""

    async def open_local(self, profile_name: str, *, local_port: int, remote_host: str, remote_port: int) -> Tunnel: ...
    async def open_remote(self, profile_name: str, *, remote_port: int, local_host: str, local_port: int) -> Tunnel: ...
    async def open_dynamic(self, profile_name: str, *, local_port: int) -> Tunnel: ...
    async def close(self, tunnel_id: str) -> None: ...


class SshSandboxBackend:
    """F-74 SandboxBackend Protocol 的 SSH 实现."""

    def __init__(self, *, pool: SshConnectionPool, exec_client: SshExecClient) -> None: ...

    async def create(self, profile: SshProfile, *, workspace: WorkspaceSpec) -> SandboxSession: ...
    async def execute(self, session_id: str, request: SandboxExecRequest) -> SandboxExecResult: ...
    async def destroy(self, session_id: str, *, force: bool = False) -> None: ...
```

### 1.7 Auth 与 Connection Pool

| Auth | 使用场景 | 实现 |
|------|----------|------|
| `password` | 临时测试 / 单次连接 | 由 `SshAuthResolver` 在 profile 内存中查得,立即销毁 |
| `private_key` | 主流场景 | paramiko `RSAKey.from_private_key_file()`,可选 passphrase |
| `agent` | 多 key 复用 | paramiko `SSHClient` 桥接 `~/.ssh/agent`(`SSH_AUTH_SOCK`)|
| `config_file` | 复用现有 `~/.ssh/config` + ProxyJump + ControlMaster | 通过 `subprocess` 调用 `ssh -F` + mux socket,避免双套实现 |
| `external` | 强制走 ssh 客户端(系统 PATH) | subprocess `ssh <host> -- command`,支持全部 ssh CLI 能力 |

> 设计取舍:F-98 默认走 paramiko / asyncssh 当 backend,**只在用户启用 `ssh.external=true` 时 fallback 到 ssh CLI**。后者保留 SystemOpenSSH 才有的特性(如证书登录的 `-o` flags)。

**Connection Pool & ControlMaster**:

- 默认开启 ControlMaster;多个并发任务复用同一条 transport;
- `control_path` 默认 `~/.ssh/cm-{user}-{host}-{port}.sock`,目录权限 `0700`;
- 连接闲置 `keepalive_interval_s` 发送 keepalive;`connect_timeout_s` 防止卡死;
- 失败重试:指数退避 `1, 2, 4, 8, 16s`,最多 5 次;
- 健康探测:每 30s 检查 mux socket 存活;transport 死掉时强制重连;
- host key:默认 `auto`,首次连接信任并写入 `~/.clawcodex/ssh/known_hosts`,后续 `strict=yes`;
- 关闭时有序 `release()` 所有连接。

### 1.8 远程执行、文件传输与 Tunnel

#### 远程执行与流

执行模式:

- `run()`:一次性返回 `SshExecResult`,返回 last 4 KiB stdout/stderr,适合短命令(< 60s);
- `stream()`:async iterator,实时推 stdout/stderr,适合长命令(测试运行、日志 tail);
- `cancel()`:发送 SIGTERM(默认)到远程进程组;30s 后进程仍存活再 SIGKILL;
- 终端宽度 `COLUMNS` 与 termcap 通过 env 转发(`TERM=xterm-256color` 等);
- 中文/UTF-8 编码统一:在执行前显式 `LANG=en_US.UTF-8` 或 `LC_ALL=C.UTF-8`。

流模式设计要点:

- transport 层 +1 个 reader task,推送字节到 channel;
- callback:`on_stdout(bytes)` 与 `on_stderr(bytes)` 都在 worker thread(executor)运行,避免阻塞 transport;
- 取消语义:`cancel()` 一定要确保 reader task 收到 cancel 时仍未传输的字节被丢弃,channel close。

#### File Transfer

- `upload` / `download` 默认走 sftp(基于已建立的 transport);
- 大文件(> 50 MiB)自动切 chunk + 进度回调;
- 支持 preserve mode / mtime;
- 路径映射:本地 `Path` ↔ 远程 POSIX,Windows 上传时建议提前 `tar -C` 打包;
- 路径必须在 `profile.remote_workdir` 子树下,其他路径需要 profile 显式列出 `allowed_paths`。

#### Tunnel

- `local forward`:把远程 service 端口映射到本地(`ssh -L 8080:internal:80 host`);
- `remote forward`:把本地 service 暴露到远程(`ssh -R 80:localhost:8080 host`,典型用法:webhook 调试);
- `dynamic SOCKS5`:`ssh -D 1080 host`,作为代理客户端使用;
- tunnel 与 connection pool 同生命周期;`close()` 时一并清理。

### 1.9 F-74 Backend Adapter 与 F-94 BG 协同

#### F-74 Backend Adapter

实现协议关键点:

```python
@runtime_checkable
class SandboxBackend(Protocol):
    async def create(self, profile, *, workspace) -> SandboxSession: ...
    async def execute(self, session_id, request) -> SandboxExecResult: ...
    async def destroy(self, session_id, *, force=False) -> None: ...


class SshSandboxBackend:
    """每个 profile → remote worktree 作为 sandbox session."""

    async def create(self, profile, *, workspace):
        # 1. 在远端创建 worktree(git worktree add)
        # 2. 写入 .clawcodex/sandbox.json 记录 session_id
        # 3. 启动 keepalive task
        ...
        return SandboxSession(
            session_id=f"ssh-{profile.name}-{ulid()}",
            workspace_root=remote_worktree,
            capabilities=("bash", "background", "process_group", "agent_runner"),
            backend_id="ssh",
        )

    async def execute(self, session_id, request):
        # 复用 SshExecClient.stream / run
        # 把 request.cwd 强制收敛到 session.worktree
        ...

    async def destroy(self, session_id, *, force=False):
        # 1. 删除 .clawcodex/sandbox.json
        # 2. git worktree remove(--force if force)
        # 3. 停止 keepalive
        ...
```

F-74 协议要求:**sandbox session 不得跑出 `workspace_root`**。F-98 通过将 `request.cwd` 在 `execute()` 内强制 resolve 到 session workspace 内 + `allowed_paths` 白名单实现。

#### F-94 BG sessions 协同

`launch_background_runner()` 改造点:

```python
async def launch_background_runner(
    session_id: str,
    *,
    ssh_profile: str | None = None,
    **kwargs,
):
    if ssh_profile:
        # 走 SshSandboxBackend.execute(session_id, request)
        # 把 .background-runner.json 写到远程 worktree
        ...
    else:
        # 走原 fork/subprocess 路径
        ...
```

标记文件路径:`{remote_worktree}/.background-runner.json`,F-94 BG_SESSIONS registry 在远端通过 `sftp` 读取该 marker。

### 1.10 CLI / Tool 与安全失败边界

#### `/ssh` 命令族

```
/ssh profiles list
/ssh profiles add <name> --host example.com --user ubuntu
/ssh profiles test <name> [--command "echo hi"]
/ssh profiles show <name>
/ssh profiles remove <name>
/ssh exec <profile-name> -- <command...>
/ssh scp <profile-name> :remote/path ./local
/ssh tunnel list
/ssh tunnel open local --profile <name> --local 8080 --remote host:80
/ssh tunnel close <tunnel-id>
/ssh sessions ls-bg                            # 列出本机的 bg sessions on remote
```

#### SshClientTool(供 Agent 调用)

| action | 输入 | 输出 |
|--------|------|------|
| `list_profiles` | - | profile 列表 |
| `exec` | `profile_name`, `command`, `timeout_s?` | result(限制输出)|
| `upload` / `download` | `profile_name`, `local_path`, `remote_path` | 成功/失败 |
| `tunnel_open` | `profile_name`, `kind`, `ports` | tunnel_id |

#### 安全与失败边界(合并本节安全 / 失败模式要点)

| 类别 | 规则 / 处理 |
|------|-------------|
| 私钥 passphrase | 仅进程内存,不入任何文件 / log / audit |
| host key | 默认 `strict=yes` 持久化到 `~/.clawcodex/ssh/known_hosts`;切换 `no` 需显式确认 |
| 路径白名单 | `remote_workdir` + `allowed_paths`,其余拒绝 |
| 远程 cmd 注入 | `exec` 接受结构化 `command: tuple[str, ...]`;不接受 shell 拼接字符串 |
| 上行/下行 | scp/sftp 走 ssh transport,不暴露独立端口 |
| Tunnel | 默认仅 `local forward`;`remote forward` 与 `dynamic` 需在 profile 显式启用 |
| SSH agent | 仅 `forward_agent=true` 才转发;默认 false |
| Secret | password / passphrase 走 keyring(`keyring` 库)而不是纯文本 profile yaml |
| `SshProfileNotFoundError` | 配置缺失 → 列出可用 profile |
| `SshAuthenticationError` | 凭据失败 → 指引更新 profile 或 `ssh-add` |
| `SshHostKeyMismatchError` | host key 变更 → 提示显式确认 + 写新指纹 |
| `SshConnectionLostError` | 网络断 → 自动 reconnect 指数退避,标记 stale |
| `SshRemoteTimeoutError` | 远程命令超时 → 强制 SIGTERM → SIGKILL |
| `SshRemoteExecutionError` | 远端非 0 exit → 返回 result 不抛错 |
| `SshPathOutsideAllowed` | 路径越界 → fail closed,返回结构化错误 |
| `SshTunnelFailed` | 端口已被占用 / 权限不足 → 给出明确建议 |

### 1.11 验收标准

1. `SSH_REMOTE=off` 时 `/ssh profiles list` 显示 disabled,不读取 profile;
2. 添加一个 profile 后 `/ssh profiles test` 能在 5s 内完成认证并执行 echo 命令;
3. 启用 ControlMaster 后,同一 profile 的多个并发 exec 不创建新 transport;
4. transport 断线后 30s 内能自动 reconnect,期间命令返回 `SshConnectionLostError`,调用方可以重试;
5. host key 指纹变更时拒绝连接并提示用户 `SSH_REMOTE_KNOWN_HOSTS_UPDATE`;
6. `scp` 50 MiB 文件,平均吞吐 ≥ 局域网限制,无 copy 残留;
7. F-74 `SandboxBackend.create + execute + destroy` 用 SSH backend 跑通 spec;
8. BG session 在 SSH 远程模式下:`launch_background_runner(ssh_profile=...)` 后,`/bg list` 能识别该 session(经 SFTP 拉 marker);
9. tunnel 在 profile 关闭时全部清理,无残留 socket;
10. 单元测试覆盖连接池 / auth / exec / transfer / tunnel / sandbox / bg_session。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | 定义数据模型 + profile config loader | P98-A | 1 天 |
| 2 | 实现 auth resolver + fingerprint store | P98-B | 1.5 天 |
| 3 | 实现 SshConnectionPool + reconnect / mux | P98-C | 2 天 |
| 4 | 实现 SshExecClient run/stream/cancel | P98-D | 1.5 天 |
| 5 | 实现 SshTransferClient scp/sftp | P98-E | 1 天 |
| 6 | 实现 SshTunnelClient | P98-F | 1 天 |
| 7 | 实现 SshSandboxBackend(F-74 adapter) | P98-G | 1.5 天 |
| 8 | 接入 `launch_background_runner(--ssh-profile)` | P98-H | 1 天 |
| 9 | 增加 `/ssh` 命令族 + `SshClientTool` | P98-I | 0.5 天 |
| 10 | 单元/集成/安全测试 + 真 sshd container | P98-J | 2 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| paramiko / asyncssh 维护负担 | 🟡 | 默认 backend 用 asyncssh + 可选 paramiko;`external` 模式 fallback 到 ssh CLI |
| mux socket 残留 | 🟠 | 启动时清理 `~/.ssh/cm-*.sock` 中 uid 匹配的 stale |
| host 中间人攻击 | 🔴 | default `strict=yes` + 持久化 fingerprint + 显式 `--update-known-hosts` |
| 远程命令注入 | 🔴 | exec API 强制 tuple[str,...];不做任何 shell 拼接 |
| 大文件传输阻塞 | 🟡 | chunk + 进度回调 + stream;rate_limit 由 profile 控制 |
| 网络分区导致 stale session | 🟠 | 自动 reconnect + session 重试策略 + 标记 semantically stale 让上层决定 |
| ssh-agent / key 权限 | 🟡 | config 默认 `private_key`,需要显式 `forward_agent` 才转发;子进程不直接 fork agent socat |
| Windows OpenSSH 行为差异 | 🟡 | paramiko 在 Win 上走 socket 非命名管道已验证;测试覆盖 Win SSH server |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-74 Sandbox** | F-98 是 F-74 的 SSH backend 实现,共享 SandboxBackend Protocol |
| **F-94 BG_SESSIONS** | BG session 可在 SSH 远程运行,通过 SFTP 拉 marker |
| **F-82 Remote Control** | 反向:Web/RCS 面板可生成 SSH profile 一键登录远端 |
| **F-85 Pipe IPC / LAN Pipes** | SSH 隧道可作为 LAN_PIPES 物理载体,把 LAN pipe 转 SSH transport |
| **F-96 Cache Break Detection** | 跨网络 context 不能直接复用本地 cache;F-98 + F-96 联手:远端 session 单独计 cache |
| **F-89 Proactive** | Proactive tick 可在指定 SSH profile 的远端节点上执行 |
| **F-100 Dreaming** | Dreaming compaction 任务可在 SSH 远程 worker 上跑(节省本地算力) |

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵), [F-74 Sandbox](./f-74-sandbox.md), [F-94 BG_SESSIONS](./f-94-bg-sessions.md)
