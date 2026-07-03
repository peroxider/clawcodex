#!/usr/bin/env node
// scripts/build.js — WSL/npm 兼容的 build wrapper
//
// 问题:npm run / npx 在 WSL/Windows 桥接环境下调用子进程时
// 会把 stdin 重新 attach 到 tty,导致 vite build 静默挂住。
// 直接调 vite 二进制没问题(node_modules/.bin/vite build)。
//
// 这个 wrapper 跳过 npm script 链,用 execSync 显式喂空 stdin
// (`input: ''`),保留 tsc 类型检查 + vite 单文件构建 + copy 三步。

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const VITE = path.join(ROOT, "node_modules", ".bin", "vite");
const TSC = path.join(ROOT, "node_modules", ".bin", "tsc");

console.log("Step 1: tsc typecheck");
execSync(`${TSC} --noEmit`, { stdio: "inherit", cwd: ROOT });

console.log("Step 2: vite build (single-file)");
execSync(`${VITE} build`, { stdio: "inherit", cwd: ROOT, input: "" });

console.log("Step 3: copy to article/article.html");
fs.mkdirSync(path.join(ROOT, "article"), { recursive: true });
const src = path.join(ROOT, "dist", "index.html");
const dst = path.join(ROOT, "article", "article.html");
fs.copyFileSync(src, dst);
const sz = fs.statSync(dst).size;
console.log(`built ${path.relative(ROOT, dst)} (${(sz / 1024).toFixed(1)} KB)`);