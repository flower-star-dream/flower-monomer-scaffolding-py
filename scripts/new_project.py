#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新建项目重命名脚本（new_project）

@Author: 花海
@Date: 2026/08/16
@Description: 从脚手架生成新项目：全局替换项目名 / 仓库名 / Python 包名 / 数据库名 / 版本 / 作者，
              重命名 src/app 目录、覆盖 README.md、删除 scripts/ 自身目录。
              使用场景（详见 docs/创建新项目.md）：
                1) 推荐：GitHub "Use this template" 创建新仓库（全新 git 历史）→ clone → 本脚本重命名；
                2) 手动：git clone 脚手架 → rm -rf .git → git init → 本脚本重命名（--git-init 可自动提交）。
              用法：python scripts/new_project.py new <project-name> [options]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 脚手架固有标识（将被替换为新项目参数）
# ---------------------------------------------------------------------------
TEMPLATE_ORG_REPO = "flower-star-dream/flower-monomer-scaffolding-py"  # GitHub org/repo 完整引用
TEMPLATE_REPO_NAME = "flower-monomer-scaffolding-py"                   # 仓库名
TEMPLATE_PROJECT_NAME = "flower-monomer-scaffolding"                   # 项目名（pyproject/app.name/镜像名）
TEMPLATE_DB_NAME = "flower_monomer"                                    # 默认数据库名
TEMPLATE_VERSION = "0.1.0"                                             # 脚手架当前版本
TEMPLATE_AUTHOR = "花海"                                               # 脚手架作者

# 运行时实例属性（app 为 FastAPI 实例变量，不是包名，替换时必须原样保留）
APP_INSTANCE_ATTRS: Tuple[str, ...] = ("state", "include_router", "routes", "url_path_for")

# 需要文本替换的扩展名 / 文件名（白名单，避免触碰二进制与构建缓存）
TEXT_SUFFIXES: Tuple[str, ...] = (
    ".py", ".toml", ".yml", ".yaml", ".ini", ".sql", ".md", ".sh", ".txt", ".json", ".mako",
)
TEXT_FILENAMES: Tuple[str, ...] = ("Dockerfile", ".env.example", ".gitignore", ".dockerignore", "LICENSE")

# 遍历时忽略的目录（构建产物 / 版本控制 / 虚拟环境）
IGNORED_DIRS: Tuple[str, ...] = (".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache")

# 脚手架专属内容（生成新项目时排除：CLI 脚本 / CLI 测试 / 设计文档 / 构建产物）
TEMPLATE_ONLY_PREFIXES: Tuple[str, ...] = (
    "scripts",
    "docs/superpowers",
    "tests/test_new_project.py",
    "docs/创建新项目.md",
)
TEMPLATE_ONLY_GLOBS: Tuple[str, ...] = ("*.egg-info",)

# 模板仓库根目录（由脚本位置推断，不依赖运行目录）
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    返回:
        含 project_name 与全部可选参数的 Namespace。
    """
    parser = argparse.ArgumentParser(
        prog="new_project",
        description="从 flower-monomer-scaffolding 脚手架生成新项目（全局重命名 + 覆盖 README + 删除脚本自身）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    new_cmd = sub.add_parser("new", help="生成新项目")
    new_cmd.add_argument("project_name", help="新项目名，如 my-project（用于 pyproject/README/镜像名/GHCR 仓库名）")
    new_cmd.add_argument("--package", help="Python 包名（默认：项目名转 snake_case，如 my-project -> my_project）")
    new_cmd.add_argument("--db", choices=("mysql", "sqlite"), default="mysql", help="默认数据库类型（默认 mysql）")
    new_cmd.add_argument("--db-name", help="数据库名（默认：项目名转 snake_case）")
    new_cmd.add_argument("--org", default="flower-star-dream", help="GitHub 组织名（默认 flower-star-dream，替换 README 徽章链接）")
    new_cmd.add_argument("--version", default=TEMPLATE_VERSION, help="初始版本号（默认 0.1.0）")
    new_cmd.add_argument("--author", help="作者名（替换 @Author: 花海 与 pyproject authors；缺省不替换）")
    new_cmd.add_argument(
        "--dir",
        help="目标输出目录（提供则从当前模板目录复制到目标后重命名，模板目录保持不动；缺省原地重命名）",
    )
    new_cmd.add_argument("--git-init", action="store_true", help="自动执行 git init + 首次提交（手动 clone 方式使用）")
    return parser.parse_args(argv)


def _derive_names(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生重命名所需参数。

    Args:
        args: 解析后的命令行参数。

    Returns:
        派生结果字典：project_name / repo_name / package / db_name。

    Raises:
        SystemExit: 项目名或包名非法时退出。
    """
    project = args.project_name.strip()
    # GitHub 仓库名规则：字母/数字开头，仅含字母/数字/连字符/下划线/点，禁止连续点、点/连字符结尾、.git 结尾
    if (
        not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", project)
        or project.endswith((".", "-"))
        or ".." in project
        or project.lower().endswith(".git")
    ):
        sys.exit(
            f"非法项目名：{project!r}（须为合法仓库名：字母/数字开头，仅含字母/数字/连字符/下划线/点，"
            "禁止连续点、点/连字符结尾与 .git 结尾）"
        )

    repo = project.lower()
    package = args.package or re.sub(r"[^a-zA-Z0-9]", "_", project).lower().strip("_")
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", package):
        sys.exit(
            f"非法 Python 包名：{package!r}（由项目名推断，可改用 --package 指定，须匹配 [a-zA-Z_][a-zA-Z0-9_]*）"
        )
    db_name = args.db_name or re.sub(r"[^a-zA-Z0-9]", "_", project).lower()
    return {
        "project_name": project,
        "repo_name": repo,
        "package": package,
        "db_name": db_name,
        "org": args.org,
        "version": args.version,
        "author": args.author,
        "db_type": args.db,
        "git_init": args.git_init,
        "target_dir": args.dir,
    }


def _protect_app_instances(text: str) -> Tuple[str, List[Tuple[int, str]]]:
    """将运行时实例属性 app.<attr> 替换为占位符，避免包名替换误伤。

    Args:
        text: 原文。

    Returns:
        (占位后的文本, 占位记录列表[(索引, 属性名)])。
    """
    records: List[Tuple[int, str]] = []
    for attr in APP_INSTANCE_ATTRS:
        marker = f"@@FLOWER_APP_INSTANCE_{attr}@@"
        text = text.replace(f"app.{attr}", marker)
        records.append((0, attr))  # 索引仅为保持结构，恢复按属性名替换
    return text, records


def _restore_app_instances(text: str, records: List[Tuple[int, str]]) -> str:
    """将占位符恢复为原实例属性 app.<attr>。"""
    for _, attr in records:
        text = text.replace(f"@@FLOWER_APP_INSTANCE_{attr}@@", f"app.{attr}")
    return text


def _apply_text_replacements(text: str, names: Dict[str, str]) -> str:
    """对单个文本文件内容执行全部重命名替换。

    Args:
        text: 文件原文。
        names: 派生参数（_derive_names 返回值）。

    Returns:
        替换后的文本。
    """
    # 1) 先占位保护运行时实例属性
    text, records = _protect_app_instances(text)
    # 2) 先长串后短串替换（避免子串互相误伤）
    text = text.replace(f"{names['org']}/{TEMPLATE_REPO_NAME}", f"{names['org']}/{names['repo_name']}")
    text = text.replace(TEMPLATE_REPO_NAME, names["repo_name"])
    text = text.replace(TEMPLATE_PROJECT_NAME, names["project_name"])
    text = text.replace(TEMPLATE_DB_NAME, names["db_name"])
    # 3) import 模块引用 app. -> <package>.（运行时实例属性已被占位保护）
    text = re.sub(r"\bapp\.", f"{names['package']}.", text)
    # 4) 版本号与作者（可选）
    text = text.replace(TEMPLATE_VERSION, names["version"])
    if names["author"]:
        text = text.replace(f"@Author: {TEMPLATE_AUTHOR}", f"@Author: {names['author']}")
    # 5) 恢复运行时实例属性
    text = _restore_app_instances(text, records)
    return text


def _is_template_only(rel_path: str) -> bool:
    """判断相对路径是否属于脚手架专属内容（生成新项目时应排除）。"""
    if any(rel_path == prefix or rel_path.startswith(prefix + "/") for prefix in TEMPLATE_ONLY_PREFIXES):
        return True
    if any(Path(rel_path).name.endswith(suffix) for suffix in TEMPLATE_ONLY_GLOBS):
        return True
    return False


def _iter_text_files(root: Path) -> Iterable[Path]:
    """遍历模板目录中的文本文件（跳过忽略目录与脚手架专属内容）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and d != "scripts"]
        for name in filenames:
            path = Path(dirpath) / name
            rel = str(path.relative_to(root)).replace("\\", "/")
            if _is_template_only(rel):
                continue
            if name in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def _remove_template_only_paths(root: Path) -> None:
    """删除脚手架专属内容（脚本 / CLI 测试 / 设计文档 / 构建产物），新项目不再需要。"""
    for egg_info in root.rglob("*.egg-info"):
        shutil.rmtree(egg_info, ignore_errors=True)
    for rel in TEMPLATE_ONLY_PREFIXES:
        target = root / rel
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()


def _rename_package_dir(root: Path, package: str) -> None:
    """将 src/app 目录重命名为 src/<package>。"""
    app_dir = root / "src" / "app"
    if app_dir.exists():
        app_dir.rename(root / "src" / package)


def _apply_db_type(root: Path, db_type: str) -> None:
    """按 --db 参数修改 application.yml 的 app.db.type。"""
    if db_type == "mysql":
        return
    yml_path = root / "application.yml"
    if not yml_path.exists():
        return
    content = yml_path.read_text(encoding="utf-8")
    # application.yml 中 db 段唯一使用 type: mysql
    updated = content.replace("type: mysql", "type: sqlite", 1)
    if updated != content:
        yml_path.write_text(updated, encoding="utf-8")


def _render_readme(names: Dict[str, str]) -> str:
    """渲染新项目初始化 README。"""
    repo_url = f"https://github.com/{names['org']}/{names['repo_name']}"
    db_label = "MySQL（默认）" if names["db_type"] == "mysql" else "SQLite（默认）"
    return f"""# {names['project_name']}

[![version](https://img.shields.io/badge/version-v{names['version']}-blue)]({repo_url})
[![python](https://img.shields.io/badge/python-3.10%2B-blue)]({repo_url})
[![license](https://img.shields.io/badge/license-MIT-green)]({repo_url})
[![CI](https://img.shields.io/github/actions/workflow/status/{names['org']}/{names['repo_name']}/ci.yml?label=CI&logo=github)]({repo_url}/actions)

> 基于 [flower-web-infrastructure](https://github.com/flower-star-dream/flower-web-infrastructure) 的单体应用，
> 由 [flower-monomer-scaffolding](https://github.com/flower-star-dream/flower-monomer-scaffolding-py) 脚手架生成。

| 项目     | 值                                        |
| -------- | ----------------------------------------- |
| 当前版本 | v{names['version']}                       |
| Python   | >= 3.10                                   |
| 依赖框架 | flower-web-infrastructure                 |
| 数据库   | {db_label} / SQLite                       |

## 快速开始

```bash
# 1) 创建虚拟环境（Windows）
python -m venv .venv
.venv\\Scripts\\activate

# 2) 安装框架依赖（默认 Git 远程拉取，不假设本机有框架仓库；本机已 clone 框架时可改本地 editable）
pip install "flower-web-infrastructure[mysql,redis,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"

# 3) 安装项目自身（业务包 + 开发依赖）
pip install -e ".[dev]"

# 4) 复制 .env.example 为 .env 并填写敏感配置，然后启动
uvicorn {names['package']}.main:app --host 0.0.0.0 --port 8000 --reload
```

> 详细说明见 [docs/使用说明.md](docs/使用说明.md)；CI/CD 见 [docs/CI-CD.md](docs/CI-CD.md)。

## 目录结构

```
{names['project_name']}/
├── application.yml               # 应用配置（项目根，MySQL 默认；敏感值用 ${{ENV:default}} 占位符）
├── .env.example                  # 本地敏感配置模板（复制为 .env 填写；.env 不提交仓库）
├── pyproject.toml                # 项目配置（框架依赖方式二选一，见注释）
├── alembic/                      # Alembic 权威迁移
├── db/                           # 手工 SQL（基线 init + 增量 versions）
├── src/{names['package']}/       # 业务包
├── tests/                        # pytest 测试（SQLite 内存库）
└── docs/                         # 使用说明 / CI/CD 文档
```

## 扩展新业务模块

参照 [docs/使用说明.md](docs/使用说明.md) 第 6 节：model → schema → repository → service → api 分层新增。
"""


def _git_init_and_commit(root: Path, project_name: str) -> None:
    """执行 git init + 首次提交（--git-init 时调用）。"""
    try:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore: 从 flower-monomer-scaffolding 脚手架初始化 {project_name} 项目"],
            cwd=root, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"git 初始化失败：{exc.stderr.decode(errors='replace').strip() or exc}")


def _prepare_target(names: Dict[str, str]) -> Path:
    """确定处理目录：原地重命名或复制到目标目录。

    Args:
        names: 派生参数。

    Returns:
        待处理的目标根目录。
    """
    if not names["target_dir"]:
        return PROJECT_ROOT
    target = Path(names["target_dir"])
    if target.exists() and any(target.iterdir()):
        sys.exit(f"目标目录已存在且非空：{target}")
    shutil.copytree(
        PROJECT_ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache", "*.pyc",
            *TEMPLATE_ONLY_PREFIXES, *TEMPLATE_ONLY_GLOBS,
        ),
    )
    return target


def _run(names: Dict[str, str]) -> Path:
    """执行重命名主流程（在目标目录内完成全部替换）。

    Args:
        names: 派生参数。

    Returns:
        处理完成的目标根目录。
    """
    root = _prepare_target(names)
    for path in _iter_text_files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 二进制或不可读文件跳过
        updated = _apply_text_replacements(content, names)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
    _rename_package_dir(root, names["package"])
    _apply_db_type(root, names["db_type"])
    (root / "README.md").write_text(_render_readme(names), encoding="utf-8")
    _remove_template_only_paths(root)
    if names["git_init"]:
        _git_init_and_commit(root, names["project_name"])
    return root


def _print_summary(names: Dict[str, str], root: Path) -> None:
    """输出生成结果与下一步指引。"""
    git_hint = "（已执行 git init + 首次提交）" if names["git_init"] else ""
    print("=" * 60)
    print(f"新项目已生成：{names['project_name']}  {git_hint}")
    print(f"  目录：{root}")
    print(f"  项目名：{names['project_name']}")
    print(f"  Python 包：src/{names['package']}")
    print(f"  数据库：{names['db_name']}（{names['db_type']}）")
    print(f"  版本：{names['version']}")
    print("=" * 60)
    print("下一步：")
    print(f"  1. cd {root}")
    print('  2. python -m venv .venv && .venv\\Scripts\\activate')
    print('  3. pip install "flower-web-infrastructure[mysql,redis,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"')
    print('  4. pip install -e ".[dev]"')
    print("  5. 复制 .env.example 为 .env 并填写敏感配置")
    print(f"  6. uvicorn {names['package']}.main:app --host 0.0.0.0 --port 8000 --reload")


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口。"""
    args = _parse_args(argv)
    if args.command != "new":
        sys.exit("未知子命令，仅支持 new")
    names = _derive_names(args)
    root = _run(names)
    _print_summary(names, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
