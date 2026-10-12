import subprocess
from pathlib import Path
import yaml


def test_backend_app_has_no_qihuo():
    """验证 backend/app/ 目录中零 'qihuo' 出现（大小写不敏感）"""
    repo_root = Path(__file__).resolve().parents[2]
    backend_app = repo_root / "backend" / "app"
    assert backend_app.is_dir(), f"{backend_app} 不存在"

    violations = []
    for file_path in backend_app.rglob("*"):
        if file_path.is_file() and not file_path.name.startswith("."):
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(content.splitlines(), start=1):
                if "qihuo" in line.lower():
                    rel_path = file_path.relative_to(repo_root)
                    violations.append(f"{rel_path}:{line_no}: {line.strip()}")

    assert not violations, (
        f"在 backend/app/ 发现 {len(violations)} 处 'qihuo' 残留：\n"
        + "\n".join(violations[:20])
    )


def test_frontend_src_has_no_qihuo():
    """验证 frontend/src/ 目录中零 'qihuo' 出现（包含没有任何 LEGACY_ 残留）"""
    repo_root = Path(__file__).resolve().parents[2]
    frontend_src = repo_root / "frontend" / "src"
    assert frontend_src.is_dir(), f"{frontend_src} 不存在"

    violations = []
    for file_path in frontend_src.rglob("*"):
        if file_path.is_file() and not file_path.name.startswith("."):
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(content.splitlines(), start=1):
                if "qihuo" in line.lower():
                    rel_path = file_path.relative_to(repo_root)
                    violations.append(f"{rel_path}:{line_no}: {line.strip()}")

    assert not violations, (
        f"在 frontend/src/ 发现 {len(violations)} 处 'qihuo' 残留：\n"
        + "\n".join(violations[:20])
    )


def test_compose_and_env_has_no_qihuo():
    """验证 docker-compose.yml、docker-compose.local.yml 与 .env.example 零 'qihuo' 出现"""
    repo_root = Path(__file__).resolve().parents[2]
    target_files = [
        repo_root / "docker-compose.yml",
        repo_root / "docker-compose.local.yml",
        repo_root / ".env.example",
    ]

    violations = []
    for file_path in target_files:
        assert file_path.is_file(), f"{file_path} 不存在"
        content = file_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            if "qihuo" in line.lower():
                violations.append(f"{file_path.name}:{line_no}: {line.strip()}")

    assert not violations, (
        f"在编排与环境配置文件中发现 {len(violations)} 处 'qihuo' 残留：\n"
        + "\n".join(violations[:20])
    )


def test_codebase_zero_qihuo_outside_docs():
    """验证全代码库（除历史 docs 与本测试文件外）绝对零 'qihuo' 残留"""
    repo_root = Path(__file__).resolve().parents[2]
    res = subprocess.run(
        ["git", "grep", "-i", "-n", "qihuo"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]

    # 白名单：仅允许历史归档文档和测试断言自身
    allowed_prefixes = (
        "docs/",
        "backend/tests/test_no_qihuo_residue.py",
        "backend/tests/test_logger_clean.py",
    )

    violations = []
    for line in lines:
        file_path = line.split(":", 1)[0]
        if not any(file_path.startswith(prefix) for prefix in allowed_prefixes):
            violations.append(line)

    assert not violations, (
        f"全代码库发现 {len(violations)} 处违规 'qihuo' 残留：\n"
        + "\n".join(violations[:20])
    )
