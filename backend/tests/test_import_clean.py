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
