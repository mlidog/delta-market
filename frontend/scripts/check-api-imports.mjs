/**
 * 构建前检查：组件不能绕过 `src/api/index.ts` 直接引用实时客户端。
 *
 * 背景：`api/client.ts` 只会请求本地 FastAPI 后端。GitHub Pages 上没有后端，
 * 直接引用它会让静态站去请求不存在的 `/api/...`。
 * 这个错误在本地开发时完全看不出来（本地 `/api` 是通的），只在部署后才暴露，
 * 所以放在构建流程里挡住。
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../src", import.meta.url));
const ALLOWED = new Set([join(SRC, "api", "index.ts")]);
const PATTERN = /from\s+["'][^"']*["']?\/api\/client["']/;

const offenders = [];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry) || ALLOWED.has(full)) continue;
    const text = readFileSync(full, "utf8");
    text.split("\n").forEach((line, index) => {
      if (line.trimStart().startsWith("*") || line.trimStart().startsWith("//")) return;
      if (PATTERN.test(line)) {
        offenders.push(`${full.replace(SRC, "src")}:${index + 1}  ${line.trim()}`);
      }
    });
  }
}

walk(SRC);

if (offenders.length > 0) {
  console.error("以下文件直接引用了 api/client（应改为从 ../api 引入）：");
  for (const line of offenders) console.error("  " + line);
  process.exit(1);
}
console.log("api 引用检查通过");
