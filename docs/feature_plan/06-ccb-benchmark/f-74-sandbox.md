# F-74: Sandbox 沙箱远程执行

> 状态: 📋 规划中
> 章节: docs/feature_plan/06-ccb-benchmark/f-74-sandbox.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB `sandbox-toggle`，实现沙箱远程执行环境（Docker/SSH），隔离 agent 执行的 Bash 命令。

### 1.2 背景

CCB 支持 `sandbox-toggle` 命令将执行环境切换到沙箱模式，以及 SSH 远程执行命令。clawcodex 当前所有 Bash/Shell 执行均在本地，无沙箱隔离或远程执行能力。

### 1.3 子特性分解

| 编号 | 子特性 | Python 依赖 | 状态 | 预计工时 |
|:----:|--------|:-----------:|:----:|:--------:|
| P74-A | Sandbox 执行器抽象 | 无 | 📋 | 3-5d |
| P74-B | Docker 沙箱执行 | `docker-py` | 📋 | 3-5d |
| P74-C | SSH 远程执行 | `asyncssh` | 📋 | 3-5d |
| P74-D | `/sandbox` CLI 命令 | 无 | 📋 | 2-3d |
| P74-E | 沙箱配置文件 | 无 | 📋 | 1-2d |

### 1.4 架构

```
src/services/sandbox/
├── base.py              # SandboxExecutor（抽象基类）
├── local.py             # LocalExecutor（直接 subprocess，当前行为）
├── docker.py            # DockerExecutor（docker run 沙箱）
├── ssh.py               # SSHExecutor（asyncssh 远程执行）
├── manager.py           # SandboxManager（全局切换/状态）
└── config.py            # SandboxConfig（pydantic model）
```

### 1.5 SandboxExecutor 抽象接口

```python
@dataclass
class SandboxResult:
    exit_code: int; stdout: str; stderr: str
    duration_ms: int = 0; error: str | None = None

@dataclass
class SandboxConfig:
    timeout: int = 30; work_dir: str = "/tmp"
    env_vars: dict[str, str] = field(default_factory=dict)

class SandboxExecutor(ABC):
    type: str = ""  # "local" / "docker" / "ssh"

    @abstractmethod
    async def execute(self, command: str) -> SandboxResult: ...
    @abstractmethod
    async def upload_file(self, local_path: str, remote_path: str) -> None: ...
    @abstractmethod
    async def download_file(self, remote_path: str, local_path: str) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...
```

### 1.6 SandboxManager

```python
class SandboxManager:
    _current: SandboxExecutor | None = None

    @classmethod
    def get_current(cls) -> SandboxExecutor:
        if cls._current is None:
            cls._current = LocalExecutor(SandboxConfig())
        return cls._current

    @classmethod
    def set_current(cls, executor: SandboxExecutor) -> None:
        if cls._current is not None:
            asyncio.ensure_future(cls._current.close())
        cls._current = executor
```

### 1.7 本地执行器

```python
class LocalExecutor(SandboxExecutor):
    type = "local"

    async def execute(self, command: str) -> SandboxResult:
        start = time.monotonic()
        proc = await asyncio.create_subprocess_shell(
            command, stdout=PIPE, stderr=PIPE, cwd=self.config.work_dir,
            env={**dict(os.environ), **self.config.env_vars},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.config.timeout)
        except asyncio.TimeoutError:
            proc.kill(); await proc.wait()
            return SandboxResult(exit_code=-1, stdout="", stderr="", error=f"Timed out after {self.config.timeout}s")
        return SandboxResult(exit_code=proc.returncode or 0, stdout=stdout.decode() if stdout else "", stderr=stderr.decode() if stderr else "")
```

### 1.8 Docker 执行器核心

```python
class DockerExecutor(SandboxExecutor):
    type = "docker"

    def __init__(self, config: DockerSandboxConfig):
        super().__init__(config)
        import docker
        self.client = docker.from_env()
        self.container = None

    async def ensure_container(self):
        if self.container is None:
            self.container = self.client.containers.create(
                image=self.config.image or "ubuntu:22.04",
                command=["sleep", "infinity"], detach=True,
                working_dir=self.config.work_dir, environment=self.config.env_vars,
            )
            self.container.start()

    async def execute(self, command: str) -> SandboxResult:
        await self.ensure_container()
        start = time.monotonic()
        exit_code, output = self.container.exec_run(cmd=["bash", "-c", command], timeout=self.config.timeout)
        return SandboxResult(exit_code=exit_code, stdout=output.decode() if isinstance(output, bytes) else str(output), stderr="")
```

### 1.9 依赖

| 依赖 | 类型 |
|------|------|
| Docker | 可选（Docker 执行器） |
| `docker-py` | 可选（Docker Python SDK） |
| `asyncssh` | 可选（SSH 执行器） |

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+接口+执行器实现） | 对齐 FEATURE_PLAN.legacy.md |
