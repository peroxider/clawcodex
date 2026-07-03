# Repair Log — Phase 7

修复对象:`assets/release-article/` (Beautiful Article skill · C)

修复日期:2026-07-01

修复原则:最小切片 —— 只修 Technical Review 标记的 must-fix 项,不动其它已通过内容。

---

## 修复 1 · `npm run build` 静默失败 (Critical)

**问题症状**

- `npm run build` 与 `npx vite build` 均退出码 0,但无任何 stdout,`dist/index.html` 不生成
- `final-review.md` Technical Review 标记为 must-fix,要求修通前禁止发布
- Reviewer 给的 5 步排查顺序:①关 emptyOutDir;②升级/移除 vite-plugin-singlefile;③显式 assetsInlineLimit + cssCodeSplit:false;④切 WSL ext4 路径;⑤build.minify:false

**根因诊断(跳过 review 的 5 步)**

直接调 `./node_modules/.bin/vite build < /dev/null` 成功(2.38s,产出 1.99MB 单文件),确认 vite 与 vite-plugin-singlefile 均正常。问题在 `npm` / `npx` 调用子进程时,WSL/Windows 桥接下 stdin 被重新 attach 到 tty,导致 vite 静默挂住不退出。

- `npm run build` → 子进程 stdin 被 attach tty → vite 静默
- `npx vite build` → 同样的 stdin/tty 问题
- `./node_modules/.bin/vite build < /dev/null` → 直接给 vite 空 stdin → 正常

**修复方案**

新增 `scripts/build.js` Node wrapper:
- 显式用 `execSync` 调 vite,传 `{ input: "" }` 喂空 stdin
- 三步串联:tsc 类型检查 → vite 单文件构建 → copy dist/index.html 到 article/article.html
- `package.json` 的 `build` / `html` 脚本改为 `node scripts/build.js`(单步到位,无需 `&&` 串联)

```diff
-    "build": "tsc --noEmit && vite build",
-    "html": "npm run build && node -e \"...\""
+    "build": "node scripts/build.js",
+    "html": "npm run build"
```

**验证结果**

```
$ npm run build
> node scripts/build.js
Step 1: tsc typecheck
Step 2: vite build (single-file)
vite v5.4.21 building for production...
✓ 39 modules transformed.
[plugin vite:singlefile] Inlining: index-kkRYE9tM.js
[plugin vite:singlefile] Inlining: style-BYZzXzcC.css
dist/index.html  1,991.51 kB │ gzip: 1,095.29 kB
✓ built in 2.34s
Step 3: copy to article/article.html
built article/article.html (1952.0 KB)

$ ls -la article/article.html
-rwxrwxrwx 1 chad chad 1998898 Jul  1 21:58 article/article.html
```

`article/article.html` 已生成,2.0 MB,断网可打开(reacticle 全部内联)。

---

## 修复 2 · Orphan 模板文件清理 (Important)

**问题症状**

- `article/sections/01-opening.tsx` 是 scaffold 创建的示例文件,从未被 `Article.tsx` import
- 与 `01-orchestrator.tsx` 同号 `index="01"`,污染 sections 目录

**修复方案**

```bash
rm article/sections/01-opening.tsx
```

**验证结果**

```
$ ls article/sections/
01-orchestrator.tsx  02-sop-compiler.tsx  03-aux-capabilities.tsx
04-decoupling.tsx    05-install.tsx       06-limits-meta.tsx
```

正好 6 个有效 Section 文件。

---

## 顺手小修 · 表格列名语义化 (Tech Review 建议,非 fail)

**改动**

`article/sections/01-orchestrator.tsx` 的 4 跟踪器表格,列名 `适配器` → `跟踪器`(与正文"支持的 issue 跟踪器"一致)。

---

## 未改动项 · 解释

| Reviewer 建议 | 状态 | 理由 |
|---|---|---|
| Visual: Cover 副标题与 Hero 副标题文字相似 | 未改 | review 自评 "not counting as fail";两处用词确实接近但语义不同(Cover 强调"升级",Hero 强调"下游 fork"),不构成硬冲突 |
| Tech: §02 "YAML/JSON" 推断 | 未改 | 该描述是 §02 的实际产品输出说明,不是误传;review 标为低优先级建议 |

---

## 修复后产物

- `article/article.html` (1.95 MB,自包含单页,tufte theme)
- `article/sections/01-orchestrator.tsx` 列名修正
- `scripts/build.js` 新增(Node wrapper,绕过 WSL stdin/tty 问题)
- `package.json` `build` / `html` 脚本更新
- `article/sections/01-opening.tsx` 删除