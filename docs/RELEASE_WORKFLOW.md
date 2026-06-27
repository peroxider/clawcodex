# ClawCodex 发布流程 & 安装指南

> 本文档面向两类读者：
> - **维护者（Maintainer）** — 打 tag、跑 CI、发布到 PyPI / GitCode Release
> - **用户（User）** — 安装指定版本 / 最新版本 / main 分支实时版本

---

## 目录

- [1. 版本号方案](#1-版本号方案)
- [2. 维护者：发布流程](#2-维护者发布流程)
  - [2.1 发布前检查清单](#21-发布前检查清单)
  - [2.2 打 Tag 与推送](#22-打-tag-与推送)
  - [2.3 CI 自动发布](#23-ci-自动发布)
  - [2.4 手动发布（workflow_dispatch）](#24-手动发布workflow_dispatch)
  - [2.5 发布后验证](#25-发布后验证)
- [3. 用户安装指南](#3-用户安装指南)
  - [3.1 固定版本（推荐）](#31-固定版本推荐)
  - [3.2 最新版本（Latest）](#32-最新版本latest)
  - [3.3 main 分支实时版本（Edge）](#33-main-分支实时版本edge)
  - [3.4 通过 pip 安装 / 升级](#34-通过-pip-安装--升级)
- [4. 版本号冻结原理](#4-版本号冻结原理)
- [5. 常见问题](#5-常见问题)

---

## 1. 版本号方案

ClawCodex 使用 **CalVer + Tag 冻结** 的双轨版本方案：

| 场景 | 版本格式 | 示例 | 来源 |
|------|---------|------|------|
| 日常开发 | `YYYY.M.D` | `2026.6.25` | `date.today()` |
| 固定 Release | `YYYY.M.D` | `2026.6.24` | `$RELEASE_TAG` 环境变量 |
| Tag 命名 | `vYYYY.M.D` | `v2026.6.24` | Git tag |

关键规则：

```
Tag v2026.6.24  →  CI 设置 RELEASE_TAG=v2026.6.24
                  →  _version.py 返回 "2026.6.24"
                  →  wheel metadata 写入 "2026.6.24"
                  →  一个月后从该 tag 重建，版本仍是 "2026.6.24"
```

> 详细实现见 [`clawcodex_ext/_version.py`](../clawcodex_ext/_version.py) 和 [`scripts/ci/bump_version.py`](../scripts/ci/bump_version.py)。

---

## 2. 维护者：发布流程

### 2.1 发布前检查清单

- [ ] 所有目标 feature 已合并到 `dev-*` 分支
- [ ] 稳定性门禁通过：`python -m pytest tests/stability_gate/ -q --tb=short -x`
- [ ] Orchestrator 单元测试通过：`python -m pytest tests/orchestrator/ --ignore=tests/orchestrator/manual_e2e_f38.py -q`
- [ ] CI 的 `lint` / `test-gate` / `audit` 三个 job 全绿
- [ ] `install.sh` 中的 `INSTALLER_VERSION` / `CLAWCODEX_VERSION` 已更新为当前日期
- [ ] `bump_version.py --apply` 已运行且 `uv.lock` 等静态文件版本一致
- [ ] `pyproject.toml` 中的 dependency 版本已审核
- [ ] CHANGELOG / Release Notes 已撰写

### 2.2 打 Tag 与推送

```bash
# 1. 确保在正确的分支上
git checkout dev

# 2. 创建 tag（日期 = 发布日期，不一定是今天）
RELEASE_DATE="2026.6.24"
git tag -a "v${RELEASE_DATE}" -m "release: clawcodex v${RELEASE_DATE}"

# 3. 推送 tag
git push origin "v${RELEASE_DATE}"
```

推送 tag 后，[`.gitcode/workflows/publish.yml`](../.gitcode/workflows/publish.yml) 会被自动触发：

### 2.3 CI 自动发布

当推送 `v*` 开头的 tag 时，`publish.yml` 自动执行以下流水线：

```
git push tag v2026.6.24
    │
    ▼
publish.yml (push: tags: ["v*"])
    │
    ├── 1. Derive RELEASE_TAG from event context
    │      GITHUB_REF=refs/tags/v2026.6.24 → RELEASE_TAG=v2026.6.24
    │
    ├── 2. Install uv + dependencies
    │
    ├── 3. Bump static version refs
    │      bump_version.py --apply  →  更新 install.sh, install.ps1,
    │                                   uv.lock, test fixtures
    │
    ├── 4. Verify installer version consistency
    │      所有 4 个版本源必须一致：
    │        install.sh    INSTALLER_VERSION = 2026.6.24
    │        install.sh    CLAWCODEX_VERSION = 2026.6.24
    │        install.ps1   InstallerVersion  = 2026.6.24
    │        install.ps1   ClawCodexVersion  = 2026.6.24
    │        __version__                     = 2026.6.24
    │
    ├── 5. Build & verify
    │      python -m build
    │      python -m twine check dist/*
    │
    ├── 6. Publish to Test PyPI
    │      twine upload --repository-url https://test.pypi.org/legacy/
    │
    ├── 7. [可选] Publish to PyPI
    │      (通过 workflow_dispatch 手动触发)
    │
    └── 8. Create GitCode Release
           python scripts/ci/gitcode_release.py \
             --owner Gideon_Zhao \
             --repo clawcodex \
             --tag v2026.6.24
```

### 2.4 手动发布（workflow_dispatch）

如果自动发布失败，或需要发布到正式 PyPI：

1. 在 GitCode 仓库 → Actions → **publish** → **Run workflow**
2. 填写参数：

| 参数 | 说明 | 示例 |
|------|------|------|
| `release_target` | 目标仓库 | `testpypi` 或 `pypi` |
| `tag` | 已推送的 tag | `v2026.6.24` |

### 2.5 发布后验证

```bash
# 验证 PyPI 包
pip install clawcodex-dev-mind==2026.6.24
clawcodex-dev --version

# 验证 install.sh
bash <(curl -fsSL https://gitcode.com/chadwweng/clawcodex/releases/download/v2026.6.24/install.sh) doctor

# 验证 release 页面
open https://gitcode.com/Gideon_Zhao/clawcodex/releases/tag/v2026.6.24
```

---

## 3. 用户安装指南

### 3.1 固定版本（推荐）

安装一个**固定的、经过测试的 release**，依赖锁定，适合生产环境。

#### 方式 A：通过 install.sh（推荐）

```bash
# 下载对应版本的 install.sh
curl -fsSL -o install.sh \
  "https://gitcode.com/chadwweng/clawcodex/releases/download/v2026.6.24/install.sh"

# 运行安装
bash install.sh
```

`install.sh` 会：
1. 克隆 tag `v2026.6.24` 的代码
2. 安装锁定的依赖（`uv.lock` 与 release 匹配）
3. 注册全局命令 `clawcodex-dev`

> `install.sh` 中的 `CLAWCODEX_VERSION` 和 `REPO_REF` 与 release 严格绑定，不会安装不同版本的代码。

#### 方式 B：通过 pip

```bash
pip install clawcodex-dev-mind==2026.6.24
```

#### 方式 C：手动 clone + install

```bash
git clone --depth 1 --branch v2026.6.24 \
  https://gitcode.com/chadwweng/clawcodex.git

cd clawcodex
pip install -e ".[all]"
```

### 3.2 最新版本（Latest）

安装**最新的正式 release**，适合希望保持更新但仍使用稳定版本的用户。

#### 方式 A：install.sh（从 main 分支获取）

```bash
# 从 main 分支获取最新版的 install.sh
# （install.sh 始终指向该版本对应的 tag）
git clone --depth 1 https://gitcode.com/chadwweng/clawcodex /tmp/clawcodex
bash /tmp/clawcodex/install.sh
```

`install.sh` 中的 `REPO_REF` 会自动尝试匹配 `CLAWCODEX_VERSION` 对应的 tag。如果该 tag 在远程存在，安装的就是固定 release；如果不存在（如开发阶段），会 fallback 到默认分支并给出警告。

#### 方式 B：pip（latest）

```bash
pip install clawcodex-dev-mind
```

#### 方式 C：通过 `--ref` 指定 tag

```bash
# 先查看有哪些 release tag
git ls-remote --tags https://gitcode.com/chadwweng/clawcodex | grep 'v20'

# 安装指定的 tag
git clone --depth 1 --branch v2026.6.24 \
  https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex
pip install -e ".[all]"
```

### 3.3 main 分支实时版本（Edge）

安装 **main 分支最新代码**，适合开发者、贡献者或需要最新功能的用户。

> ⚠️ **Edge 版本依赖锁不保证与 main 分支同步**，`uv.lock` 可能落后于 `pyproject.toml` 的依赖声明。如果遇到依赖冲突，运行 `uv sync --upgrade` 或 `pip install -e ".[all]"` 会重新解析。

```bash
git clone --depth 1 https://gitcode.com/chadwweng/clawcodex.git
cd clawcodex
pip install -e ".[all]"
clawcodex-dev --version
# 输出: 2026.6.25  ← 安装当天的日期
```

Edge 版本的版本号为**安装当天的日期**，版本更新说明：

- 版本 `2026.6.24`（发布版）和版本 `2026.6.25`（Edge）**没有大小关系**——CalVer 版本号只反映日期，不反映语义版本（SemVer）的向前兼容性。
- Edge 版本可能包含未测试的变更，建议用 `pip install -e ".[dev]"` 安装后运行稳定性门禁验证。

#### Edge 升级

```bash
cd clawcodex
git pull origin main
pip install -e ".[all]"
clawcodex-dev --version   # 版本变为 pull 当天的日期
```

### 3.4 通过 pip 安装 / 升级

| 操作 | 命令 |
|------|------|
| 安装固定版本 | `pip install clawcodex-dev-mind==2026.6.24` |
| 安装最新版本 | `pip install clawcodex-dev-mind` |
| 升级到最新 | `pip install --upgrade clawcodex-dev-mind` |
| 从源码安装（editable） | `pip install -e ".[all]"` |
| 查看已安装版本 | `pip show clawcodex-dev-mind` |
| 查看运行时版本 | `clawcodex-dev --version` |
| 卸载 | `pip uninstall clawcodex-dev-mind` |

---

## 4. 版本号冻结原理

```
                          日常开发
                     ┌────────────────────┐
                     │  _version.py        │
                     │  __version__        │
                     │  = date.today()     │
                     │  → "2026.6.25"      │
                     └────────┬───────────┘
                              │
                              │  pip install -e ".[all]"
                              │  python -c "import ...; print(__version__)"
                              ▼
                     "2026.6.25"  (每天自动变化)
```

```
                           发布流程 (CI)
                     ┌────────────────────┐
                     │  CI 设置             │
                     │  RELEASE_TAG         │
                     │  = v2026.6.24       │
                     └────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
 ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
 │ _version.py     │ │ bump_version.py │ │ python -m build │
 │ RELEASE_TAG     │ │ calver()        │ │ __version__     │
 │ 有值 →          │ │ 有值 →          │ │ 进入 wheel      │
 │ "2026.6.24"     │ │ "2026.6.24"     │ │ metadata        │
 └─────────────────┘ └─────────────────┘ └─────────────────┘
```

**发布后的版本不变性**：

```python
# 2026年6月24日，CI 发布 v2026.6.24
# 2026年7月1日，用户从 PyPI 下载 wheel

# wheel 中的 METADATA 已写入：
# Version: 2026.6.24  ← 永远不变
```

```python
# 如果2026年7月1日签出 tag v2026.6.24 并用 pip install -e . 安装：
# _version.py 被重新执行，此时 $RELEASE_TAG 未设置
# __version__ = "2026.7.1"  ← 日常开发用日期

# 但 pip install -e . 通常用于开发而非生产，
# 生产环境应使用：pip install clawcodex-dev-mind==2026.6.24
```

---

## 5. 常见问题

### Q: 为什么不用 SemVer（语义化版本）？

CalVer 更符合 AI 项目的发布节奏——每天可能有多个增量发布，SemVer 无法有效区分。同时，CalVer 让用户直观知晓包的"新鲜度"。

### Q: 为什么 Edge 版本日期可能比发布版"更早"？

CalVer `2026.6.25`（Edge）并不比 `2026.6.24`（发布版）版本更高——它们只是日期戳。没有语义版本的大于/小于关系。建议用户在 Edge 环境中运行测试后再使用。

### Q: `install.sh` 安装后如何升级？

```bash
# 升级到最新的正式 release：
cd ~/.clawcodex/clawcodex
git fetch --tags
git checkout v2026.7.1
uv sync --extra all

# 或直接重新跑 install.sh update：
bash ~/.clawcodex/clawcodex/install.sh update
```

### Q: 如何确认当前安装的版本是固定 release 还是 Edge？

```bash
clawcodex-dev --version
# 输出: 2026.6.24 ← 固定 release
# 输出: 2026.6.25 ← Edge（日期 != 任何 release tag 的日期）

# 检查 git ref：
cd ~/.clawcodex/clawcodex
git describe --tags --exact-match 2>/dev/null || echo "no tag (edge)"
```

### Q: 发布后发现严重 bug 怎么办？

1. 修复代码并推送到 main 分支
2. 创建补丁 tag：`git tag v2026.6.24.1`
3. 手动触发 `publish.yml` → `workflow_dispatch`
4. 在 release 页面对旧版本标记为 **deprecated**

### Q: `bump_version.py` 的作用是什么？

`bump_version.py` 更新那些**不能动态读取** `_version.py` 的静态文件：

| 文件 | 原因 |
|------|------|
| `install.sh` | shell 脚本，环境变量可读 |
| `install.ps1` | PowerShell 安装脚本 |
| `uv.lock` | 锁文件需固定版本号 |
| 测试 fixture | 硬编码版本断言的测试文件 |

在 CI 发布流程中，`bump_version.py` 通过 `$RELEASE_TAG` 环境变量获取 tag 版本，确保静态文件与运行时版本**严格一致**。
