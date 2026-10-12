/**
 * API 入口：按构建参数在「本地后端」与「静态 JSON」之间切换。
 *
 * - `VITE_STATIC=true`（GitHub Pages 构建）：读 `data/*.json`，没有写操作
 * - 否则：请求本地 FastAPI 后端
 */

import { api as liveApi } from "./client";
import { staticApi } from "./staticClient";

export const IS_STATIC = import.meta.env.VITE_STATIC === "true";

export const api = IS_STATIC ? staticApi : liveApi;
