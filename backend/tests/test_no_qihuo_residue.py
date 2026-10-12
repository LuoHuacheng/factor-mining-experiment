import re
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


def test_docker_compose_no_qihuo_containers_or_networks():
    """验证 docker-compose.yml 和 docker-compose.local.yml 无 qihuo container_name 与 qihuo-net 网络"""
    repo_root = Path(__file__).resolve().parents[2]
    compose_files = [
        repo_root / "docker-compose.yml",
        repo_root / "docker-compose.local.yml",
    ]

    for compose_path in compose_files:
        assert compose_path.is_file(), f"{compose_path} 不存在"
        with open(compose_path, "r", encoding="utf-8") as f:
            compose_data = yaml.safe_load(f) or {}

        # 1. 验证所有 service 的 container_name 不包含 qihuo
        services = compose_data.get("services", {})
        for svc_name, svc_cfg in services.items():
            if not isinstance(svc_cfg, dict):
                continue
            container_name = svc_cfg.get("container_name", "")
            assert "qihuo" not in str(container_name).lower(), (
                f"{compose_path.name}: 服务 '{svc_name}' 的 container_name '{container_name}' 包含 'qihuo'"
            )
            # 验证 service 关联的 networks 中无 qihuo-net
            svc_networks = svc_cfg.get("networks", [])
            if isinstance(svc_networks, list):
                for net in svc_networks:
                    assert net != "qihuo-net", f"{compose_path.name}: 服务 '{svc_name}' 引用了 'qihuo-net'"
            elif isinstance(svc_networks, dict):
                assert "qihuo-net" not in svc_networks, f"{compose_path.name}: 服务 '{svc_name}' 引用了 'qihuo-net'"

        # 2. 验证顶层 networks 不包含 qihuo-net
        top_networks = compose_data.get("networks", {})
        if isinstance(top_networks, dict):
            assert "qihuo-net" not in top_networks, f"{compose_path.name}: 顶层 networks 包含 'qihuo-net'"

        # 3. 文本行扫描确保无遗漏
        lines = compose_path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("container_name:"):
                assert "qihuo" not in stripped.lower(), (
                    f"{compose_path.name}:{idx} container_name 包含 'qihuo': {stripped}"
                )
            assert "qihuo-net" not in stripped, (
                f"{compose_path.name}:{idx} 包含遗留网络名 'qihuo-net': {stripped}"
            )


def test_frontend_src_qihuo_restricted_and_no_active_routes_or_keys():
    """验证 frontend/src/ 中任何 qihuo 出现均严格限制于 LEGACY_* 常量或 regex 兼容 replace，无活跃主键或路由"""
    repo_root = Path(__file__).resolve().parents[2]
    frontend_src = repo_root / "frontend" / "src"
    assert frontend_src.is_dir(), f"{frontend_src} 不存在"

    # 1. 验证没有任何 Next.js App Router 路由路径包含 qihuo
    frontend_app = frontend_src / "app"
    route_violations = []
    for file_path in frontend_app.rglob("*"):
        rel_str = str(file_path.relative_to(frontend_app))
        if "qihuo" in rel_str.lower():
            route_violations.append(str(file_path.relative_to(repo_root)))
    assert not route_violations, (
        f"在前端路由路径中发现 'qihuo' 残留：\n" + "\n".join(route_violations)
    )

    # 2. 验证所有 frontend/src 源码中的 qihuo 出现均严格限制在 LEGACY_* 常量、regex 兼容 replace、或内联脚本兜底
    allowed_patterns = [
        re.compile(r"\bLEGACY_[A-Z0-9_]*\s*="),
        re.compile(r"export\s+const\s+LEGACY_[A-Z0-9_]*\s*="),
        re.compile(r"\.replace\(\s*(?:/\^?qihuo-?/?|['\"]qihuo)"),
        re.compile(r"\.replace\(\s*/\^?app-?/?\s*,\s*['\"]qihuo-?['\"]"),
        re.compile(r"var\s+lk\s*=\s*['\"]qihuo_font_size['\"]"),
    ]

    unrestricted_violations = []
    active_key_violations = []

    for file_path in frontend_src.rglob("*"):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        if file_path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".json", ".css"}:
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            if "qihuo" not in line.lower():
                continue

            rel_file = str(file_path.relative_to(repo_root))
            line_str = line.strip()

            # 检查是否匹配被允许的向下兼容模式
            is_allowed = any(p.search(line_str) for p in allowed_patterns)
            if not is_allowed:
                unrestricted_violations.append(f"{rel_file}:{line_no}: {line_str}")

            # 额外验证：绝不能是活跃的主键声明 (非 LEGACY_ 前缀的 KEY)
            active_key_match = re.search(
                r"(?:const|let|var)\s+((?!LEGACY_)[A-Z0-9_]*KEY)\s*=\s*['\"]([^'\"]*qihuo[^'\"]*)['\"]",
                line_str,
            )
            if active_key_match:
                active_key_violations.append(
                    f"{rel_file}:{line_no}: 活跃主键 '{active_key_match.group(1)}' 包含 qihuo"
                )

            # 额外验证：活跃的 URL 路由跳转或 API 请求路径不能包含 qihuo
            route_call_match = re.search(
                r"""(?:href|push|replace|fetch)\s*(?:\(\s*|\=\s*)['"`](/[^'"`]*qihuo[^'"`]*)['"`]""",
                line_str,
                re.IGNORECASE,
            )
            if route_call_match:
                active_key_violations.append(
                    f"{rel_file}:{line_no}: 活跃路由路径包含 qihuo: {route_call_match.group(1)}"
                )

    assert not unrestricted_violations, (
        f"在 frontend/src/ 中发现 {len(unrestricted_violations)} 处非兼容兜底的未授权 'qihuo'：\n"
        + "\n".join(unrestricted_violations)
    )
    assert not active_key_violations, (
        f"在 frontend/src/ 中发现活跃主键或路由违规项：\n"
        + "\n".join(active_key_violations)
    )
