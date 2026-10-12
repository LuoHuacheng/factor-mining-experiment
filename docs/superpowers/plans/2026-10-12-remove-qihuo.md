# 彻底移除 Qihuo 命名与残留资产 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底剥离与重构项目中全部 233 处 `qihuo` 引用与期货残留组件：标准化后端 Logger、通用化工程元数据与 API Key 前缀、重构前端持久化键、彻底删除 Docker Compose 中废弃的期货桥容器（CTP/Sina/VVTR），并无损重命名基础服务与存储卷映射，最终交付 100% 无 `qihuo` 痕迹的纯净系统。

**Architecture:** 
1. **分层脱敏与标准化**：日志层回归 Python 标准 `logging.getLogger(__name__)` 与根命名空间 `app`；API Key 采用 `ak_` 通用前缀并向下兼容旧 Key；前端持久化去掉 `qihuo_` 冗余前缀并加一层存量 fallback 读取。
2. **编排精简与安全重构**：直接裁剪已废弃的 4 个国内期货桥容器；将 `qihuo-backend` / `qihuo-frontend` / `qihuo-redis` / `qihuo-postgres` 收敛为标准容器名；Docker Volume 显式声明外部映射 `name: qihuo-postgres-data`，实现配置去 `qihuo` 化且绝对零数据丢失。
3. **门禁防护**：新增全仓 `test_no_qihuo_residue.py` 自动化测试，作为终验门禁。

**Tech Stack:** Python 3.12 / FastAPI / pytest / uv / TypeScript / Next.js 15 / Docker Compose

**Spec:** 前置勘察结论见对话记录（233 处出现点分类、7 大风险评估）；OKX 演进主基线见 `docs/superpowers/plans/2026-10-12-okx-crypto-only.md`。

## Global Constraints

- Python `>=3.12`，Node.js `>=20`
- 不新增任何 Python 或 Node 第三方依赖
- 数据库现有数据（Postgres 卷与表数据）必须保持 100% 完整，禁止删卷重建
- Git 提交信息格式固定：`<type>(<scope>): 中文描述`，不使用 emoji
- 测试命令统一：`cd backend && uv run pytest <path> -v`
- 前端校验命令统一：`cd frontend && pnpm build` 或 `pnpm lint`

---

## File Structure

```
backend/
├── pyproject.toml                             # 模块包名重构 (qihuo-backend -> backend)
├── uv.lock                                    # 锁文件同步
├── app/
│   ├── core/
│   │   ├── config.py                          # 剥离 qihuo_sim / qihuo_oc 等期货配置
│   │   └── logger.py                          # 根 Logger 重构 (qihuo -> app)
│   ├── main.py                                # 清除迁移中的 qihuo_sim 兜底
│   ├── models/system_settings.py              # 清理 ctp_sim_investor_id 默认值
│   ├── schemas/admin.py                       # 清理管理端期货模拟账号 schema
│   ├── services/
│   │   ├── admin_overview.py                  # 监控容器名单更新 (_WATCH_CONTAINERS)
│   │   ├── api_key_svc.py                     # API Key 前缀升级为 ak_，兼容校验
│   │   ├── channel_failover.py                # 移除 qihuo-ctp-bridge 依赖
│   │   ├── market_channel.py                  # 清除 sina/ctp 桥容器键引用
│   │   ├── market_health.py                   # 移除桥容器异常提示
│   │   └── system_settings_svc.py             # 清除 qihuo_sim 兜底逻辑
│   └── (80+ 业务文件)                          # logger = logging.getLogger("qihuo.*") -> __name__
tests/
├── test_api_key_clean.py                      # API Key 前缀与向下兼容测试
├── test_logger_clean.py                       # Logger 结构与命名空间测试
└── test_no_qihuo_residue.py                   # 终验全仓无 qihuo 门禁测试

frontend/
├── package.json                               # 包名重构 (qihuo-frontend -> frontend)
├── Dockerfile                                 # 内网反代地址更新 (qihuo-backend -> backend)
├── next.config.ts                             # 默认 BACKEND_URL 更新
├── src/
│   ├── app/
│   │   ├── (auth)/login/page.tsx              # 登录 remember/user/pass 键名通用化
│   │   ├── (main)/market/page.tsx             # 布局偏好键名通用化
│   │   ├── admin/dashboard/page.tsx           # 移除 qihuo- 前缀截断
│   │   ├── admin/settings/page.tsx            # 清除 qihuo_sim 表单默认值
│   │   ├── api/backtest/*/route.ts            # 反代 URL 更新为 http://backend:8001
│   │   ├── api/factor-lab/[...path]/route.ts  # 反代 URL 更新为 http://backend:8001
│   │   └── layout.tsx                         # 字体脚本键名通用化
│   ├── components/
│   │   ├── landing/auth/auth-login-form.tsx   # 登录持久化键名通用化
│   │   └── market/kline/drawing/              # 画线图层与样式类名通用化
│   ├── hooks/sync.ts                          # BroadcastChannel 名称更新
│   ├── lib/
│   │   ├── ai-anchor-persist.ts               # AI 主播持久化键名通用化
│   │   ├── font-size.ts                       # 字号键名通用化
│   │   └── kline-colors.ts                    # K线颜色配置键名通用化
│   └── stores/                                # app.ts, auth.ts, indicator.ts 等键名通用化

docker-compose.yml                             # 彻底剔除期货桥服务，容器/网络通用化
docker-compose.local.yml                       # 本地开发编排同步更新
```

---

### Task 1: 标准化工程元数据（包名与锁文件）

**Files:**
- Modify: `backend/pyproject.toml:1-5`
- Modify: `backend/uv.lock`
- Modify: `frontend/package.json:1-5`

**Interfaces:**
- Consumes: 无
- Produces: 规范包名 `backend` 与 `frontend`

- [ ] **Step 1: 修改后端 `pyproject.toml`**

在 `backend/pyproject.toml` 中将 `name = "qihuo-backend"` 修改为 `name = "backend"`：

```toml
[project]
name = "backend"
version = "0.1.0"
description = "Factor Mining Experiment Platform"
readme = "README.md"
requires-python = ">=3.12"
```

- [ ] **Step 2: 重新生成 `uv.lock`**

运行：
```bash
cd backend && uv lock
```
Expected: `uv.lock` 成功更新，包名解析为 `backend`。

- [ ] **Step 3: 修改前端 `package.json`**

在 `frontend/package.json` 中将 `"name": "qihuo-frontend"` 修改为 `"name": "frontend"`：

```json
{
  "name": "frontend",
  "version": "0.1.0",
  "private": true
}
```

- [ ] **Step 4: 运行基本测试验证包完整性**

运行：
```bash
cd backend && uv run pytest tests/test_import_clean.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock frontend/package.json
git commit -m "chore(repo): 标准化前后端包名为 backend 与 frontend"
```

---

### Task 2: 标准化后端 Logger 架构

**Files:**
- Modify: `backend/app/core/logger.py`
- Modify: `backend/app/` 下 82 处 `logging.getLogger("qihuo.*")`
- Test: `backend/tests/test_logger_clean.py`

**Interfaces:**
- Consumes: 无
- Produces: 根 Logger `app`，各子模块统一使用 `logging.getLogger(__name__)` 或 `logging.getLogger("app.<subsystem>")`

- [ ] **Step 1: 编写 Logger 单元测试**

新建 `backend/tests/test_logger_clean.py`：

```python
import logging
from app.core.logger import setup_logger


def test_setup_logger_root_name():
    logger = setup_logger("INFO")
    assert logger.name == "app"
    assert logger.level == logging.INFO


def test_no_qihuo_logger_created():
    # 确保当前活动 loggers 中无 qihuo 遗留
    manager = logging.Logger.manager
    for name in manager.loggerDict:
        assert not name.startswith("qihuo"), f"发现旧 logger 命名: {name}"
```

- [ ] **Step 2: 运行测试验证失败**

运行：
```bash
cd backend && uv run pytest tests/test_logger_clean.py -v
```
Expected: FAIL（因 `setup_logger` 仍返回 `"qihuo"`）

- [ ] **Step 3: 修改 `backend/app/core/logger.py`**

将第 11 行 `logger = logging.getLogger("qihuo")` 改为 `logger = logging.getLogger("app")`：

```python
def setup_logger(log_level: str = "INFO") -> logging.Logger:
    """配置并返回应用日志器"""
    logger = logging.getLogger("app")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if logger.handlers:
        return logger
```

- [ ] **Step 4: 全局替换业务代码中的 `qihuo.` logger**

使用 Python 脚本批量将 `logging.getLogger("qihuo.` 替换为 `logging.getLogger("app.`：

```bash
python3 -c '
import pathlib
root = pathlib.Path("backend/app")
for p in root.rglob("*.py"):
    txt = p.read_text(encoding="utf-8")
    if "logging.getLogger(\"qihuo." in txt or "logging.getLogger(\"qihuo\")" in txt:
        new_txt = txt.replace("logging.getLogger(\"qihuo.", "logging.getLogger(\"app.").replace("logging.getLogger(\"qihuo\")", "logging.getLogger(\"app\")")
        p.write_text(new_txt, encoding="utf-8")
'
```

- [ ] **Step 5: 验证测试通过**

运行：
```bash
cd backend && uv run pytest tests/test_logger_clean.py tests/test_import_clean.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ backend/tests/test_logger_clean.py
git commit -m "refactor(logger): 根日志器由 qihuo 迁移为 app 命名空间"
```

---

### Task 3: 通用化 API Key 前缀与向下兼容验证

**Files:**
- Modify: `backend/app/services/api_key_svc.py`
- Test: `backend/tests/test_api_key_clean.py`

**Interfaces:**
- Consumes: `ApiKey` model
- Produces: `_KEY_PREFIX = "ak_"`, `generate_raw_key()`, `authenticate()`

- [ ] **Step 1: 编写 API Key 测试**

新建 `backend/tests/test_api_key_clean.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.api_key_svc import (
    generate_raw_key,
    hash_key,
    authenticate,
    _prefix_of,
    _KEY_PREFIX,
)
from app.models.api_key import ApiKey


def test_new_key_prefix():
    key = generate_raw_key()
    assert key.startswith("ak_")
    assert not key.startswith("qihuo_")
    assert _prefix_of(key).startswith("ak_")


@pytest.mark.asyncio
async def test_authenticate_supports_legacy_and_new_keys():
    # 测试历史以 qihuo_ 开头的 key 依然能通过 hash 校验
    legacy_key = "qihuo_mock_test_token_12345678"
    legacy_hash = hash_key(legacy_key)

    mock_record = MagicMock(spec=ApiKey)
    mock_record.key_hash = legacy_hash
    mock_record.is_active = True

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = mock_record
    session.execute.return_value = exec_result

    # 验证历史 key 认证通过
    auth_result = await authenticate(session, legacy_key)
    assert auth_result is not None
    assert mock_record.last_used_at is not None

    # 验证新 ak_ key 同样认证通过
    new_key = generate_raw_key()
    mock_record.key_hash = hash_key(new_key)
    auth_result_new = await authenticate(session, new_key)
    assert auth_result_new is not None
```

- [ ] **Step 2: 运行测试验证失败**

运行：
```bash
cd backend && uv run pytest tests/test_api_key_clean.py -v
```
Expected: FAIL（因 `_KEY_PREFIX` 仍为 `"qihuo_"`）

- [ ] **Step 3: 修改 `backend/app/services/api_key_svc.py`**

将第 18 行 `_KEY_PREFIX = "qihuo_"` 替换为 `_KEY_PREFIX = "ak_"`，并更新注释：

```python
_KEY_PREFIX = "ak_"
# 明文前缀长度：存 key_prefix 用于列表掩码展示（前缀 + ****）
_PREFIX_LEN = 12


def _now() -> datetime:
    return datetime.utcnow()


def generate_raw_key() -> str:
    """生成新 key 明文：ak_<urlsafe token>"""
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"
```

- [ ] **Step 4: 运行测试验证通过**

运行：
```bash
cd backend && uv run pytest tests/test_api_key_clean.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/api_key_svc.py backend/tests/test_api_key_clean.py
git commit -m "refactor(auth): API Key 前缀升级为通用 ak_ 格式并兼容旧 Key 认证"
```

---

### Task 4: 前端存储键与广播频道通用化（含存量 Fallback）

**Files:**
- Modify: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/stores/app.ts`
- Modify: `frontend/src/hooks/sync.ts`
- Modify: `frontend/src/lib/font-size.ts`
- Modify: `frontend/src/lib/ai-anchor-persist.ts`
- Modify: `frontend/src/lib/kline-colors.ts`
- Modify: `frontend/src/components/market/kline/drawing/draw-types.ts`
- Modify: `frontend/src/components/market/kline/drawing/use-drawing-overlay.ts`
- Modify: `frontend/src/components/market/kline/use-kline-history.ts`
- Modify: `frontend/src/stores/task-alert.ts`
- Modify: `frontend/src/stores/big-order.ts`
- Modify: `frontend/src/stores/indicator.ts`
- Modify: `frontend/src/stores/ai-market-indicator.ts`
- Modify: `frontend/src/stores/backtest-indicator.ts`
- Modify: `frontend/src/stores/market-pane-indicator.ts`
- Modify: `frontend/src/stores/voice-broadcast.ts`
- Modify: `frontend/src/app/(auth)/login/page.tsx`
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/components/landing/auth/auth-login-form.tsx`
- Modify: `frontend/src/components/screener/screener-workspace.tsx`

**Interfaces:**
- Consumes: 浏览器 LocalStorage, BroadcastChannel
- Produces: 通用存储键（无 `qihuo`），保证向后兼容

- [ ] **Step 1: 修改关键 Store 键名并加入旧键回退**

在 `frontend/src/stores/auth.ts`:
```typescript
// 优先读新 key "app_auth_user"，兼容旧 key "qihuo_auth_user"
const USER_KEY = "app_auth_user";
const LEGACY_USER_KEY = "qihuo_auth_user";

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY) || localStorage.getItem(LEGACY_USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
```

在 `frontend/src/stores/app.ts`:
```typescript
export const ACTIVE_CONTRACT_KEY = "app_active_symbol";
export const MARKET_VIEW_CONTRACT_KEY = "app_market_view_symbol";
```

在 `frontend/src/hooks/sync.ts`:
```typescript
const channel = new BroadcastChannel("app-sync");
```

- [ ] **Step 2: 批量替换前端其它 LocalStorage 键名**

对剩余的静态常量进行重构，将 `qihuo-` / `qihuo_` 替换为 `app-` / `app_`：
- `FONT_SIZE_STORAGE_KEY = "app_font_size"` (及 `frontend/src/app/layout.tsx` 启动脚本)
- `DRAWING_STORAGE_KEY = "app_drawings"`
- `CANVAS_CLASS = "app-drawing-overlay"`
- `DRAFT_KEY = "app-ai-anchor-draft"`
- `VOICE_KEY = "app-ai-anchor-voice"`
- `VOICE_URI_KEY = "app-ai-anchor-voice-uri"`
- `VOICE_RATE_KEY = "app-ai-anchor-voice-rate"`
- `STORAGE_KEY = "app.kline-history.v1"`
- `CONFIG_KEY = "app-market-screener-config"`
- 登录记住账密：`REMEMBER_KEY = "app_login_remember"`, `SAVED_USER_KEY = "app_login_username"`, `SAVED_PASS_KEY = "app_login_password"`

- [ ] **Step 3: 运行前端检查**

运行：
```bash
cd frontend && pnpm lint
```
Expected: PASS（无类型错误或断链）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "refactor(frontend): 本地持久化键与广播频道通用化为 app 命名空间"
```

---

### Task 5: 剥离 Docker Compose 期货桥服务与安全重命名

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.local.yml`
- Modify: `frontend/Dockerfile`
- Modify: `frontend/next.config.ts`
- Modify: `frontend/src/app/api/backtest/*/route.ts`
- Modify: `frontend/src/app/api/factor-lab/[...path]/route.ts`
- Modify: `backend/app/services/admin_overview.py`
- Modify: `frontend/src/app/admin/dashboard/page.tsx`

**Interfaces:**
- Consumes: Docker engine, Compose spec
- Produces: 极简纯净的 compose 编排，内网域名 `http://backend:8001`，无缝挂载旧数据卷

- [ ] **Step 1: 清理 `docker-compose.yml` 中的期货服务**

从 `docker-compose.yml` 中：
1. 删除 `ctp-bridge`、`sina-bridge`、`vvtr-relay`、`ctp-bridge-virtual` 四个废弃 service。
2. 基础容器名重构：
   - `container_name: redis`（原 `qihuo-redis`）
   - `container_name: backend`（原 `qihuo-backend`）
   - `container_name: frontend`（原 `qihuo-frontend`）
3. 网络更名：`networks: [app-net]`（原 `qihuo-net`）。
4. 数据卷保留安全映射：
```yaml
volumes:
  redis-data:
    name: qihuo-redis-data # 挂载已有卷，零数据丢失
```

- [ ] **Step 2: 更新前端代理内网域名**

将前端所有硬编码 `http://qihuo-backend:8001` 更新为 `http://backend:8001`：
- `frontend/Dockerfile`:
  ```dockerfile
  ENV BACKEND_URL=http://backend:8001
  ```
- `frontend/next.config.ts`:
  ```typescript
  const backendUrl = process.env.BACKEND_URL ?? "http://backend:8001";
  ```
- `frontend/src/app/api/backtest/finish/route.ts`
- `frontend/src/app/api/backtest/run/route.ts`
- `frontend/src/app/api/backtest/step/route.ts`
- `frontend/src/app/api/backtest/generate-kline/route.ts`
- `frontend/src/app/api/factor-lab/[...path]/route.ts`

- [ ] **Step 3: 更新服务监控组件**

在 `backend/app/services/admin_overview.py`：
```python
_WATCH_CONTAINERS = (
    "backend",
    "frontend",
)
```

在 `frontend/src/app/admin/dashboard/page.tsx`：
移除 `const short = name.replace("qihuo-", "")`，直接显示 `name`：
```typescript
const short = name;
```

- [ ] **Step 4: 校验 Compose 配置合法性**

运行：
```bash
docker compose config > /dev/null
```
Expected: 返回 0，无语法错误。

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.local.yml frontend/Dockerfile frontend/next.config.ts frontend/src/ backend/app/services/admin_overview.py
git commit -m "chore(deploy): 剔除废弃期货容器，服务与网络命名收敛为通用名"
```

---

### Task 6: 剥离后端遗留 CTP/Sina 渠道配置与默认值

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/models/system_settings.py`
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/services/system_settings_svc.py`
- Modify: `backend/app/services/market_channel.py`
- Modify: `backend/app/services/channel_failover.py`
- Modify: `backend/app/services/market_health.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/src/app/admin/settings/page.tsx`
- Modify: `frontend/src/app/admin/channels/page.tsx`

**Interfaces:**
- Consumes: `system_settings`
- Produces: 彻底移除 `qihuo_sim`、`qihuo_oc`、`qihuo_real` 默认参数，渠道系统适配纯净状态

- [ ] **Step 1: 清理 `config.py` 中的 CTP 产品标识默认值**

在 `backend/app/core/config.py` 中移除或将默认值改为空字符串：
- `openctp_user_product_info: str = ""`
- `real_ctp_user_product_info: str = ""`
- `ctp_sim_investor_id: str = ""`
- `ctp_sim_user_product_info: str = ""`

- [ ] **Step 2: 清理模型与初始化迁移中的 `qihuo_sim`**

在 `backend/app/models/system_settings.py`：
```python
ctp_sim_investor_id: Mapped[str] = mapped_column(
    String(64),
    default="",
    server_default="",
    comment="CTP 模拟账号",
)
```
在 `backend/app/main.py`：
将启动迁移中关于 `ctp_sim_investor_id` 的 `NOT NULL DEFAULT 'qihuo_sim'` 改为 `NOT NULL DEFAULT ''`。

- [ ] **Step 3: 清理管理端 Schema 与 Service**

在 `backend/app/schemas/admin.py`、`backend/app/services/system_settings_svc.py`、`frontend/src/app/admin/settings/page.tsx`、`frontend/src/app/admin/channels/page.tsx` 中移除 `"qihuo_sim"` 兜底，全部以空字符串 `""` 替代。

- [ ] **Step 4: 清理 `market_channel.py`、`channel_failover.py`、`market_health.py`**

移除代码中对 `qihuo-ctp-bridge`、`qihuo-sina-bridge` 的容器名硬编码引用与提示文案。

- [ ] **Step 5: 运行后端测试**

运行：
```bash
cd backend && uv run pytest tests/test_system_settings.py tests/test_admin_api.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ frontend/src/app/admin/
git commit -m "refactor(settings): 剥离 CTP 与新浪桥遗留默认参数 qihuo_sim"
```

---

### Task 7: 建立终验无残留门禁测试与全量回归

**Files:**
- Create: `backend/tests/test_no_qihuo_residue.py`

**Interfaces:**
- Consumes: 整个项目文件树
- Produces: 自动化门禁测试，保证无 `qihuo` 倒流

- [ ] **Step 1: 编写全仓无 `qihuo` 门禁测试**

新建 `backend/tests/test_no_qihuo_residue.py`：

```python
import subprocess
from pathlib import Path

# 允许出现 qihuo 的文件白名单（仅限本迁移计划与历史归档计划）
WHITELIST_FILES = {
    "docs/superpowers/plans/2026-10-12-okx-crypto-only.md",
    "docs/superpowers/plans/2026-10-12-remove-qihuo.md",
}


def test_no_qihuo_residue_in_codebase():
    repo_root = Path(__file__).resolve().parents[2]
    cmd = ["git", "grep", "-i", "-n", "qihuo"]
    res = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)

    lines = [line for line in res.stdout.splitlines() if line.strip()]
    violations = []
    for line in lines:
        file_path = line.split(":", 1)[0]
        if file_path not in WHITELIST_FILES:
            violations.append(line)

    assert not violations, (
        f"在非白名单文件中发现 {len(violations)} 处 'qihuo' 残留：\n"
        + "\n".join(violations[:20])
    )
```

- [ ] **Step 2: 运行门禁测试**

运行：
```bash
cd backend && uv run pytest tests/test_no_qihuo_residue.py -v
```
Expected: PASS（无任何非白名单违规项）

- [ ] **Step 3: 运行全量测试套件验证系统完整性**

运行：
```bash
cd backend && uv run pytest -q
```
Expected: 全部测试通过，无 `ImportError` 或缺失依赖。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_no_qihuo_residue.py
git commit -m "test(gate): 新增全仓 qihuo 残留扫描门禁测试"
```

---

## 验证基线与验收条件

完成所有任务后，运行下列验收命令：

```bash
# 1. 验证代码库中除了计划文档外再无 qihuo
git grep -i "qihuo" | grep -v "docs/superpowers/plans" | wc -l
# 期望输出: 0

# 2. 验证后端全量单元测试
cd backend && uv run pytest -q
# 期望输出: 全部通过

# 3. 验证前端类型与构建
cd ../frontend && pnpm lint
# 期望输出: 全部通过

# 4. 验证 Docker 编排无语法与服务引用错误
cd .. && docker compose config > /dev/null
# 期望退出码: 0
```
