# F-82: Remote Control 远程控制

> 状态: 🔄 进行中（Hermes 兼容 API 已完成）
> 章节: docs/feature_plan/06-ccb-benchmark/f-82-remote-control.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB Remote Control Server，提供远程控制服务，支持 Worker 调度、SSE 事件流推送、ACP 协议中继、Web 管理面板。

### 1.2 背景

CCB 的 `remote-control-server` 是一个全功能 Web 服务 + Web 管理面板，提供远程会话管理、Worker 调度、环境管理、事件流推送和 ACP 协议中继。clawcodex 当前 `extensions/remote_api/` 已有 Hermes 兼容 API（OpenAI 兼容 API 服务器）。

### 1.3 已落地基础设施

`extensions/remote_api/` 已有 Hermes 兼容 API（11 模块 2,597 行）：

| 能力 | 状态 |
|------|:----:|
| completion/responses API | ✅ |
| SSE 流式 | ✅ |
| Bearer 认证 | ✅ |
| CLI `clawcodex api serve` 子命令 | ✅ |

### 1.4 子特性分解

| 子特性 | 说明 | 优先级 |
|--------|------|:------:|
| F-82.1 | RCS 核心基础设施：FastAPI 应用 + asyncio 事件循环 + 配置加载 + 日志 | P0 |
| F-82.2 | 认证系统：API Key / JWT / CORS 中间件 | P0 |
| F-82.3 | 会话管理 API：会话 CRUD、List、详情 | P0 |
| F-82.4 | Worker 注册与调度：心跳检测、长轮询工作分发、断线检测 | P0 |
| F-82.5 | 事件流推送：SSE 流 + WebSocket 双通道 | P1 |
| F-82.6 | 环境管理：多机器部署、测试环境管理 | P1 |
| F-82.7 | ACP 协议中继：WebSocket/SSE 双向 ACP 桥接 | P1 |
| F-82.8 | 会话入口：从 RCS 远程发起新会话 | P1 |
| F-82.9 | Web 管理面板：React 前端或 Jinja2 简单面板 | P2 |

### 1.5 架构设计

```
src/remote_control/
├── __init__.py            # 包初始化 + 版本
├── app.py                 # FastAPI 应用工厂 + 生命周期
├── auth/
│   ├── api_key.py         # API Key 验证中间件
│   ├── jwt.py             # JWT 签发与验证
│   ├── cors.py            # CORS 配置
│   └── middleware.py      # 认证中间件（统一入口）
├── routes/
│   ├── sessions.py        # 会话 CRUD (v1)
│   ├── workers.py         # Worker 注册/心跳/分发
│   ├── events.py          # SSE 事件流
│   ├── environments.py    # 环境管理
│   └── session_ingress.py # 远程会话启动
├── services/
│   ├── work_dispatch.py   # Worker 工作分发逻辑
│   └── store.py           # 内存/数据库存储抽象
├── transport/
│   ├── ws_handler.py      # WebSocket 处理器
│   ├── sse_writer.py      # SSE 写入器
│   ├── event_bus.py       # 内存事件总线（pub/sub）
│   └── acp_relay.py       # ACP 协议中继桥接
└── storage/
    ├── memory.py          # 内存存储（默认）
    └── sqlite.py          # SQLite 持久化（可选）
```

### 1.6 核心数据模型

```python
class WorkerStatus(Enum):
    ONLINE = "online"; OFFLINE = "offline"; BUSY = "busy"; ERROR = "error"

@dataclass
class RemoteSession:
    id: str; status: str  # "running" | "paused" | "completed" | "error"
    created_at: datetime = field(default_factory=datetime.utcnow)
    worker_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Worker:
    id: str; name: str
    status: WorkerStatus = WorkerStatus.OFFLINE
    last_heartbeat: datetime | None = None
    labels: dict[str, str] = field(default_factory=dict)
    current_session_id: str | None = None
```

### 1.7 认证中间件

```python
async def auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/web/"):
        # Web 面板走 JWT Cookie
        token = request.cookies.get("access_token")
        if not token: raise HTTPException(status_code=401)
        request.state.user = verify_jwt(token, config.jwt_secret)
    elif request.url.path.startswith("/api/"):
        # API 走 X-API-Key Header
        api_key = request.headers.get("X-API-Key")
        if not api_key or not hmac.compare_digest(api_key, stored):
            raise HTTPException(status_code=401)
    return await call_next(request)
```

### 1.8 Worker 调度与长轮询

```python
class WorkDispatcher:
    """Worker 工作分发引擎，支持长轮询。"""
    _pending: dict[str, asyncio.Event] = {}

    async def wait_for_work(self, worker_id: str, timeout: int = 30):
        event = asyncio.Event()
        self._pending[worker_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending.pop(worker_id, None)

    async def dispatch_work(self, job: Job) -> str | None:
        workers = await self._store.get_idle_workers(job.labels)
        if not workers: return None
        target = workers[0]
        await self._store.assign_job(job.id, target.id)
        event = self._pending.get(target.id)
        if event: event.set()
        return target.id

    async def check_heartbeats(self, timeout_sec: int = 60):
        threshold = datetime.utcnow() - timedelta(seconds=timeout_sec)
        for worker in await self._store.get_all_workers():
            if worker.last_heartbeat and worker.last_heartbeat < threshold:
                worker.status = WorkerStatus.OFFLINE
```

### 1.9 FastAPI 应用工厂

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(app.state.dispatcher.check_heartbeats())
    yield
    task.cancel()

def create_app(config: RCSConfig) -> FastAPI:
    app = FastAPI(title="ClawCodex RCS", lifespan=lifespan)
    app.state.config = config
    app.state.store = create_store(config)
    app.state.dispatcher = WorkDispatcher(app.state.store)
    app.state.event_bus = EventBus()
    app.add_middleware(CORSMiddleware, ...)
    app.middleware("http")(auth_middleware)
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(workers.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    return app
```

### 1.10 依赖

- `fastapi` + `uvicorn`（Web 框架）
- `PyJWT` / `python-jose`（JWT 认证）
- `sqlalchemy` / `aiosqlite`（持久化，可选）

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | Hermes 兼容 API（completion/responses/SSE/认证） | `extensions/remote_api/` 11 模块 2,597 行 |

### 2.2 下一步计划

1. Session 管理 API
2. Worker 调度 + 长轮询
3. ACP 协议中继

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+数据模型+认证+调度+工厂） | 对齐 FEATURE_PLAN.legacy.md |
