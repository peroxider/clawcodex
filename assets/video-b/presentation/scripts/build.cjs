#!/usr/bin/env node
// scripts/build.js —— 单文件离线构建 wrapper
//
// 设计要点:
// 1. 跳过 `tsc -b`(presentation 包未装 @types/node,scripts/extract-narrations.ts
//    引用 node:fs 会失败;vite build 自身不依赖 tsc 类型检查)。
// 2. 直接调 vite 二进制,显式喂空 stdin(绕过 WSL 下 npm wrapper 重新 attach tty
//    导致 vite 静默挂住的 bug,与 release-article/scripts/build.js 一致)。
// 3. vite-plugin-singlefile + base:"./" 让产物是单文件 HTML 且能 file:// 打开。
// 4. 产物不放 dist/(根 .gitignore 屏蔽 dist/),而放 article.html(与 release-article
//    产物 article/article.html 命名对称,便于 file:// 双击)。

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const VITE = path.join(ROOT, "node_modules", ".bin", "vite");

console.log("Step 1: vite single-file build");
execSync(`${VITE} build`, { stdio: "inherit", cwd: ROOT, input: "" });

console.log("Step 2: copy dist/index.html -> article.html");
const src = path.join(ROOT, "dist", "index.html");
const dst = path.join(ROOT, "article.html");
fs.copyFileSync(src, dst);
const sz = fs.statSync(dst).size;
console.log(`built ${path.relative(ROOT, dst)} (${(sz / 1024).toFixed(1)} KB)`);