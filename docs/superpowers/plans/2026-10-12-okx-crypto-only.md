# OKX 加密货币专属改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有期货因子挖掘平台改造为 OKX 加密货币专属版本：新分支、稀疏检出、剥离期货代码、接入 OKX 现货/永续行情与 K 线，最终交付一个能跑出真实 OKX 行情的系统。

**Architecture:** 沿用现有分层（`api` / `services` / `data` / `connectors` / `models`），只替换市场接入层。核心手法是**用一个 `app/data/instruments.py` 顶替 `app/data/contracts.py` 的 7 个公开查询函数**，从而让 98 处调用点零改动继续工作。OKX 行情走新增 `app/connectors/okx/`（REST 快照 + WS 增量），复用既有 Redis 键命名空间与 `quote_schema` 归一化契约。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy(async) / PostgreSQL 18 / Redis 7 / httpx / websockets / Next.js 15 / React 19 / Docker Compose

**Spec:** 本计划同时是 spec。前置分析结论见对话记录（期货耦合面勘察）；OKX API 事实来源见 `https://www.okx.com/docs-v5/en/`。

## Global Constraints

- Python `>=3.12`（`backend/pyproject.toml` 既有约束，不得下调）
- **不新增任何 Python 依赖**：`httpx>=0.27.0` 与 `websockets>=12.0` 已在 `backend/pyproject.toml`，OKX 接入只允许使用这两个
- 新分支名固定 `feat/okx-crypto-only`，从 `main`（当前 HEAD `b504207`）切出
- 内部 symbol 一律小写，格式 `<base>-<quote>[-SWAP]`，例：`btc-usdt-swap`、`btc-usdt`
- 品种 code 一律大写，取 instId 第一段，例：`btc-usdt-swap` → `BTC`
- OKX REST 基址 `https://www.okx.com`；WS 公开频道 `wss://ws.okx.com:8443/ws/v5/public`
- 模拟盘（demo）通过请求头 `x-simulated-trading: 1` 切换，不得用不同域名
- 每个 Task 结束必须 `git commit`，提交信息用 Conventional Commits（无 emoji）
- 测试命令统一 `cd backend && uv run pytest <path> -v`
- 不得降低 lint / typecheck / 测试门槛来让验证通过

---

## 现状事实（执行者必读）

这些是勘察得到的确定事实，不要重新推导：

| 事实 | 位置 | 含义 |
|---|---|---|
| `contracts.py` 导出 7 个查询函数 | `backend/app/data/contracts.py:331-402` | `get_code_for_symbol` / `get_master_symbol_for_code` / `get_product_name` / `get_contract_name` / `get_tick_size` / `get_decimal_places` / `round_by_tick` |
| 98 处引用 | `grep -rn "app.data.contracts" backend/app` | 全部只用到上述 7 函数 + `ALL_CONTRACTS` |
| `trading_mode` 是已验证的开关先例 | `backend/app/core/trading_mode.py` | 584 处引用、77 后端文件、41 前端处、Redis 键命名空间、JWT claim |
| Redis 键集中定义 | `backend/app/services/market_keys.py` | 约 20 个函数，全部以 `market:{mode}:*` 为前缀 |
| 时段函数已有降级路径 | `backend/app/services/session_profiles.py` | 无匹配 profile 返回 `None`，调用方回退墙钟（`sina_kline.py:113/241`、`kline.py:869`） |
| 因子层已容忍缺持仓量 | `backend/app/services/factor_lab/features/compute.py:142` | `has_oi=False` 时 OI 特征整体置零，不造假信号 |
| 测试规模 | `backend/tests/` | 152 个 `.py`，27,401 行 |
| 当前无 CI | `.github` 不存在 | 验证靠本地 pytest |
| OKX candle 返回 9 字段 | OKX docs-v5 | `[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]`，全为字符串；`confirm="1"` 表示已收盘 |
| OKX instruments 字段 | OKX docs-v5 | `ctVal`(合约面值) `ctMult` `lotSz`(数量步长) `minSz`(最小量) `tickSz`(最小价位) |

---

## Phase 0 — 分支与工作树

### Task 1: 建立分支与稀疏检出

**Files:**
- Modify: `.git/info/sparse-checkout`（git 元数据，不进版本库）

**Interfaces:**
- Consumes: 无
- Produces: 分支 `feat/okx-crypto-only`；工作树只物化 `backend/` 与 `frontend/` 两棵应用树及其构建配置

- [ ] **Step 1: 确认起点干净**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git status --short
git log --oneline -1
```

Expected: 仅 `?? .pi/` 与 `?? docker-compose.local.yml` 两个未跟踪项；HEAD 为 `b504207`。
`docker-compose.local.yml` 是本地容器化产物，**保留**，后续 Task 会用到。

- [ ] **Step 2: 从 main 切出新分支**

```bash
git checkout -b feat/okx-crypto-only
git branch --show-current
```

Expected: 输出 `feat/okx-crypto-only`

- [ ] **Step 3: 先提交本地 compose override（避免它被稀疏检出甩掉）**

```bash
git add docker-compose.local.yml
git commit -m "chore(deploy): 加入本地容器化 compose override"
```

Expected: 1 file changed

- [ ] **Step 4: 启用非 cone 模式稀疏检出**

必须用 `--no-cone`：cone 模式只能按目录粒度选，无法把 `backend/pyproject.toml` 这类单文件与目录混选。

```bash
git sparse-checkout init --no-cone
```

- [ ] **Step 5: 写入稀疏规则**

```bash
cat > .git/info/sparse-checkout <<'EOF'
/backend/app/
/backend/tests/
/backend/pyproject.toml
/backend/uv.lock
/backend/Dockerfile
/backend/ctp-bridge.Dockerfile
/frontend/src/
/frontend/public/
/frontend/package.json
/frontend/pnpm-lock.yaml
/frontend/next.config.ts
/frontend/tsconfig.json
/frontend/next-env.d.ts
/frontend/postcss.config.mjs
/frontend/Dockerfile
/docker-compose.yml
/docker-compose.local.yml
/.env.example
/.gitignore
/.gitattributes
/README.md
/LICENSE
# 本计划自身所在目录：不列入则 Task 1 会把计划从工作树删掉
/docs/superpowers/
EOF
git sparse-checkout reapply
```

- [ ] **Step 6: 验证工作树只剩应用树**

```bash
ls -A
echo "--- backend ---"
ls backend
echo "--- frontend ---"
ls frontend
```

Expected:
- 顶层只剩 `backend/` `frontend/` `docs/` `docker-compose.yml` `docker-compose.local.yml` `.env.example` `.gitignore` `.gitattributes` `README.md` `LICENSE`（外加 git 自动保留的 `.git/`、以及未被跟踪的 `.pi/`、`logs/`）
- `docs/` 下只保留 `superpowers/`（本计划），`SELF-HOSTING.md`、`screenshots/`、`benchmarks/` 等期货文档不物化
- **不再有** `deploy/` `doc/` `scripts/` `.claude/` `AI渠道商圆形图标_120x120/`
- `backend/` 下不再有 `.venv/`（被稀疏规则排除；**这会导致既有虚拟环境消失**，Task 6 会重建）

- [ ] **Step 7: 确认 .venv 与 node_modules 是否被甩掉，必要时重建**

```bash
ls backend/.venv 2>/dev/null || echo "backend/.venv 已不在工作树"
ls frontend/node_modules 2>/dev/null | head -1 || echo "frontend/node_modules 已不在工作树"
```

Expected: 两者都可能消失（它们本就被 `.gitignore` 忽略，但 `git sparse-checkout reapply` 会清理未被跟踪且不在锥内的文件）。
若消失，重建：

```bash
cd backend && uv venv .venv && uv sync
cd ../frontend && pnpm install
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit --allow-empty -m "chore(repo): 启用稀疏检出，工作树收敛至 backend/frontend"
```

Expected: 若无文件变化则为空提交，属正常。

---

### Task 2: 剥离期货专属代码

**Files:**
- Delete: `backend/app/connectors/ctp/`（整目录）
- Delete: `backend/app/connectors/sina/`（整目录）
- Delete: `backend/app/connectors/vvtr/`（整目录）
- Delete: `backend/app/relay/`（整目录）
- Delete: `backend/app/data/specs/`（整目录）
- Delete: `backend/app/data/{akshare_history,contract_keywords,contract_months,contracts,product_specs,sina_kline,sina_quote,term_structure,tickdata_kline,tickdata_writer,tqsdk_history,kline_crosscheck}.py`
- Delete: `backend/app/services/{contract_master,contracts_sync,session_profiles,kline_virtual,kline_virtual_hist,virtual_quote_fill,vvtr_tickdata_sync,tickdata_gap_backfill}.py`
- Delete: `backend/app/api/contracts.py`
- Delete: `frontend/src/data/contract-months.ts`
- Modify: `backend/app/main.py`（摘除已删模块的 import 与 router 注册）

**Interfaces:**
- Consumes: Task 1 的分支
- Produces: 一个 import 干净的期货剥离版仓库（此时**还不能跑**，因为 `contracts.py` 被删而调用点还在 —— Task 5 修复）

> **执行顺序警告：** 本 Task 会留下大量 `ImportError`，这是**预期的中间状态**。Task 3-5 修复后恢复可运行。不要在本 Task 试图让测试通过。

- [ ] **Step 1: 记录待删文件清单，供后续核对**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git ls-files backend/app/connectors backend/app/relay backend/app/data backend/app/services backend/app/api \
  | grep -E "connectors/(ctp|sina|vvtr)/|relay/|data/specs/|data/(akshare_history|contract_keywords|contract_months|contracts|product_specs|sina_kline|sina_quote|term_structure|tickdata_kline|tickdata_writer|tqsdk_history|kline_crosscheck)\.py|services/(contract_master|contracts_sync|session_profiles|kline_virtual|kline_virtual_hist|virtual_quote_fill|vvtr_tickdata_sync|tickdata_gap_backfill)\.py|api/contracts\.py" \
  | tee /tmp/futures-files.txt | wc -l
```

Expected: 打印一批路径并给出计数（预计 40-60 个文件）。清单存入 `/tmp/futures-files.txt`。

- [ ] **Step 2: 执行删除**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git rm -r -q backend/app/connectors/ctp backend/app/connectors/sina backend/app/connectors/vvtr
git rm -r -q backend/app/relay
git rm -r -q backend/app/data/specs
git rm -q backend/app/data/akshare_history.py backend/app/data/contract_keywords.py \
  backend/app/data/contract_months.py backend/app/data/contracts.py \
  backend/app/data/product_specs.py backend/app/data/sina_kline.py \
  backend/app/data/sina_quote.py backend/app/data/term_structure.py \
  backend/app/data/tickdata_kline.py backend/app/data/tickdata_writer.py \
  backend/app/data/tqsdk_history.py backend/app/data/kline_crosscheck.py
git rm -q backend/app/services/contract_master.py backend/app/services/contracts_sync.py \
  backend/app/services/session_profiles.py backend/app/services/kline_virtual.py \
  backend/app/services/kline_virtual_hist.py backend/app/services/virtual_quote_fill.py \
  backend/app/services/vvtr_tickdata_sync.py backend/app/services/tickdata_gap_backfill.py
git rm -q backend/app/api/contracts.py
git rm -q frontend/src/data/contract-months.ts
```

- [ ] **Step 3: 清掉因删除而变成空壳的目录**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
find backend/app frontend/src -type d -empty -not -path "*/node_modules/*" -print
```

Expected: 打印空目录（若有）。逐个 `rmdir` 之。

- [ ] **Step 4: 摘除 main.py 中的相关 import 与 router 注册**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
grep -n "contracts\|ctp\|sina\|vvtr\|relay\|virtual\|tickdata\|session_profiles\|contract_master" app/main.py
```

Expected: 打印若干行。逐行处理：
- 形如 `from app.api.contracts import router as contracts_router` 的 import 行 → 删除
- 形如 `application.include_router(contracts_router)` 的注册行 → 删除
- 形如 `from app.services.scheduler import ...` 若其内部依赖已删模块 → **保留 import**，在 Task 5 一并修复（scheduler 是核心，不删）

- [ ] **Step 5: 摘除 scheduler 与其它核心服务中的期货调用**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
grep -rn "contract_master\|contract_months\|session_profiles\|app.data.contracts\|app.data.sina_\|app.data.tickdata\|app.data.tqsdk\|app.data.product_specs\|app.data.contract_keywords\|app.data.kline_crosscheck\|app.data.term_structure\|app.data.akshare_history" app --include=*.py
```

Expected: 打印剩余引用点。**本步骤只做记录**，不改代码 —— Task 5 会用一个统一的 import 替换把它们全部指向新模块。把输出存盘：

```bash
grep -rn "contract_master\|contract_months\|session_profiles\|app.data.contracts\|app.data.sina_\|app.data.tickdata\|app.data.tqsdk\|app.data.product_specs\|app.data.contract_keywords\|app.data.kline_crosscheck\|app.data.term_structure\|app.data.akshare_history" app --include=*.py > /tmp/futures-refs.txt
wc -l /tmp/futures-refs.txt
```

- [ ] **Step 6: 删除期货专属测试**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
ls tests | grep -iE "contract|sina|ctp|vvtr|tickdata|tqsdk|session|virtual|kline_history|term_struct|akshare"
```

Expected: 打印期货专属测试文件。逐个 `git rm`。**注意保留** `test_kline_*.py` 中与 OKX 无关但测的是通用 K 线逻辑的（逐个判断：文件内 import 了已删模块的才删）。

- [ ] **Step 7: 验证删除彻底**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
ls backend/app/connectors/ 2>/dev/null; echo "--- relay ---"; ls backend/app/relay 2>/dev/null || echo "relay 已删"
echo "--- 残留引用（应为空）---"
grep -rn "from app.connectors.ctp\|from app.connectors.sina\|from app.connectors.vvtr\|from app.relay" backend/app --include=*.py || echo "无残留"
```

Expected: `backend/app/connectors/` 只剩 `__init__.py`；`relay 已删`；`无残留`

- [ ] **Step 8: Commit**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add -A
git commit -m "refactor(okx): 剥离期货专属代码（CTP/新浪/VVTR/合约与时段）" \
  -m "- 删除 connectors/{ctp,sina,vvtr} 与 relay
- 删除合约表、交割月、品种规格、期货数据源与深历史
- 删除主力合约与期货交易时段服务
- 删除期货专属 API 路由与前端交割月表"
```

---

## Phase 1 — 品种抽象层

### Task 3: OKX Instrument 模型与查找表

**Files:**
- Create: `backend/app/data/instruments.py`
- Test: `backend/tests/test_okx_instruments.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `@dataclass(frozen=True) class Instrument`，字段：`symbol: str`、`code: str`、`name: str`、`exchange: str`、`tick_size: float`、`contract_value: float`、`min_qty: float`、`lot_size: float`、`quote_ccy: str`
  - `set_instruments(items: list[Instrument]) -> None`
  - `all_instruments() -> list[Instrument]`
  - `get_code_for_symbol(symbol: str) -> str`
  - `get_master_symbol_for_code(code: str) -> str`
  - `get_product_name(code: str) -> str`
  - `get_contract_name(symbol: str) -> str`
  - `get_tick_size(code: str) -> float`
  - `get_decimal_places(code: str) -> int`
  - `round_by_tick(price: float, code: str) -> float`
  - `get_instrument(symbol: str) -> Instrument | None`
  - `DEFAULT_TICK_SIZE: float = 0.01`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_okx_instruments.py`：

```python
"""OKX 品种查找表 —— 7 个兼容查询函数 + Instrument 模型"""

from app.data import instruments as inst


def _seed():
    inst.set_instruments([
        inst.Instrument(
            symbol="btc-usdt-swap", code="BTC", name="BTC/USDT 永续",
            exchange="OKX", tick_size=0.1, contract_value=0.01,
            min_qty=0.01, lot_size=0.01, quote_ccy="USDT",
        ),
        inst.Instrument(
            symbol="eth-usdt-swap", code="ETH", name="ETH/USDT 永续",
            exchange="OKX", tick_size=0.01, contract_value=0.1,
            min_qty=0.1, lot_size=0.1, quote_ccy="USDT",
        ),
        inst.Instrument(
            symbol="btc-usdt", code="BTC", name="BTC/USDT 现货",
            exchange="OKX", tick_size=0.1, contract_value=1.0,
            min_qty=0.00001, lot_size=0.00000001, quote_ccy="USDT",
        ),
    ])


def test_code_from_full_symbol():
    _seed()
    assert inst.get_code_for_symbol("btc-usdt-swap") == "BTC"


def test_code_from_bare_code():
    _seed()
    assert inst.get_code_for_symbol("btc") == "BTC"


def test_code_unknown_returns_empty():
    _seed()
    assert inst.get_code_for_symbol("nope-usdt") == ""


def test_master_symbol_prefers_swap():
    """永续优先于现货：OKX 主战场是 SWAP"""
    _seed()
    assert inst.get_master_symbol_for_code("BTC") == "btc-usdt-swap"


def test_product_name_is_code():
    _seed()
    assert inst.get_product_name("BTC") == "BTC"


def test_contract_name_is_display_name():
    _seed()
    assert inst.get_contract_name("btc-usdt-swap") == "BTC/USDT 永续"


def test_contract_name_unknown_symbol_falls_back_to_symbol():
    _seed()
    assert inst.get_contract_name("zzz-usdt") == "zzz-usdt"


def test_tick_size_and_decimal_places():
    _seed()
    assert inst.get_tick_size("BTC") == 0.1
    assert inst.get_decimal_places("BTC") == 1
    assert inst.get_decimal_places("ETH") == 2


def test_decimal_places_for_whole_number_tick():
    inst.set_instruments([
        inst.Instrument(
            symbol="x-usdt-swap", code="X", name="X", exchange="OKX",
            tick_size=1.0, contract_value=1.0, min_qty=1.0,
            lot_size=1.0, quote_ccy="USDT",
        ),
    ])
    assert inst.get_decimal_places("X") == 0


def test_round_by_tick():
    _seed()
    assert inst.round_by_tick(123.456, "BTC") == 123.5
    assert inst.round_by_tick(123.44, "ETH") == 123.44


def test_unknown_code_uses_default_tick():
    _seed()
    assert inst.get_tick_size("ZZZ") == inst.DEFAULT_TICK_SIZE


def test_get_instrument_returns_none_for_unknown():
    _seed()
    assert inst.get_instrument("nope") is None
    assert inst.get_instrument("btc-usdt-swap").contract_value == 0.01


def test_set_instruments_replaces_previous():
    _seed()
    inst.set_instruments([])
    assert inst.all_instruments() == []
    assert inst.get_code_for_symbol("btc-usdt-swap") == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_okx_instruments.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.data.instruments'`

- [ ] **Step 3: 写最小实现**

创建 `backend/app/data/instruments.py`：

```python
"""OKX 品种定义与查找表 —— 顶替原期货合约表（app.data.contracts）

对外保持与原 contracts.py 同名的 7 个查询函数，使 98 处调用点无需改动。

主力口径：同 code 下优先 SWAP（永续），其次 SPOT —— OKX 主战场是永续，
且永续无到期日，不需要换月逻辑。

数据由 app.connectors.okx.instruments 在启动时经
GET /api/v5/public/instruments 拉取后调用 set_instruments 灌入；
本模块只负责存储与查询，不做任何网络访问。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

DEFAULT_TICK_SIZE = 0.01

EXCHANGE_OKX = "OKX"


@dataclass(frozen=True)
class Instrument:
    """单个可交易标的

    symbol 为内部规范符号（小写），如 btc-usdt-swap；
    contract_value 对应 OKX 的 ctVal（每张合约面值，现货恒为 1.0）。
    """

    symbol: str
    code: str
    name: str
    exchange: str
    tick_size: float
    contract_value: float
    min_qty: float
    lot_size: float
    quote_ccy: str


_INSTRUMENTS: list[Instrument] = []
_BY_SYMBOL: dict[str, Instrument] = {}
_BY_CODE: dict[str, list[Instrument]] = {}
_MASTER_BY_CODE: dict[str, str] = {}


def _kind_rank(symbol: str) -> int:
    """symbol 的品种类型权重：永续 0，现货 1，其它 2"""
    if symbol.endswith("-swap"):
        return 0
    if symbol.count("-") == 1:
        return 1
    return 2


def set_instruments(items: Iterable[Instrument]) -> None:
    """整体替换品种表并重建全部查找索引"""
    global _INSTRUMENTS, _BY_SYMBOL, _BY_CODE, _MASTER_BY_CODE

    _INSTRUMENTS = list(items)
    _BY_SYMBOL = {i.symbol: i for i in _INSTRUMENTS}

    by_code: dict[str, list[Instrument]] = {}
    for item in _INSTRUMENTS:
        by_code.setdefault(item.code, []).append(item)
    _BY_CODE = by_code

    _MASTER_BY_CODE = {
        code: min(rows, key=lambda i: (_kind_rank(i.symbol), i.symbol)).symbol
        for code, rows in by_code.items()
    }


def all_instruments() -> list[Instrument]:
    """当前全部标的"""
    return list(_INSTRUMENTS)


def get_instrument(symbol: str) -> Instrument | None:
    """按 symbol 精确取标的，未找到返回 None"""
    return _BY_SYMBOL.get(str(symbol or "").strip().lower())


def get_code_for_symbol(symbol: str) -> str:
    """symbol → 品种 code（大写）。支持全符号、纯 code、未知返回空串"""
    s = str(symbol or "").strip().lower()
    if not s:
        return ""
    hit = _BY_SYMBOL.get(s)
    if hit is not None:
        return hit.code
    # 纯 code 形式（如 btc / BTC）
    rows = _BY_CODE.get(s.upper())
    if rows:
        return rows[0].code
    # 前缀兜底：btc-anything → BTC
    head = s.split("-")[0].upper()
    if head in _BY_CODE:
        return head
    return ""


def get_master_symbol_for_code(code: str) -> str:
    """品种 code → 主力 symbol（永续优先）。未知时原样返回入参"""
    c = str(code or "").strip().upper()
    master = _MASTER_BY_CODE.get(c)
    if master:
        return master
    return str(code or "")


def get_product_name(code: str) -> str:
    """品种 code → 展示名（即 code 本身，OKX 无中文品种名）"""
    c = str(code or "").strip().upper()
    if c in _BY_CODE:
        return c
    return c


def get_contract_name(symbol: str) -> str:
    """symbol → 展示名；未知则原样返回 symbol"""
    s = str(symbol or "").strip().lower()
    hit = _BY_SYMBOL.get(s)
    if hit is not None:
        return hit.name
    return str(symbol or "")


def get_tick_size(code: str) -> float:
    """品种最小变动价位；未知返回 DEFAULT_TICK_SIZE"""
    rows = _BY_CODE.get(str(code or "").strip().upper())
    if not rows:
        return DEFAULT_TICK_SIZE
    return min(r.tick_size for r in rows)


def get_decimal_places(code: str) -> int:
    """按 tick_size 推算价格显示小数位"""
    tick = get_tick_size(code)
    if tick >= 1:
        return 0
    text = f"{tick:.10f}".rstrip("0").split(".")
    return len(text[1]) if len(text) > 1 else 0


def round_by_tick(price: float, code: str) -> float:
    """按品种最小变动价位取整价格"""
    tick = get_tick_size(code)
    if tick <= 0:
        return float(price)
    return round(round(float(price) / tick) * tick, 10)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_okx_instruments.py -v`
Expected: PASS，13 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/data/instruments.py backend/tests/test_okx_instruments.py
git commit -m "feat(okx): 新增品种查找表顶替期货合约表" \
  -m "- Instrument 模型承载 ctVal/tickSz/lotSz 等 OKX 规格
- 7 个查询函数与原 contracts.py 同名同签名，调用点无需改动
- 主力口径改为永续优先，取消换月逻辑"
```

---

### Task 4: OKX instruments 拉取与缓存

**Files:**
- Create: `backend/app/connectors/__init__.py`（若已存在则跳过）
- Create: `backend/app/connectors/okx/__init__.py`
- Create: `backend/app/connectors/okx/client.py`
- Create: `backend/app/connectors/okx/instruments.py`
- Test: `backend/tests/test_okx_instruments_fetch.py`

**Interfaces:**
- Consumes: Task 3 的 `Instrument`、`set_instruments`
- Produces:
  - `class OkxApiError(Exception)`，属性 `code: str`、`msg: str`
  - `class OkxRestClient`，方法：`async def get(path: str, params: dict | None = None) -> list[dict]`、`async def aclose() -> None`、构造签名 `OkxRestClient(base_url: str = OKX_BASE_URL, demo: bool = False, timeout: float = 10.0)`
  - `OKX_BASE_URL: str = "https://www.okx.com"`
  - `async def fetch_instruments(client: OkxRestClient, inst_type: str = "SWAP") -> list[Instrument]`
  - `async def refresh_instruments(client: OkxRestClient) -> int`
  - `def parse_instrument(raw: dict) -> Instrument | None`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_okx_instruments_fetch.py`：

```python
"""OKX instruments 解析与拉取"""

import pytest

from app.connectors.okx import instruments as oi
from app.connectors.okx.client import OkxApiError, OkxRestClient


SWAP_RAW = {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "uly": "BTC-USDT",
    "instFamily": "BTC-USDT",
    "baseCcy": "",
    "quoteCcy": "",
    "settleCcy": "USDT",
    "ctVal": "0.01",
    "ctMult": "1",
    "ctValCcy": "BTC",
    "tickSz": "0.1",
    "lotSz": "0.01",
    "minSz": "0.01",
    "state": "live",
}

SPOT_RAW = {
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "baseCcy": "BTC",
    "quoteCcy": "USDT",
    "tickSz": "0.1",
    "lotSz": "0.00000001",
    "minSz": "0.00001",
    "state": "live",
}


def test_parse_swap_maps_contract_value_from_ct_val():
    item = oi.parse_instrument(SWAP_RAW)
    assert item is not None
    assert item.symbol == "btc-usdt-swap"
    assert item.code == "BTC"
    assert item.tick_size == 0.1
    assert item.contract_value == 0.01
    assert item.min_qty == 0.01
    assert item.lot_size == 0.01
    assert item.quote_ccy == "USDT"


def test_parse_spot_uses_base_and_quote_ccy():
    item = oi.parse_instrument(SPOT_RAW)
    assert item is not None
    assert item.symbol == "btc-usdt"
    assert item.code == "BTC"
    assert item.contract_value == 1.0
    assert item.quote_ccy == "USDT"


def test_parse_skips_non_live():
    raw = {**SWAP_RAW, "state": "suspend"}
    assert oi.parse_instrument(raw) is None


def test_parse_skips_usdc_quoted():
    """只保留 USDT 计价，避免同名品种跨计价币冲突"""
    raw = {**SWAP_RAW, "instId": "BTC-USDC-SWAP", "settleCcy": "USDC"}
    assert oi.parse_instrument(raw) is None


def test_parse_returns_none_on_bad_numbers():
    raw = {**SWAP_RAW, "tickSz": "abc"}
    assert oi.parse_instrument(raw) is None


def test_parse_returns_none_without_inst_id():
    raw = {k: v for k, v in SWAP_RAW.items() if k != "instId"}
    assert oi.parse_instrument(raw) is None


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def get(self, path, params=None):
        self.calls.append((path, params))
        return self._payload


@pytest.mark.asyncio
async def test_fetch_instruments_requests_swap_type():
    client = _FakeClient([SWAP_RAW])
    items = await oi.fetch_instruments(client, "SWAP")
    assert len(items) == 1
    assert client.calls[0][0] == "/api/v5/public/instruments"
    assert client.calls[0][1]["instType"] == "SWAP"


@pytest.mark.asyncio
async def test_refresh_instruments_populates_module_table():
    from app.data import instruments as inst

    client = _FakeClient([SWAP_RAW, SPOT_RAW])
    count = await oi.refresh_instruments(client)
    assert count == 2
    assert inst.get_code_for_symbol("btc-usdt-swap") == "BTC"
    assert inst.get_master_symbol_for_code("BTC") == "btc-usdt-swap"


def test_api_error_carries_code_and_msg():
    err = OkxApiError("51001", "Instrument ID does not exist")
    assert err.code == "51001"
    assert "does not exist" in err.msg
    assert "51001" in str(err)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_okx_instruments_fetch.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.connectors.okx'`

- [ ] **Step 3: 写 REST 客户端**

创建 `backend/app/connectors/__init__.py`（若已存在则保持原样）与
`backend/app/connectors/okx/__init__.py`（空文件）。

创建 `backend/app/connectors/okx/client.py`：

```python
"""OKX REST v5 客户端 —— 公开行情接口（无需鉴权）

私有接口（下单/持仓）不在本计划范围；Phase 3 扩展时在
本模块加签名（HMAC-SHA256 + passphrase）而非另起客户端。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("qihuo.okx.client")

OKX_BASE_URL = "https://www.okx.com"

# 模拟盘开关：OKX 用请求头而非独立域名
DEMO_HEADER = "x-simulated-trading"

# OKX 业务码：0 为成功
_OK_CODE = "0"


class OkxApiError(Exception):
    """OKX 返回非 0 业务码"""

    def __init__(self, code: str, msg: str) -> None:
        self.code = str(code)
        self.msg = str(msg)
        super().__init__(f"OKX {self.code}: {self.msg}")


class OkxRestClient:
    """薄封装：统一业务码校验与 data 提取"""

    def __init__(
        self,
        base_url: str = OKX_BASE_URL,
        demo: bool = False,
        timeout: float = 10.0,
    ) -> None:
        headers: dict[str, str] = {}
        if demo:
            headers[DEMO_HEADER] = "1"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET 并返回 data 数组；业务码非 0 抛 OkxApiError"""
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        body = resp.json()
        code = str(body.get("code") or "")
        if code != _OK_CODE:
            raise OkxApiError(code, str(body.get("msg") or ""))
        data = body.get("data")
        return data if isinstance(data, list) else []
```

- [ ] **Step 4: 写 instruments 拉取**

创建 `backend/app/connectors/okx/instruments.py`：

```python
"""从 OKX 拉取品种规格并灌入 app.data.instruments 查找表"""

from __future__ import annotations

import logging
from typing import Any

from app.data.instruments import EXCHANGE_OKX, Instrument, set_instruments

logger = logging.getLogger("qihuo.okx.instruments")

_INSTRUMENTS_PATH = "/api/v5/public/instruments"

# 只保留 USDT 计价：同名 base 在 USDC/USD 下会与 USDT 行冲突，
# 且本项目账户/计价统一 USDT
_KEEP_QUOTE = "USDT"

# 只保留可交易状态
_LIVE_STATE = "live"


def _f(raw: Any) -> float | None:
    """安全转 float，失败返回 None"""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _quote_ccy(raw: dict[str, Any]) -> str:
    """永续取 settleCcy，现货取 quoteCcy"""
    return str(raw.get("settleCcy") or raw.get("quoteCcy") or "").upper()


def parse_instrument(raw: dict[str, Any]) -> Instrument | None:
    """OKX instruments 条目 → Instrument；不可用返回 None"""
    inst_id = str(raw.get("instId") or "").strip()
    if not inst_id:
        return None
    if str(raw.get("state") or "") != _LIVE_STATE:
        return None

    quote = _quote_ccy(raw)
    if quote != _KEEP_QUOTE:
        return None

    symbol = inst_id.lower()
    # code 取第一段：btc-usdt-swap → BTC
    code = symbol.split("-")[0].upper()
    if not code:
        return None

    tick = _f(raw.get("tickSz"))
    lot = _f(raw.get("lotSz"))
    min_sz = _f(raw.get("minSz"))
    if tick is None or tick <= 0 or lot is None or min_sz is None:
        return None

    is_swap = symbol.endswith("-swap")
    if is_swap:
        ct_val = _f(raw.get("ctVal"))
        if ct_val is None or ct_val <= 0:
            return None
        kind = "永续"
    else:
        ct_val = 1.0
        kind = "现货"

    return Instrument(
        symbol=symbol,
        code=code,
        name=f"{code}/{quote} {kind}",
        exchange=EXCHANGE_OKX,
        tick_size=tick,
        contract_value=ct_val,
        min_qty=min_sz,
        lot_size=lot,
        quote_ccy=quote,
    )


async def fetch_instruments(
    client: Any,
    inst_type: str = "SWAP",
) -> list[Instrument]:
    """拉取指定 instType 的品种清单（只读公开接口）"""
    rows = await client.get(_INSTRUMENTS_PATH, {"instType": inst_type})
    out: list[Instrument] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = parse_instrument(raw)
        if item is not None:
            out.append(item)
    return out


async def refresh_instruments(client: Any) -> int:
    """拉取 SWAP + SPOT 并整体替换查找表，返回写入条数"""
    swap = await fetch_instruments(client, "SWAP")
    spot = await fetch_instruments(client, "SPOT")
    merged = {i.symbol: i for i in (*swap, *spot)}
    set_instruments(list(merged.values()))
    logger.info(
        "OKX 品种表已更新：SWAP %d 条，SPOT %d 条，去重后 %d 条",
        len(swap), len(spot), len(merged),
    )
    return len(merged)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_okx_instruments_fetch.py -v`
Expected: PASS，10 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/connectors/okx backend/tests/test_okx_instruments_fetch.py
git commit -m "feat(okx): 接入 REST 客户端与品种规格拉取" \
  -m "- OkxRestClient 统一业务码校验与 data 提取
- parse_instrument 映射 ctVal/tickSz/lotSz 到 Instrument
- 只保留 USDT 计价与 live 状态，避免同名品种冲突
- 零新增依赖（复用既有 httpx）"
```

---

### Task 5: 替换全部调用点，恢复可导入

**Files:**
- Modify: 所有引用已删模块的 `backend/app/**/*.py`（清单见 `/tmp/futures-refs.txt`）
- Modify: `backend/app/main.py`（启动时注入品种表）
- Test: `backend/tests/test_import_clean.py`

**Interfaces:**
- Consumes: Task 3 的 7 个查询函数、Task 4 的 `refresh_instruments`、`OkxRestClient`
- Produces: 全仓可导入状态；`main.py` lifespan 启动时调用 `refresh_instruments`

- [ ] **Step 1: 写失败测试（导入洁净性）**

创建 `backend/tests/test_import_clean.py`：

```python
"""全仓导入洁净性 —— 不得残留已删模块引用"""

import importlib
import pkgutil
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# 已删除的模块前缀（Phase 0 剥离的期货代码）
REMOVED_PREFIXES = (
    "app.connectors.ctp",
    "app.connectors.sina",
    "app.connectors.vvtr",
    "app.relay",
    "app.data.contracts",
    "app.data.contract_months",
    "app.data.contract_keywords",
    "app.data.product_specs",
    "app.data.specs",
    "app.data.sina_kline",
    "app.data.sina_quote",
    "app.data.tickdata_kline",
    "app.data.tickdata_writer",
    "app.data.tqsdk_history",
    "app.data.akshare_history",
    "app.data.term_structure",
    "app.data.kline_crosscheck",
    "app.services.contract_master",
    "app.services.contracts_sync",
    "app.services.session_profiles",
    "app.services.kline_virtual",
    "app.services.kline_virtual_hist",
    "app.services.virtual_quote_fill",
    "app.services.vvtr_tickdata_sync",
    "app.services.tickdata_gap_backfill",
    "app.api.contracts",
)


def _all_module_names() -> list[str]:
    names = []
    for info in pkgutil.walk_packages([str(APP_ROOT)], prefix="app."):
        names.append(info.name)
    return names


def test_no_source_file_references_removed_modules():
    """源码文本层面不得出现已删模块引用"""
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for prefix in REMOVED_PREFIXES:
            if prefix in text:
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}: {prefix}")
    assert offenders == [], "残留引用：\n" + "\n".join(offenders)


@pytest.mark.parametrize("name", _all_module_names())
def test_module_imports(name):
    """每个模块都能独立导入"""
    importlib.import_module(name)


def test_removed_modules_are_gone():
    """已删模块确实不存在"""
    for prefix in REMOVED_PREFIXES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(prefix)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_import_clean.py -v`
Expected: FAIL，`test_no_source_file_references_removed_modules` 列出残留引用

- [ ] **Step 3: 机械替换 import 路径**

对 `/tmp/futures-refs.txt` 中的每一处，按此映射改写：

| 原 import | 新 import |
|---|---|
| `from app.data.contracts import X` | `from app.data.instruments import X` |
| `from app.data import contracts` | `from app.data import instruments as contracts` |
| `from app.services.contract_master import X` | 见 Step 4 |
| `from app.services.session_profiles import X` | 见 Step 5 |
| `from app.data.sina_quote import X` | 见 Step 6 |
| `from app.data.sina_kline import X` | 见 Step 6 |
| `from app.data.tickdata_kline import X` | 删除该 import 及其调用块 |
| `from app.data.tqsdk_history import X` | 删除该 import 及其调用块 |
| `from app.data.akshare_history import X` | 删除该 import 及其调用块 |
| `from app.data.term_structure import X` | 删除该 import 及其调用块 |
| `from app.data.kline_crosscheck import X` | 删除该 import 及其调用块 |
| `from app.data.product_specs import X` | 删除该 import 及其调用块 |
| `from app.services.kline_virtual* import X` | 删除该 import 及其调用块 |
| `from app.services.virtual_quote_fill import X` | 删除该 import 及其调用块 |
| `from app.services.vvtr_tickdata_sync import X` | 删除该 import 及其调用块 |
| `from app.services.tickdata_gap_backfill import X` | 删除该 import 及其调用块 |

先做批量替换：

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
grep -rl "app\.data\.contracts" app --include=*.py | while read -r f; do
  sed -i '' 's/from app\.data\.contracts import/from app.data.instruments import/g; s/from app\.data import contracts/from app.data import instruments as contracts/g' "$f"
done
grep -rn "app.data.contracts" app --include=*.py || echo "contracts 引用已清零"
```

Expected: `contracts 引用已清零`

- [ ] **Step 4: 处理主力合约调用点**

`contract_master` 的调用点（8 处）按用途分类处理：

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
grep -rn "contract_master" app --include=*.py
```

- 若用于「取主力 symbol」→ 改为 `from app.data.instruments import get_master_symbol_for_code`
- 若用于「按成交量识别主力」→ **整块删除**（OKX 永续无换月，不需要识别）
- 若用于「拉主力清单」→ 改为 `from app.data.instruments import all_instruments`

- [ ] **Step 5: 处理交易时段调用点**

`session_profiles` 的调用点（4 处：`data/tickdata_kline.py`、`data/sina_kline.py`、`services/trading_hours.py`、`services/kline.py`）：
`tickdata_kline.py` 与 `sina_kline.py` 已在 Phase 0 删除，剩 `trading_hours.py` 与 `kline.py`。

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
grep -n "session_profiles\|period_end_for_product\|period_start_for_product\|fold_tick_minute_edge" app/services/trading_hours.py app/services/kline.py
```

新建 `backend/app/services/trading_hours.py` 的 24/7 实现（Phase 3 Task 10 会扩充，此处先给最小可用版）：

```python
"""交易时段 —— OKX 加密 24/7，无夜盘/无休市

替代原期货 session_profiles。OKX 现货与永续全年无休，
因此所有时段函数退化为「恒在交易中 + 墙钟对齐」。
"""

from __future__ import annotations

from datetime import datetime, timedelta

# OKX 24/7：恒定
ALWAYS_OPEN = True


def is_trading_now(at: datetime) -> bool:
    """OKX 全年无休"""
    return True


def period_end_for_product(product_code: str, at: datetime, minutes: int) -> datetime | None:
    """当前多分钟 K 线的结束时刻：24/7 下即墙钟上取整到 minutes 边界"""
    if minutes <= 0:
        return None
    base = at.replace(second=0, microsecond=0)
    remainder = base.minute % minutes
    if remainder == 0 and at.second == 0:
        return base
    return base + timedelta(minutes=minutes - remainder)


def period_start_for_product(product_code: str, at: datetime, minutes: int) -> datetime | None:
    """at 所属多分钟桶的起点：24/7 下即墙钟下取整"""
    if minutes <= 0:
        return None
    base = at.replace(second=0, microsecond=0)
    return base - timedelta(minutes=base.minute % minutes)


def fold_tick_minute_edge(product_code: str, at: datetime) -> datetime:
    """24/7 无收盘打印语义，原样返回"""
    return at
```

在 `app/services/kline.py` 中把 import 改为：

```python
from app.services.trading_hours import (
    fold_tick_minute_edge,
    period_end_for_product,
    period_start_for_product,
)
```

- [ ] **Step 6: 处理行情源调用点**

`data/sina_quote.py`、`data/sina_kline.py` 已删。检查 `data/kline_provider.py` 与 `services/kline.py` 中的引用：

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
grep -n "sina\|Sina" app/data/kline_provider.py app/services/kline.py app/services/kline_sync.py | head -30
```

处理原则：把新浪数据源分支**删除**，保留函数签名；OKX 数据源在 Phase 2（Task 6-9）填充。此处先让函数返回空列表而非抛异常，保证导入通过：

```python
    # OKX 数据源在 Phase 2 接入；此处返回空列表让调用方走降级路径
    return []
```

- [ ] **Step 7: 在 main.py lifespan 注入品种表**

修改 `backend/app/main.py` 的 `lifespan`，在 `_init_tables` 之后加入：

```python
    # 拉取 OKX 品种规格（失败不阻塞启动：品种表为空时行情链路自然降级）
    from app.connectors.okx.client import OkxRestClient
    from app.connectors.okx.instruments import refresh_instruments

    okx_client = OkxRestClient()
    try:
        count = await refresh_instruments(okx_client)
        logger.info("OKX 品种表就绪：%d 条", count)
    except Exception as exc:
        logger.warning("OKX 品种表拉取失败（行情将不可用）：%s", exc)
    application.state.okx_client = okx_client
```

并在关闭段（`yield` 之后）加入：

```python
    await okx_client.aclose()
```

- [ ] **Step 8: 运行导入测试**

Run: `cd backend && uv run pytest tests/test_import_clean.py -v`
Expected: PASS（全部模块可导入、无残留引用）

- [ ] **Step 9: 运行全量测试，记录基线**

Run: `cd backend && uv run pytest -q 2>&1 | tail -30`
Expected: 有失败是**预期的**（删除了期货测试的依赖）。记录失败清单：

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest -q 2>&1 | tail -40 > /tmp/test-baseline.txt
cat /tmp/test-baseline.txt
```

- [ ] **Step 10: Commit**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add -A
git commit -m "refactor(okx): 全部调用点切换到 OKX 品种表与 24/7 时段" \
  -m "- 98 处 contracts 引用改为 instruments（同名同签名）
- 新增 24/7 trading_hours 顶替期货 session_profiles
- 删除期货数据源分支，保留函数签名待 Phase 2 填充
- main.py 启动时拉取 OKX 品种表，失败不阻塞启动"
```

---

## Phase 2 — OKX 行情接入

### Task 6: OKX REST 行情（ticker 快照）

**Files:**
- Create: `backend/app/connectors/okx/market.py`
- Test: `backend/tests/test_okx_market.py`

**Interfaces:**
- Consumes: `OkxRestClient`（Task 4）
- Produces:
  - `async def fetch_tickers(client, inst_type: str = "SWAP") -> list[dict]`
  - `def ticker_to_quote(raw: dict) -> dict | None`
  - 返回的 quote dict 字段：`symbol`、`name`、`exchange`、`last_price`、`open_price`、`high_price`、`low_price`、`bid_price`、`ask_price`、`bid_vol`、`ask_vol`、`volume`、`turnover`、`tick_time`、`change_pct`（均可被 `app.data.quote_schema.normalize_quote_fields` 接受）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_okx_market.py`：

```python
"""OKX 行情解析"""

from app.connectors.okx.market import ticker_to_quote
from app.data.quote_schema import normalize_quote_fields


TICKER_RAW = {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "last": "61234.5",
    "lastSz": "1",
    "askPx": "61235.0",
    "askSz": "12",
    "bidPx": "61234.0",
    "bidSz": "8",
    "open24h": "60000.0",
    "high24h": "62000.0",
    "low24h": "59500.0",
    "volCcy24h": "123456.78",
    "vol24h": "12345",
    "ts": "1791782400000",
    "sodUtc0": "60100.0",
    "sodUtc8": "60200.0",
}


def test_ticker_maps_prices():
    q = ticker_to_quote(TICKER_RAW)
    assert q is not None
    assert q["symbol"] == "btc-usdt-swap"
    assert q["last_price"] == 61234.5
    assert q["bid_price"] == 61234.0
    assert q["ask_price"] == 61235.0
    assert q["bid_vol"] == 8
    assert q["ask_vol"] == 12


def test_ticker_uses_sod_utc8_as_pre_close():
    """OKX 的 sodUtc8 是北京时区零点开盘价，用作涨跌幅基准"""
    q = ticker_to_quote(TICKER_RAW)
    assert q["pre_close"] == 60200.0


def test_normalized_quote_computes_change_pct_from_pre_close():
    """涨跌幅由 quote_schema 按 pre_close 算，ticker_to_quote 不重复实现"""
    norm = normalize_quote_fields(ticker_to_quote(TICKER_RAW))
    assert norm is not None
    assert norm["change"] is not None
    expected = (61234.5 - 60200.0) / 60200.0 * 100
    assert round(norm["change_pct"], 4) == round(expected, 4)


def test_ticker_falls_back_to_sod_utc0_when_utc8_missing():
    raw = {k: v for k, v in TICKER_RAW.items() if k != "sodUtc8"}
    q = ticker_to_quote(raw)
    assert q["pre_close"] == 60100.0


def test_ticker_survives_missing_pre_close():
    raw = {k: v for k, v in TICKER_RAW.items() if k not in ("sodUtc8", "sodUtc0")}
    q = ticker_to_quote(raw)
    assert q is not None
    assert q["pre_close"] is None


def test_ticker_returns_none_on_bad_last():
    raw = {**TICKER_RAW, "last": "0"}
    assert ticker_to_quote(raw) is None


def test_ticker_returns_none_without_inst_id():
    raw = {k: v for k, v in TICKER_RAW.items() if k != "instId"}
    assert ticker_to_quote(raw) is None


def test_quote_passes_normalize_contract():
    """输出必须能被既有 quote_schema 归一化（下游 K 线/WS 契约）"""
    q = ticker_to_quote(TICKER_RAW)
    norm = normalize_quote_fields(q)
    assert norm is not None
    assert norm["symbol"] == "btc-usdt-swap"
    assert norm["last_price"] == 61234.5
    assert norm["position"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_okx_market.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.connectors.okx.market'`

- [ ] **Step 3: 写实现**

创建 `backend/app/connectors/okx/market.py`：

```python
"""OKX 行情 REST —— ticker 快照

输出统一 quote dict，字段集必须能被 app.data.quote_schema.normalize_quote_fields
接受（下游 K 线/WS 依赖同一契约）。

与期货的关键差异：
- 无 settlement_price / position（持仓量）：OKX ticker 不含，永续持仓量需
  另调 /api/v5/public/open-interest；本 Task 不取，quote_schema 会填 0。
- 涨跌幅基准用 sodUtc8（北京时区零点价），其次 sodUtc0，都没有则置 None
  （绝不用 last 充当基准，避免涨跌幅恒为 0）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("qihuo.okx.market")

_TICKERS_PATH = "/api/v5/market/tickers"

EXCHANGE_OKX = "OKX"


def _f(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value


def _i(raw: Any) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def ticker_to_quote(raw: dict[str, Any]) -> dict[str, Any] | None:
    """OKX ticker → 统一 quote dict；不可用返回 None"""
    inst_id = str(raw.get("instId") or "").strip()
    if not inst_id:
        return None

    last = _f(raw.get("last"))
    if last is None or last <= 0:
        return None

    symbol = inst_id.lower()
    code = symbol.split("-")[0].upper()

    # 基准价：北京零点优先，其次 UTC 零点
    pre = _f(raw.get("sodUtc8"))
    if pre is None or pre <= 0:
        pre = _f(raw.get("sodUtc0"))
    if pre is not None and pre <= 0:
        pre = None

    return {
        "symbol": symbol,
        "name": code,
        "exchange": EXCHANGE_OKX,
        "last_price": last,
        "open_price": pre if pre is not None else last,
        "high_price": _f(raw.get("high24h")) or last,
        "low_price": _f(raw.get("low24h")) or last,
        "pre_close": pre,
        "bid_price": _f(raw.get("bidPx")) or last,
        "ask_price": _f(raw.get("askPx")) or last,
        "bid_vol": _i(raw.get("bidSz")),
        "ask_vol": _i(raw.get("askSz")),
        "volume": _i(raw.get("vol24h")),
        "turnover": _f(raw.get("volCcy24h")),
        "tick_time": str(raw.get("ts") or ""),
        "trade_date": "",
    }


async def fetch_tickers(client: Any, inst_type: str = "SWAP") -> list[dict[str, Any]]:
    """拉取全市场 ticker 快照（一次请求覆盖全部品种）"""
    rows = await client.get(_TICKERS_PATH, {"instType": inst_type})
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        quote = ticker_to_quote(raw)
        if quote is not None:
            out.append(quote)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_okx_market.py -v`
Expected: PASS，8 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/connectors/okx/market.py backend/tests/test_okx_market.py
git commit -m "feat(okx): 新增 ticker 快照行情解析" \
  -m "- ticker_to_quote 输出统一 quote 契约，可被 quote_schema 归一化
- 涨跌幅基准用 sodUtc8 优先，缺失置 None 不造假 0
- 一次请求覆盖全市场，避免逐品种轮询"
```

---

### Task 7: OKX K 线接入

**Files:**
- Create: `backend/app/connectors/okx/kline.py`
- Test: `backend/tests/test_okx_kline.py`

**Interfaces:**
- Consumes: `OkxRestClient`（Task 4）
- Produces:
  - `BAR_MAP: dict[str, str]`（内部周期名 → OKX bar，如 `"1m" → "1m"`、`"60m" → "1H"`、`"1d" → "1D"`）
  - `def candle_to_bar(raw: list[str], symbol: str) -> dict | None`
  - `async def fetch_candles(client, symbol: str, bar: str = "1m", limit: int = 300, after: int | None = None) -> list[dict]`
  - `async def fetch_history_candles(client, symbol: str, bar: str = "1m", limit: int = 100, after: int | None = None) -> list[dict]`
  - bar dict 字段：`ts`(int, 毫秒)、`open`、`high`、`low`、`close`、`volume`、`open_interest`(恒 0)、`confirm`(bool)

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_okx_kline.py`：

```python
"""OKX K 线解析"""

import pytest

from app.connectors.okx import kline as ok


CANDLE = [
    "1791782400000", "61234.5", "61300.0", "61100.0", "61250.0",
    "1234", "75.6", "7560000", "1",
]

FORMING = [
    "1791782460000", "61250.0", "61280.0", "61240.0", "61270.0",
    "12", "0.7", "70000", "0",
]


def test_bar_map_covers_all_periods():
    assert ok.BAR_MAP["1m"] == "1m"
    assert ok.BAR_MAP["5m"] == "5m"
    assert ok.BAR_MAP["15m"] == "15m"
    assert ok.BAR_MAP["30m"] == "30m"
    assert ok.BAR_MAP["60m"] == "1H"
    assert ok.BAR_MAP["4h"] == "4H"
    assert ok.BAR_MAP["1d"] == "1D"


def test_candle_to_bar_maps_ohlcv():
    bar = ok.candle_to_bar(CANDLE, "btc-usdt-swap")
    assert bar is not None
    assert bar["ts"] == 1791782400000
    assert bar["open"] == 61234.5
    assert bar["high"] == 61300.0
    assert bar["low"] == 61100.0
    assert bar["close"] == 61250.0
    assert bar["volume"] == 1234


def test_candle_confirm_flag():
    assert ok.candle_to_bar(CANDLE, "btc-usdt-swap")["confirm"] is True
    assert ok.candle_to_bar(FORMING, "btc-usdt-swap")["confirm"] is False


def test_candle_open_interest_is_zero():
    """OKX candle 不含持仓量；因子层对 has_oi=False 已置零，不得造数"""
    bar = ok.candle_to_bar(CANDLE, "btc-usdt-swap")
    assert bar["open_interest"] == 0


def test_candle_returns_none_on_short_row():
    assert ok.candle_to_bar(CANDLE[:5], "btc-usdt-swap") is None


def test_candle_returns_none_on_bad_number():
    bad = list(CANDLE)
    bad[1] = "abc"
    assert ok.candle_to_bar(bad, "btc-usdt-swap") is None


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def get(self, path, params=None):
        self.calls.append((path, params))
        return self._payload


@pytest.mark.asyncio
async def test_fetch_candles_uses_market_path_and_limit():
    client = _FakeClient([CANDLE, FORMING])
    bars = await ok.fetch_candles(client, "btc-usdt-swap", "1m", limit=300)
    assert len(bars) == 2
    path, params = client.calls[0]
    assert path == "/api/v5/market/candles"
    assert params["instId"] == "BTC-USDT-SWAP"
    assert params["bar"] == "1m"
    assert params["limit"] == "300"


@pytest.mark.asyncio
async def test_fetch_candles_clamps_limit_to_300():
    """/market/candles 上限 300，超出必须夹取"""
    client = _FakeClient([])
    await ok.fetch_candles(client, "btc-usdt-swap", "1m", limit=5000)
    assert client.calls[0][1]["limit"] == "300"


@pytest.mark.asyncio
async def test_fetch_history_candles_clamps_limit_to_100():
    client = _FakeClient([])
    await ok.fetch_history_candles(client, "btc-usdt-swap", "1m", limit=500)
    path, params = client.calls[0]
    assert path == "/api/v5/market/history-candles"
    assert params["limit"] == "100"


@pytest.mark.asyncio
async def test_fetch_candles_unknown_period_raises():
    client = _FakeClient([])
    with pytest.raises(ValueError):
        await ok.fetch_candles(client, "btc-usdt-swap", "7m")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_okx_kline.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.connectors.okx.kline'`

- [ ] **Step 3: 写实现**

创建 `backend/app/connectors/okx/kline.py`：

```python
"""OKX K 线 REST —— 近期 + 历史

OKX candle 行格式（全部为字符串）：
  [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
confirm="1" 表示该根已收盘，"0" 为形成中。

两个端点限额不同，必须分别夹取：
- /api/v5/market/candles       最近数据，单次上限 300
- /api/v5/market/history-candles 更早数据，单次上限 100
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("qihuo.okx.kline")

_CANDLES_PATH = "/api/v5/market/candles"
_HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"

_CANDLES_MAX = 300
_HISTORY_MAX = 100

# 内部周期名 → OKX bar 参数
BAR_MAP: dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
    "1w": "1W",
}

_CANDLE_FIELDS = 9


def _f(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def candle_to_bar(raw: list[Any], symbol: str) -> dict[str, Any] | None:
    """OKX candle 行 → bar dict；不可用返回 None"""
    if not isinstance(raw, list) or len(raw) < _CANDLE_FIELDS:
        return None

    ts = _f(raw[0])
    o = _f(raw[1])
    h = _f(raw[2])
    low = _f(raw[3])
    c = _f(raw[4])
    vol = _f(raw[5])
    if None in (ts, o, h, low, c, vol):
        return None

    return {
        "symbol": str(symbol or "").lower(),
        "ts": int(ts),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": int(vol),
        # OKX candle 不提供持仓量；因子层对 has_oi=False 整体置零，
        # 这里恒填 0 以保持字段存在（不造伪信号）
        "open_interest": 0,
        "confirm": str(raw[8]) == "1",
    }


def _resolve_bar(bar: str) -> str:
    okx_bar = BAR_MAP.get(str(bar or "").strip())
    if okx_bar is None:
        raise ValueError(f"不支持的 K 线周期：{bar}")
    return okx_bar


def _params(symbol: str, okx_bar: str, limit: int, after: int | None) -> dict[str, str]:
    params = {
        "instId": str(symbol or "").strip().upper(),
        "bar": okx_bar,
        "limit": str(limit),
    }
    if after is not None:
        params["after"] = str(int(after))
    return params


async def fetch_candles(
    client: Any,
    symbol: str,
    bar: str = "1m",
    limit: int = _CANDLES_MAX,
    after: int | None = None,
) -> list[dict[str, Any]]:
    """拉取近期 K 线（单次上限 300）"""
    okx_bar = _resolve_bar(bar)
    capped = max(1, min(int(limit), _CANDLES_MAX))
    rows = await client.get(_CANDLES_PATH, _params(symbol, okx_bar, capped, after))
    return [
        parsed
        for raw in rows
        if isinstance(raw, list) and (parsed := candle_to_bar(raw, symbol)) is not None
    ]


async def fetch_history_candles(
    client: Any,
    symbol: str,
    bar: str = "1m",
    limit: int = _HISTORY_MAX,
    after: int | None = None,
) -> list[dict[str, Any]]:
    """拉取更早的 K 线（单次上限 100，配合 after 向前翻页）"""
    okx_bar = _resolve_bar(bar)
    capped = max(1, min(int(limit), _HISTORY_MAX))
    rows = await client.get(
        _HISTORY_CANDLES_PATH, _params(symbol, okx_bar, capped, after)
    )
    return [
        parsed
        for raw in rows
        if isinstance(raw, list) and (parsed := candle_to_bar(raw, symbol)) is not None
    ]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_okx_kline.py -v`
Expected: PASS，11 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/connectors/okx/kline.py backend/tests/test_okx_kline.py
git commit -m "feat(okx): 新增 K 线 REST 接入（近期+历史）" \
  -m "- BAR_MAP 映射内部周期到 OKX bar（60m→1H/1d→1D）
- 两个端点限额分别夹取（candles 300 / history-candles 100）
- confirm 标志透传，形成中的末根可被下游识别
- 持仓量恒 0，配合因子层 has_oi=False 降级"
```

---

### Task 8: OKX WS 实时行情

**Files:**
- Create: `backend/app/connectors/okx/ws.py`
- Test: `backend/tests/test_okx_ws.py`

**Interfaces:**
- Consumes: `ticker_to_quote`（Task 6）
- Produces:
  - `OKX_PUBLIC_WS: str = "wss://ws.okx.com:8443/ws/v5/public"`
  - `def subscribe_args(symbols: list[str], channels: list[str]) -> list[dict[str, str]]`
  - `def parse_ws_message(msg: dict) -> tuple[str, dict] | None`（返回 `(channel, payload)`）
  - `class OkxPublicWs`，方法 `async def run(self, symbols: list[str], on_quote) -> None`、`async def stop(self) -> None`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_okx_ws.py`：

```python
"""OKX 公开 WS 订阅与消息解析"""

from app.connectors.okx import ws as ok


def test_subscribe_args_shape():
    args = ok.subscribe_args(["btc-usdt-swap", "eth-usdt-swap"], ["tickers"])
    assert args == [
        {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
        {"channel": "tickers", "instId": "ETH-USDT-SWAP"},
    ]


def test_subscribe_args_multi_channel():
    args = ok.subscribe_args(["btc-usdt-swap"], ["tickers", "books5"])
    assert len(args) == 2
    assert {a["channel"] for a in args} == {"tickers", "books5"}


def test_subscribe_args_empty_symbols():
    assert ok.subscribe_args([], ["tickers"]) == []


def test_parse_ticker_message():
    msg = {
        "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
        "data": [{"instId": "BTC-USDT-SWAP", "last": "61234.5"}],
    }
    parsed = ok.parse_ws_message(msg)
    assert parsed is not None
    channel, payload = parsed
    assert channel == "tickers"
    assert payload["instId"] == "BTC-USDT-SWAP"


def test_parse_books5_message():
    msg = {
        "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
        "data": [{"asks": [["61235", "1", "0", "1"]], "bids": [["61234", "2", "0", "1"]], "ts": "1"}],
    }
    parsed = ok.parse_ws_message(msg)
    assert parsed is not None
    assert parsed[0] == "books5"


def test_parse_ignores_event_and_error_frames():
    assert ok.parse_ws_message({"event": "subscribe", "arg": {"channel": "tickers"}}) is None
    assert ok.parse_ws_message({"event": "error", "code": "60012", "msg": "bad"}) is None


def test_parse_ignores_frame_without_data():
    assert ok.parse_ws_message({"arg": {"channel": "tickers"}, "data": []}) is None


def test_parse_ignores_frame_without_arg():
    assert ok.parse_ws_message({"data": [{"instId": "X"}]}) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_okx_ws.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.connectors.okx.ws'`

- [ ] **Step 3: 写实现**

创建 `backend/app/connectors/okx/ws.py`：

```python
"""OKX 公开 WebSocket —— tickers / books5 / trades

公开频道无需登录。订阅信封：
  {"op": "subscribe", "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]}

断线重连由本模块负责；上层只需提供 on_quote 回调。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import websockets

from app.connectors.okx.market import ticker_to_quote

logger = logging.getLogger("qihuo.okx.ws")

OKX_PUBLIC_WS = "wss://ws.okx.com:8443/ws/v5/public"

# 重连退避（秒）
_RECONNECT_MIN = 1.0
_RECONNECT_MAX = 30.0

# 服务端要求 30 秒内至少一次心跳
_PING_INTERVAL = 20.0

QuoteCallback = Callable[[dict[str, Any]], Awaitable[None]]


def subscribe_args(symbols: list[str], channels: list[str]) -> list[dict[str, str]]:
    """构造订阅 args（symbol 转 OKX instId 大写）"""
    return [
        {"channel": channel, "instId": str(symbol).strip().upper()}
        for channel in channels
        for symbol in symbols
        if str(symbol or "").strip()
    ]


def parse_ws_message(msg: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """解析数据帧 → (channel, 首条数据)；事件帧/错误帧/空数据返回 None"""
    if not isinstance(msg, dict):
        return None
    arg = msg.get("arg")
    if not isinstance(arg, dict):
        return None
    data = msg.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    return str(arg.get("channel") or ""), first


class OkxPublicWs:
    """公开行情 WS 长连接，带指数退避重连"""

    def __init__(self, url: str = OKX_PUBLIC_WS) -> None:
        self._url = url
        self._stop = asyncio.Event()
        self._channels: list[str] = ["tickers"]

    async def stop(self) -> None:
        self._stop.set()

    async def _send_subscribe(self, ws: Any, args: list[dict[str, str]]) -> None:
        await ws.send(json.dumps({"op": "subscribe", "args": args}))

    async def _handle(self, raw: str, on_quote: QuoteCallback) -> None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(msg, dict) and msg.get("event") == "error":
            logger.warning("OKX WS 错误帧：%s", msg)
            return
        parsed = parse_ws_message(msg)
        if parsed is None:
            return
        channel, payload = parsed
        if channel != "tickers":
            return
        quote = ticker_to_quote(payload)
        if quote is None:
            return
        await on_quote(quote)

    async def run(self, symbols: list[str], on_quote: QuoteCallback) -> None:
        """持续运行直到 stop()；每次断线按指数退避重连"""
        args = subscribe_args(symbols, self._channels)
        if not args:
            logger.warning("OKX WS 无订阅标的，退出")
            return

        backoff = _RECONNECT_MIN
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    await self._send_subscribe(ws, args)
                    logger.info("OKX WS 已连接，订阅 %d 个频道", len(args))
                    backoff = _RECONNECT_MIN
                    while not self._stop.is_set():
                        try:
                            raw = await asyncio.wait_for(
                                ws.recv(), timeout=_PING_INTERVAL
                            )
                        except asyncio.TimeoutError:
                            await ws.send("ping")
                            continue
                        await self._handle(raw, on_quote)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("OKX WS 断开（%.0fs 后重连）：%s", backoff, exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, _RECONNECT_MAX)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_okx_ws.py -v`
Expected: PASS，8 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/connectors/okx/ws.py backend/tests/test_okx_ws.py
git commit -m "feat(okx): 新增公开 WebSocket 行情接入" \
  -m "- subscribe_args 构造 OKX 订阅信封
- parse_ws_message 过滤事件帧/错误帧，只透传数据帧
- 指数退避重连 + 20 秒心跳，避免被服务端断开
- 复用 ticker_to_quote，WS 与 REST 同源同契约"
```

---

### Task 9: 行情写入 Redis 与端到端验证

**Files:**
- Create: `backend/app/services/okx_quote_service.py`
- Modify: `backend/app/main.py`（启动 WS 行情任务）
- Modify: `backend/app/connectors/okx/__init__.py`（导出）
- Test: `backend/tests/test_okx_quote_service.py`

**Interfaces:**
- Consumes: `OkxPublicWs`（Task 8）、`fetch_tickers`（Task 6）、`market_keys`（既有）
- Produces:
  - `class OkxQuoteService`，方法 `async def start(self, symbols: list[str]) -> None`、`async def stop(self) -> None`、`async def snapshot_once(self) -> int`
  - 写入的 Redis 键：`market:live:quote:{symbol}` 与 `market:live:source:okx:quote:{symbol}`（复用既有 `market_keys`）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_okx_quote_service.py`：

```python
"""OKX 行情写入 Redis —— 键名与既有 market_keys 契约一致"""

import json

import pytest

from app.services.market_keys import quote_key, source_quote_key
from app.services.okx_quote_service import OkxQuoteService


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value


def _quote(symbol="btc-usdt-swap", last=61234.5):
    return {
        "symbol": symbol,
        "name": "BTC",
        "exchange": "OKX",
        "last_price": last,
        "pre_close": 60000.0,
        "bid_price": last,
        "ask_price": last,
        "bid_vol": 1,
        "ask_vol": 1,
        "volume": 10,
        "open_price": last,
        "high_price": last,
        "low_price": last,
        "tick_time": "1791782400000",
        "trade_date": "",
    }


@pytest.mark.asyncio
async def test_write_quote_uses_live_namespace():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis)
    await svc.write_quote(_quote())

    unified = quote_key("live", "btc-usdt-swap")
    source = source_quote_key("okx", "btc-usdt-swap")
    assert unified in redis.store
    assert source in redis.store


@pytest.mark.asyncio
async def test_written_payload_is_normalized():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis)
    await svc.write_quote(_quote())

    payload = json.loads(redis.store[quote_key("live", "btc-usdt-swap")])
    assert payload["symbol"] == "btc-usdt-swap"
    assert payload["last_price"] == 61234.5
    # quote_schema 归一化会补 position 字段
    assert payload["position"] == 0


@pytest.mark.asyncio
async def test_invalid_quote_is_skipped():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis)
    written = await svc.write_quote({"symbol": "", "last_price": 0})
    assert written is False
    assert redis.store == {}


class _FakeClient:
    async def get(self, path, params=None):
        return [
            {"instId": "BTC-USDT-SWAP", "last": "61234.5", "bidPx": "1", "askPx": "2",
             "bidSz": "1", "askSz": "1", "high24h": "2", "low24h": "0.5",
             "vol24h": "10", "volCcy24h": "1", "sodUtc8": "60000", "ts": "1"},
        ]


@pytest.mark.asyncio
async def test_snapshot_once_writes_all_tickers():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis, client=_FakeClient())
    count = await svc.snapshot_once()
    assert count == 1
    assert quote_key("live", "btc-usdt-swap") in redis.store
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/test_okx_quote_service.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.okx_quote_service'`

- [ ] **Step 3: 写实现**

创建 `backend/app/services/okx_quote_service.py`：

```python
"""OKX 行情写入 Redis —— WS 增量 + REST 快照兜底

写入两个键（与既有 market_keys 契约一致）：
- market:live:quote:{symbol}           统一报价（下游唯一读入口）
- market:live:source:okx:quote:{symbol} 原始源快照（收盘/断线时兜底）

quote 必须先过 normalize_quote_fields：下游 K 线/WS/前端都按该契约读字段。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.connectors.okx.client import OkxRestClient
from app.connectors.okx.market import fetch_tickers
from app.connectors.okx.ws import OkxPublicWs
from app.data.quote_schema import normalize_quote_fields
from app.services.market_keys import quote_key, source_quote_key

logger = logging.getLogger("qihuo.okx.quote")

# 统一报价键 TTL：OKX 24/7，10 分钟无更新视为过期
_QUOTE_TTL = 600

SOURCE_OKX = "okx"
MODE_LIVE = "live"

# REST 快照兜底间隔（秒）
_SNAPSHOT_INTERVAL = 60.0


class OkxQuoteService:
    """把 OKX 行情写进 Redis 的 live 命名空间"""

    def __init__(
        self,
        redis_conn: Any,
        client: OkxRestClient | None = None,
        ws: OkxPublicWs | None = None,
    ) -> None:
        self._redis = redis_conn
        self._client = client or OkxRestClient()
        self._ws = ws or OkxPublicWs()
        self._tasks: list[asyncio.Task] = []

    async def write_quote(self, quote: dict[str, Any]) -> bool:
        """归一化并写入 Redis；无效 quote 返回 False"""
        normalized = normalize_quote_fields(quote)
        if normalized is None:
            return False
        symbol = normalized["symbol"]
        payload = json.dumps(normalized, ensure_ascii=False)
        try:
            await self._redis.set(
                quote_key(MODE_LIVE, symbol), payload, ex=_QUOTE_TTL
            )
            await self._redis.set(
                source_quote_key(SOURCE_OKX, symbol), payload, ex=_QUOTE_TTL
            )
        except Exception as exc:
            logger.warning("OKX 报价写入 Redis 失败 %s：%s", symbol, exc)
            return False
        return True

    async def snapshot_once(self) -> int:
        """REST 全市场快照（WS 未覆盖或断线时的兜底）"""
        written = 0
        for inst_type in ("SWAP", "SPOT"):
            try:
                quotes = await fetch_tickers(self._client, inst_type)
            except Exception as exc:
                logger.warning("OKX %s 快照拉取失败：%s", inst_type, exc)
                continue
            for quote in quotes:
                if await self.write_quote(quote):
                    written += 1
        return written

    async def _snapshot_loop(self) -> None:
        while True:
            try:
                count = await self.snapshot_once()
                logger.info("OKX 快照兜底完成：%d 条", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("OKX 快照兜底异常：%s", exc)
            await asyncio.sleep(_SNAPSHOT_INTERVAL)

    async def start(self, symbols: list[str]) -> None:
        """启动 WS 增量 + REST 快照兜底两个任务"""
        self._tasks = [
            asyncio.create_task(
                self._ws.run(symbols, self.write_quote), name="okx-ws-quote"
            ),
            asyncio.create_task(self._snapshot_loop(), name="okx-snapshot"),
        ]
        logger.info("OKX 行情服务已启动：WS %d 个标的 + REST 快照兜底", len(symbols))

    async def stop(self) -> None:
        await self._ws.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_okx_quote_service.py -v`
Expected: PASS，4 passed

- [ ] **Step 5: 在 main.py 启动行情服务**

修改 `backend/app/main.py` lifespan，在品种表注入之后加入：

```python
    # OKX 行情服务：WS 增量 + REST 快照兜底
    from app.data.instruments import all_instruments
    from app.services.okx_quote_service import OkxQuoteService

    okx_quotes = OkxQuoteService(redis_conn, client=okx_client)
    symbols = [i.symbol for i in all_instruments()][:200]
    if symbols:
        await okx_quotes.start(symbols)
    else:
        logger.warning("OKX 品种表为空，行情服务未启动")
    application.state.okx_quotes = okx_quotes
```

关闭段加入：

```python
    await okx_quotes.stop()
```

- [ ] **Step 6: 端到端验证（真实 OKX 网络）**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
APP_ENV=production uv run uvicorn app.main:app --host 0.0.0.0 --port 8008 2>&1 | tee /tmp/okx-e2e.log &
sleep 25
echo "--- 健康检查 ---"
curl -s http://127.0.0.1:8008/health | head -c 400; echo
echo "--- 真实 OKX 报价（Redis）---"
redis-cli -p 6379 --scan --pattern 'market:live:source:okx:*' | head -5
redis-cli -p 6379 get market:live:quote:btc-usdt-swap | head -c 300; echo
```

Expected:
- `/health` 返回 `status: ok`
- Redis 中存在 `market:live:source:okx:quote:*` 键
- `market:live:quote:btc-usdt-swap` 返回含真实价格的 JSON

- [ ] **Step 7: 停止进程并 Commit**

```bash
pkill -f "uvicorn app.main:app"
cd /Users/hc/Documents/ai/factor-mining-experiment
git add -A
git commit -m "feat(okx): 行情写入 Redis 并接入启动流程" \
  -m "- OkxQuoteService 统一 WS 增量与 REST 快照兜底
- 复用 market_keys 的 live 命名空间与 source 键
- 报价先过 normalize_quote_fields，保证下游契约一致
- main.py 启动时按品种表订阅 WS"
```

---

## Phase 3-5 — 后续计划（范围与交付物）

> **这三个阶段各自是独立子系统，按 writing-plans 的 Scope Check 应各自单独出计划。**
> 下面给出范围、任务边界与验收标准，供后续按同样粒度展开。

### Plan 2：交易模型适配（预计 2-3 周）

**前置：** Phase 0-2 完成（品种表 + 行情可用）

| Task | 内容 | 验收 |
|---|---|---|
| 2.1 | 24/7 时段完整化：`trading_hours.py` 覆盖多周期边界、取消收盘打印语义 | `period_end_for_product` 对 1m/5m/15m/30m/60m/1d 全部边界正确 |
| 2.2 | 合约乘数接入：`paper/order_fill.py:31` 的 `calc_margin` 改读 `Instrument.contract_value` | 永续保证金 = price × qty × ctVal × rate，与 OKX 逐位对齐 |
| 2.3 | 数量精度：`lot_size` / `min_qty` 校验替换期货整数手 | 下单 0.001 BTC 可成交；低于 minSz 被拒 |
| 2.4 | 价格精度：`round_by_tick` 接入委托价 | 委托价始终是 tickSz 整数倍 |
| 2.5 | 费率模型：taker/maker bps 接入既有 `fee_mode=rate` | 开平手续费与 OKX 费率表一致 |
| 2.6 | 双向持仓：`PaperPosition.direction` long/short 语义对齐 OKX 双向持仓模式 | 同 symbol 可同时持多空 |
| 2.7 | 价格带：`paper/price_band.py` ±10% 改为 OKX 涨跌停规则（或取消） | 带外委托被拒 |
| 2.8 | DB 迁移：`paper_*` 表新增 `market` 维度（默认 `okx`） | 存量数据回填成功，唯一约束不冲突 |

### Plan 3：前端适配（预计 1-2 周）

**前置：** Plan 2 的 API 契约冻结

| Task | 内容 | 验收 |
|---|---|---|
| 3.1 | 移除期货 UI 文案（`frontend/src` 中 19 个文件含「期货」） | 全站无期货字样 |
| 3.2 | 品种树改 OKX 结构（无交易所/无交割月，改为 base/quote 分组） | 品种选择器列出真实 OKX 品种 |
| 3.3 | 数量输入改小数（当前为整数手） | 可输入 0.001 |
| 3.4 | 24/7 交易状态（去掉夜盘/休市提示） | 任何时刻显示「交易中」 |
| 3.5 | K 线图确认周期映射（60m→1H 等） | 各周期渲染正确 |

### Plan 4：部署与运维（预计 3-5 天）

| Task | 内容 | 验收 |
|---|---|---|
| 4.1 | `docker-compose.yml` 移除 CTP/VVTR/sina-bridge 服务 | `docker compose config` 无期货服务 |
| 4.2 | 新增 OKX 行情容器（或并入 backend） | 容器 healthy |
| 4.3 | `.env.example` 重写为 OKX 变量 | 无期货变量残留 |
| 4.4 | 私有 API 鉴权（下单）：HMAC-SHA256 + passphrase | 可查询账户余额 |

---

## 验证基线

每个 Task 结束跑：

```bash
cd backend && uv run pytest tests/test_okx_instruments.py tests/test_okx_instruments_fetch.py \
  tests/test_okx_market.py tests/test_okx_kline.py tests/test_okx_ws.py \
  tests/test_okx_quote_service.py tests/test_import_clean.py -v
```

Phase 2 结束跑全量 + 端到端：

```bash
cd backend && uv run pytest -q
curl -s http://127.0.0.1:8008/health
redis-cli -p 6379 get market:live:quote:btc-usdt-swap
```

## 风险与未决

| 风险 | 影响 | 缓解 |
|---|---|---|
| Phase 0 删除后大量测试失败 | 无法用「全绿」判断进度 | 以 `test_import_clean.py` 为阶段门；期货测试同步删除 |
| `contract_master` 调用点语义不明 | 8 处需逐个判断，可能误删 | Task 5 Step 4 要求逐条分类，不批量 sed |
| OKX 限速（candles 40 次/2s） | 批量拉 K 线可能被拒 | Task 9 用一次全市场 ticker 替代逐品种轮询；K 线拉取需加节流（Plan 2 处理） |
| 品种表首次拉取失败 | 启动后无行情 | 已设计为不阻塞启动 + 60 秒快照重试 |
| 稀疏检出甩掉 `.venv`/`node_modules` | 需重建，耗时 | Task 1 Step 7 显式检查并重建 |
| 私有接口（下单）未评估 | Plan 4 工作量不确定 | 明确排除在 Phase 0-2 外 |

## 明确排除

- OKX 私有 API（下单/撤单/持仓/账户）—— 仅公开行情
- 实盘资金接入与风控
- A股市场（本次只做 OKX）
- 期货代码的删除是**分支内删除**，`main` 分支不受影响，可随时回退
