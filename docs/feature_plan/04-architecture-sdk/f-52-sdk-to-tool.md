# F-52: Python SDK 方法注册为 Tool

> 状态: ✅ 已完成
> 章节: docs/feature_plan/04-architecture-sdk/f-52-sdk-to-tool.md
> 最后更新: 2026-07-16

## §1 设计规划

### 1.1 目标

将 SOP 转换解析出的 `SourceOperation`（如 `detect_modality`、`load_dataset`）以及 OpenAPI Spec 解析出的 API 操作注册为 clawcodex 可调用的 `Tool` 对象。

**增强目标（OpenAPI Schema 路径）：**
1. 增强 `SdkParser` 提取完整的 OpenAPI schema（参数类型、请求体、响应）
2. 实现 `register_http_tools()` 函数，为每个 operation 生成 HTTP Tool
3. 在 `convert_sop_to_agent()` 中调用工具注册
4. 生成 HTTP 调用的 wrapper 脚本（类似当前 Python 源码路径的 bash wrapper）

### 1.2 实现计划

| 组件 | 文件 | 说明 |
|------|------|------|
| `SdkParam` | `extensions/sop_converter/sdk_parser.py` | 新增参数类型，存储参数类型、是否必填、描述、位置和schema |
| `SdkMethod` 增强 | `extensions/sop_converter/sdk_parser.py` | 新增 http_method、http_path、params、request_body、responses、tags 字段 |
| `_parse_openapi` 增强 | `extensions/sop_converter/sdk_parser.py` | 提取基础URL、解析参数为SdkParam对象、解析请求体和响应信息 |
| `register_http_tools()` | `extensions/sop_converter/tool_registry_bridge.py` | 将 SdkMethod 转换为 HTTP 类型的 AgentToolSpec 并注册 |
| `_build_http_input_schema()` | `extensions/sop_converter/tool_registry_bridge.py` | 构建 HTTP 工具的 JSON Schema 输入schema |
| `_build_http_call_impl()` | `extensions/sop_converter/tool_registry_bridge.py` | 构建 HTTP 工具的调用实现配置 |
| `_generate_http_wrapper_script()` | `extensions/sop_converter/tool_registry_bridge.py` | 生成独立的 HTTP wrapper 测试脚本 |
| `convert_sop_to_agent()` 增强 | `extensions/sop_converter/convert_sop_skill.py` | 调用 register_http_tools() 注册 HTTP 工具 |

### 1.3 验收标准

#### 1.3.1 基础验收标准（原有）
1. `ToolWrapper(operation).to_tool().name == "detect_modality"`
2. 注册后 `registry.get_tool("detect_modality")` 返回有效 `Tool`
3. 无 Python 源文件时优雅降级

#### 1.3.2 OpenAPI Schema 路径验收标准（新增）

| 编号 | 验收项 | 描述 | 验证方法 |
|------|--------|------|----------|
| OA-1 | OpenAPI 解析参数类型 | 解析后的 SdkMethod.params 包含完整的参数类型信息 | 单元测试验证 param_type 字段 |
| OA-2 | OpenAPI 解析请求体 | 解析后的 SdkMethod.request_body 包含请求体 schema | 单元测试验证 request_body 字段 |
| OA-3 | OpenAPI 解析响应 | 解析后的 SdkMethod.responses 包含响应定义 | 单元测试验证 responses 字段 |
| OA-4 | HTTP Tool 注册 | register_http_tools() 生成有效的 AgentToolSpec | 单元测试验证生成的 spec 结构 |
| OA-5 | HTTP Tool 类型 | 生成的工具 call_type 为 "http" | 验证 spec.call_type == "http" |
| OA-6 | HTTP Tool 调用配置 | call_impl 包含 method 和 url | 验证 spec.call_impl 结构 |
| OA-7 | JSON Schema 输入验证 | input_schema 包含完整的参数类型和必填约束 | 验证 input_schema 结构 |
| OA-8 | HTTP Wrapper 脚本生成 | 为每个操作生成独立的 Python wrapper 脚本 | 验证脚本文件生成 |
| OA-9 | SOP 转换集成 | convert_sop_to_agent() 自动注册 HTTP 工具 | 集成测试验证转换结果 |
| OA-10 | 完整流程验证 | OpenAPI Spec → 解析 → 工具注册 → Agent 生成 | 端到端测试 |

### 1.4 依赖

F-50（SourceCodeParser 已输出 SourceOperation）

## §2 技术方案

### 2.1 SdkParam 数据结构

```python
@dataclass(frozen=True)
class SdkParam:
    name: str
    param_type: str = "string"
    required: bool = False
    description: str = ""
    location: str = "query"
    schema: dict | None = None
```

### 2.2 SdkMethod 增强结构

```python
@dataclass(frozen=True)
class SdkMethod:
    name: str
    description: str
    parameters: list[str] = field(default_factory=list)
    required_params: list[str] = field(default_factory=list)
    return_type: str | None = None
    original_class: str | None = None
    http_method: str | None = None       # 新增
    http_path: str | None = None         # 新增
    params: list[SdkParam] = field(default_factory=list)  # 新增
    request_body: dict | None = None     # 新增
    responses: dict[str, dict] = field(default_factory=dict)  # 新增
    tags: list[str] = field(default_factory=list)  # 新增
```

### 2.3 register_http_tools() 函数签名

```python
def register_http_tools(
    methods: list[SdkMethod],
    *,
    persist: bool = True,
    overwrite: bool = True,
    bundle_dir: str | Path | None = None,
    bundle_id: str | None = None,
    generate_wrappers: bool = True,
) -> dict[str, str]:
```

### 2.4 生成的 HTTP Tool Spec 结构

```json
{
  "name": "list-users",
  "description": "List all users",
  "input_schema": {
    "type": "object",
    "properties": {
      "limit": {"type": "integer", "description": "Max results"},
      "offset": {"type": "integer"}
    },
    "required": ["offset"]
  },
  "call_type": "http",
  "call_impl": {
    "method": "GET",
    "url": "/users"
  },
  "tags": ["users"],
  "source": "openapi-converter"
}
```

### 2.5 HTTP Wrapper 脚本功能

生成的 wrapper 脚本支持：
- 命令行参数解析（argparse）
- 参数类型验证
- 请求构建
- 实际 HTTP 请求发送
- 响应输出

## §3 实现路径

### 3.1 阶段一：OpenAPI Schema 解析增强

1. 新增 `SdkParam` 类
2. 增强 `SdkMethod` 类，添加 HTTP 相关字段
3. 修改 `_parse_openapi()` 方法，提取完整的参数类型、请求体、响应信息
4. 添加 `openapi_base_url` 属性

### 3.2 阶段二：HTTP Tool 注册

1. 实现 `_build_http_input_schema()` 构建 JSON Schema
2. 实现 `_build_http_call_impl()` 构建 HTTP 调用配置
3. 实现 `register_http_tools()` 主函数

### 3.3 阶段三：HTTP Wrapper 脚本生成

1. 定义 `_HTTP_WRAPPER_TEMPLATE` 模板
2. 实现 `_generate_http_wrapper_script()` 生成脚本
3. 集成到 `register_http_tools()` 中

### 3.4 阶段四：SOP 转换集成

1. 修改 `convert_sop_to_agent()` 调用 `register_http_tools()`
2. 更新 skill 的 allowed_tools 使用 kebab-case 名称
3. 更新输出结果包含 OpenAPI 相关信息

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补充 OpenAPI Schema 路径方案 | 实现 F-52 完整功能 |
| 2026-07-16 | 完成所有功能实现 | 实现 F-52 完整路径 |

## §5 完成情况

### 5.1 实现进度

| 组件 | 状态 | 说明 |
|------|------|------|
| `SdkParam` | ✅ 完成 | 新增参数类型，存储参数类型、是否必填、描述、位置和 schema |
| `SdkMethod` 增强 | ✅ 完成 | 新增 http_method、http_path、params、request_body、responses、tags 字段 |
| `_parse_openapi` 增强 | ✅ 完成 | 提取基础 URL、解析参数为 SdkParam 对象、解析请求体和响应信息 |
| `parse()` 方法增强 | ✅ 完成 | 支持文件路径、URL、JSON 字符串输入 |
| `register_http_tools()` | ✅ 完成 | 将 SdkMethod 转换为 HTTP 类型的 AgentToolSpec 并注册 |
| `_build_http_input_schema()` | ✅ 完成 | 构建 HTTP 工具的 JSON Schema 输入 schema |
| `_build_http_call_impl()` | ✅ 完成 | 构建 HTTP 工具的调用实现配置 |
| `_generate_http_wrapper_script()` | ✅ 完成 | 生成独立的 HTTP wrapper 测试脚本 |
| `convert_sop_to_agent()` 增强 | ✅ 完成 | 调用 register_http_tools() 注册 HTTP 工具，传递 bundle_dir |
| CLI 集成 | ✅ 完成 | sop convert 命令支持 OpenAPI Spec 文件路径输入 |
| HTTP 工具执行器修复 | ✅ 完成 | 修复 execute_http() POST 请求 body 处理问题 |

### 5.2 验收结果

| 编号 | 验收项 | 结果 | 验证方法 |
|------|--------|------|----------|
| OA-1 | OpenAPI 解析参数类型 | ✅ 通过 | 单元测试验证 param_type 字段 |
| OA-2 | OpenAPI 解析请求体 | ✅ 通过 | 单元测试验证 request_body 字段 |
| OA-3 | OpenAPI 解析响应 | ✅ 通过 | 单元测试验证 responses 字段 |
| OA-4 | HTTP Tool 注册 | ✅ 通过 | 单元测试验证生成的 spec 结构 |
| OA-5 | HTTP Tool 类型 | ✅ 通过 | 验证 spec.call_type == "http" |
| OA-6 | HTTP Tool 调用配置 | ✅ 通过 | 验证 spec.call_impl 结构 |
| OA-7 | JSON Schema 输入验证 | ✅ 通过 | 验证 input_schema 结构 |
| OA-8 | HTTP Wrapper 脚本生成 | ✅ 通过 | 验证脚本文件生成 |
| OA-9 | SOP 转换集成 | ✅ 通过 | 集成测试验证转换结果 |
| OA-10 | 完整流程验证 | ✅ 通过 | 端到端测试，使用 Petstore API |

### 5.3 修改的文件

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `extensions/sop_converter/sdk_parser.py` | 修改 | 新增 SdkParam 类，增强 SdkMethod 类，修改 _parse_openapi() 和 parse() 方法 |
| `extensions/sop_converter/tool_registry_bridge.py` | 修改 | 实现 register_http_tools()、_build_http_input_schema()、_build_http_call_impl()、_generate_http_wrapper_script() |
| `extensions/sop_converter/convert_sop_skill.py` | 修改 | 增强 convert_sop_to_agent()，调用 register_http_tools()，传递 bundle_dir |
| `extensions/sop_converter/__init__.py` | 修改 | 导出新增的 SdkParam 类和 register_http_tools() 函数 |
| `clawcodex_ext/cli/sop_cmd/commands.py` | 修改 | 在 _handle_convert() 中传递 bundle_dir 参数 |
| `clawcodex_ext/agent/tool_authoring/call_handlers/http.py` | 修改 | 修复 POST 请求 body 处理问题，使用 params 作为请求体 |

## §6 操作说明

### 6.1 验证流程

#### 步骤 1：准备 OpenAPI Spec

使用已下载的 Petstore Spec：

```bash
ls tests/data/petstore_swagger.json
```

#### 步骤 2：使用 `sop convert` 转换为 Agent Bundle

```bash
cd "d:\projects\clawcodex\.worktrees\SOP-tool4"
clawcodex-dev sop convert tests/data/petstore_swagger.json \
    --out petstore_bundle \
    --requirements "宠物管理系统" \
    --name petstore-agent
```

**预期输出：**

```
✅ Converted SOP: petstore-agent
   Description: Agent for: 宠物管理系统
   Tools: 20
   Skills: 1
     - sdk_utility (upload-file, add-pet, update-pet, find-pets-by-status, ...)
   Agent: .claude/agents/petstore-agent.md
   Skill: .atomcode/skills/sdk_utility/SKILL.md
```

#### 步骤 3：检查生成的文件

```bash
ls petstore_bundle/agent-tools/
# 工具规范文件: get-pet-by-id.json, add-pet.json, ... (20个)
# Wrapper脚本目录: scripts/
```

#### 步骤 4：通过 `--agent` 打开对话

```bash
clawcodex --agent petstore_bundle
```

#### 步骤 5：在对话中验证 Agent 能力

在 REPL/TUI 中输入以下指令来验证：

| 指令 | 验证内容 | 预期结果 |
|------|----------|----------|
| `查询 ID 为 1 的宠物信息` | GET 请求，路径参数 | 返回宠物详细信息 |
| `查询所有可用的宠物` | GET 请求，查询参数 | 返回可用宠物列表 |
| `添加一个新宠物，名称为"测试猫"` | POST 请求，请求体 | 创建成功，返回宠物信息 |
| `更新宠物 ID 为 1 的信息` | PUT 请求 | 更新成功 |

### 6.2 生成的 Bundle 结构

```
petstore_bundle/
├── .claude/
│   └── agents/
│       └── petstore-agent.md      # Agent 定义
├── .atomcode/
│   └── skills/
│       └── sdk_utility/
│           └── SKILL.md           # Skill 定义
├── agent-tools/                    # HTTP 工具规范（关键！）
│   ├── get-pet-by-id.json          # 工具规范
│   ├── add-pet.json
│   ├── ... (共20个)
│   └── scripts/                   # Wrapper 脚本
│       ├── get-pet-by-id.py
│       ├── add-pet.py
│       └── ... (共20个)
├── skills/                         # 旧格式（兼容）
└── workflows/                      # 工作流定义
```

### 6.3 工具规范示例

生成的 `get-pet-by-id.json` 工具规范：

```json
{
  "name": "get-pet-by-id",
  "description": "Find pet by ID",
  "input_schema": {
    "type": "object",
    "properties": {
      "petId": {
        "type": "integer",
        "description": "ID of pet that needs to be fetched"
      }
    },
    "required": ["petId"]
  },
  "call_type": "http",
  "call_impl": {
    "method": "GET",
    "url": "https://petstore.swagger.io/v2/pet/{petId}"
  },
  "tags": ["pet"],
  "source": "agent-created"
}
```

### 6.4 单元测试

运行单元测试验证功能：

```bash
cd "d:\projects\clawcodex\.worktrees\SOP-tool4"
python -m pytest tests/test_swagger_petstore.py -v
```

**预期结果：**

```
7 passed, 1 warning in 11.58s
```

### 6.5 支持的 OpenAPI 格式

| 格式 | 版本 | 支持情况 |
|------|------|----------|
| OpenAPI 3.0 | JSON/YAML | ✅ 支持 |
| Swagger 2.0 | JSON/YAML | ✅ 支持 |

### 6.6 支持的输入方式

| 输入类型 | 示例 |
|----------|------|
| 文件路径 | `tests/data/petstore_swagger.json` |
| URL | `https://petstore.swagger.io/v2/swagger.json` |
| JSON 字符串 | `{"openapi": "3.0.0", ...}` |
| Python dict | 直接传入解析后的 dict |

### 6.7 注意事项

1. **认证处理**：当前实现不包含认证头，如需认证需在 `call_impl` 中添加 `headers` 字段
2. **网络访问**：确保测试环境能访问目标 API
3. **速率限制**：真实 API 可能有调用频率限制，建议使用本地 mock 服务（如 Prism）
4. **数据安全**：避免在测试中使用生产环境数据

## §7 验证指标

| 指标 | 预期值 | 实际值 |
|------|--------|--------|
| 解析的 API 操作数（Petstore） | 20 | ✅ 20 |
| 生成的工具规范数 | 20 | ✅ 20 |
| 生成的 Wrapper 脚本数 | 20 | ✅ 20 |
| 工具类型 | `call_type="http"` | ✅ http |
| 工具规范位置 | `bundle_dir/agent-tools/` | ✅ 正确 |
| 工具名称格式 | kebab-case | ✅ `get-pet-by-id` |
| 参数类型提取 | 完整 | ✅ string/integer/number/boolean |
| 请求体提取 | 完整 | ✅ JSON Schema |
| 响应提取 | 完整 | ✅ 状态码和 schema |
| CLI 转换成功 | 是 | ✅ 成功 |
| 实际 API 调用 | 成功 | ✅ GET/POST/PUT/DELETE 均成功 |