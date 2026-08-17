#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新建项目 / 升级脚本（new_project）

@Author: 花海
@Date: 2026/08/16
@Description: 脚手架生命周期管理：
    new <project-name>       从脚手架生成新项目：全局替换项目名 / 仓库名 / Python 包名 / 数据库名 /
                             版本 / 作者，重命名 src/app 目录、覆盖 README.md、删除 scripts/ 自身目录，
                             并在项目根写入 .scaffold-info.json（升级依据）。
                             组件与实现选择（框架全部能力）：交互式向导逐步询问，或
                             --components=name:impl,... 参数跳过（非交互/CI）；
                             未选组件配置段按标记块裁剪，选择 custom 生成自研 SPI 骨架。
    upgrade <project-dir>    将已生成项目同步到新版脚手架（三路合并 diff+patch）：模板未变不触碰、
                             模板变更且业务未改则更新、模板与业务都改则报告冲突；可一并指定框架版本升级。
    snapshot <version>       生成模板快照基线（发版流程：改 TEMPLATE_VERSION → snapshot → 提交）。
              使用场景（详见 docs/创建新项目.md）：
                1) 推荐：GitHub "Use this template" 创建新仓库（全新 git 历史）→ clone → 本脚本重命名；
                2) 手动：git clone 脚手架 → rm -rf .git → git init → 本脚本重命名（--git-init 可自动提交）。
              用法：python scripts/new_project.py new <project-name> [options]
                    python scripts/new_project.py upgrade <project-dir> [options]
                    python scripts/new_project.py snapshot <version>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# 加载同目录组件选择模块（组件目录 / 交互向导 / 标记块裁剪 / 自研骨架）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_components import (  # noqa: E402
    COMPONENTS,
    apply_capabilities_to_text,
    apply_components_to_text,
    generate_spi_skeletons,
    render_capabilities,
    render_extras,
    resolve_components,
)

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

# 脚手架专属内容（生成新项目时排除：CLI 脚本 / CLI 测试 / 设计文档 / 构建产物 / 模板快照历史）
TEMPLATE_ONLY_PREFIXES: Tuple[str, ...] = (
    "scripts",
    "scaffold",
    "docs/superpowers",
    "tests/test_new_project.py",
    "docs/创建新项目.md",
)
TEMPLATE_ONLY_GLOBS: Tuple[str, ...] = ("*.egg-info",)

# 项目根升级元数据（new 时写入业务项目，upgrade 读取作为版本与替换依据）
SCAFFOLD_INFO_FILE = ".scaffold-info.json"
# 模板快照基线目录（脚手架仓库内，发版时 snapshot <version> 生成）
VERSIONS_ROOT = "scaffold/versions"
# 框架标识与安装 extras（upgrade --framework-version 时生成升级命令）
FRAMEWORK_NAME = "flower-web-infrastructure"
FRAMEWORK_EXTRAS = "mysql,redis,migrate"
FRAMEWORK_GIT_URL = "https://github.com/flower-star-dream/flower-web-infrastructure.git"
# 业务文件（new 时被覆盖 / 业务专属，不参与模板三路合并，upgrade 提示手工比对）
BUSINESS_ONLY_FILES: Tuple[str, ...] = ("README.md",)

# 模板仓库根目录（由脚本位置推断，不依赖运行目录）
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    返回:
        含 project_name 与全部可选参数的 Namespace。
    """
    parser = argparse.ArgumentParser(
        prog="new_project",
        description="脚手架生命周期管理：new 生成新项目 / upgrade 升级已生成项目 / snapshot 生成模板快照",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    new_cmd = sub.add_parser("new", help="生成新项目")
    new_cmd.add_argument("project_name", help="新项目名，如 my-project（用于 pyproject/README/镜像名/GHCR 仓库名）")
    new_cmd.add_argument("--package", help="Python 包名（默认：项目名转 snake_case，如 my-project -> my_project）")
    new_cmd.add_argument("--db", choices=("mysql", "sqlite"), default=None, help="默认数据库类型（默认随组件选择，如 --components=db:mysql；等价于 --components=db:<type>）")
    new_cmd.add_argument("--db-name", help="数据库名（默认：项目名转 snake_case）")
    new_cmd.add_argument("--org", default="flower-star-dream", help="GitHub 组织名（默认 flower-star-dream，替换 README 徽章链接）")
    new_cmd.add_argument("--version", default=TEMPLATE_VERSION, help="初始版本号（默认 0.1.0）")
    new_cmd.add_argument("--author", help="作者名（替换 @Author: 花海 与 pyproject authors；缺省不替换）")
    new_cmd.add_argument(
        "--components",
        help="组件与实现选择（逗号分隔 name:impl，如 cache:redis,mq:rocketmq,registry:nacos；"
        "all=全部默认 / none=仅必选组件；缺省时交互式逐个询问，非交互环境默认全部默认值）。"
        f"可用组件：{'、'.join(COMPONENTS)}；注册中心禁止内存实现",
    )
    new_cmd.add_argument(
        "--dir",
        help="目标输出目录（提供则从当前模板目录复制到目标后重命名，模板目录保持不动；缺省原地重命名）",
    )
    new_cmd.add_argument("--git-init", action="store_true", help="自动执行 git init + 首次提交（手动 clone 方式使用）")

    upgrade_cmd = sub.add_parser("upgrade", help="升级已生成项目到新版脚手架（三路合并，模板同步 + 框架版本）")
    upgrade_cmd.add_argument("project_dir", help="目标业务项目根目录（含 .scaffold-info.json）")
    upgrade_cmd.add_argument("--to", dest="to_version", help="目标脚手架版本（默认当前模板版本）")
    upgrade_cmd.add_argument(
        "--framework-version",
        dest="framework_version",
        help="目标框架版本（如 0.2.0），提供则更新 .scaffold-info.json 并输出框架升级命令",
    )
    upgrade_cmd.add_argument(
        "--components",
        help="覆盖组件与实现选择（默认沿用项目 .scaffold-info.json 记录；none 表示仅必选组件）",
    )
    upgrade_cmd.add_argument("--dry-run", action="store_true", help="只预览变更，不写盘")

    snap_cmd = sub.add_parser("snapshot", help="生成模板快照基线（发版流程使用）")
    snap_cmd.add_argument("version", help="版本号（如 0.2.0，生成到 scaffold/versions/v<version>/）")
    return parser.parse_args(argv)


def _derive_names(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生重命名所需参数。

    Args:
        args: 解析后的命令行参数。

    Returns:
        派生结果字典：project_name / repo_name / package / db_name / db_type / components。

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
    # 组件与实现选择：--components 显式 > 交互式询问（TTY）> 非交互默认；
    # 单体脚手架注册中心默认不使用（可选 Nacos），内存实现一律禁止
    components = resolve_components(args.components)
    if args.db:
        components["db"] = args.db
    return {
        "project_name": project,
        "repo_name": repo,
        "package": package,
        "db_name": db_name,
        "org": args.org,
        "version": args.version,
        "author": args.author,
        "db_type": components["db"],
        "components": components,
        "git_init": args.git_init,
        "target_dir": args.dir,
    }


def _derive_upgrade_args(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生升级参数。

    Args:
        args: 解析后的命令行参数。

    Returns:
        派生结果字典：project_dir / to_version / framework_version / components / dry_run。
    """
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.is_dir():
        sys.exit(f"项目目录不存在：{project_dir}")
    to_version = args.to_version or TEMPLATE_VERSION
    if not re.fullmatch(r"\d+\.\d+\.\d+", to_version):
        sys.exit(f"非法版本号：{to_version!r}（须为 x.y.z，如 0.2.0）")
    if args.framework_version and not re.fullmatch(r"\d+\.\d+\.\d+", args.framework_version):
        sys.exit(f"非法框架版本号：{args.framework_version!r}（须为 x.y.z，如 0.2.0）")
    return {
        "project_dir": str(project_dir),
        "to_version": to_version,
        "framework_version": args.framework_version,
        "components": args.components,
        "dry_run": args.dry_run,
    }


def _derive_snapshot_args(args: argparse.Namespace) -> Dict[str, str]:
    """校验并派生快照参数。"""
    version = args.version.strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"非法版本号：{version!r}（须为 x.y.z，如 0.2.0）")
    return {"version": version}


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
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS
            and not d.endswith(".egg-info")
            and d not in ("scripts", "scaffold")
        ]
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


def _apply_db_type_to_text(content: str, db_type: str) -> str:
    """将 application.yml 文本的 app.db.type 由 mysql 改为 sqlite（内存处理，供 new/upgrade 复用）。"""
    if db_type == "mysql":
        return content
    # application.yml 中 db 段唯一使用 type: mysql
    return content.replace("type: mysql", "type: sqlite", 1)


def _apply_db_type(root: Path, db_type: str) -> None:
    """按 --db / 组件选择修改 application.yml 的 app.db.type（旧模板兜底）。

    说明：新模板 db 段由组件标记块处理（mysql/sqlite 块内替换、orm_custom/custom 保留默认）；
    本函数仅对旧模板（无组件标记块）兜底，且只处理真实 type 值（mysql/sqlite），
    策略型实现（orm_custom/custom）不触发 legacy 替换。
    """
    if db_type not in ("mysql", "sqlite"):
        return
    yml_path = root / "application.yml"
    if not yml_path.exists():
        return
    updated = _apply_db_type_to_text(yml_path.read_text(encoding="utf-8"), db_type)
    yml_path.write_text(updated, encoding="utf-8")


def _render_readme(names: Dict[str, str]) -> str:
    """渲染新项目初始化 README（含组件选择结果与按选择的框架 extras）。"""
    repo_url = f"https://github.com/{names['org']}/{names['repo_name']}"
    db_labels = {
        "mysql": "MySQL（默认）",
        "sqlite": "SQLite（默认）",
        "orm_custom": "基于框架 ORM 自定义",
        "custom": "完全自定义（自研 DatabaseSessionInterface）",
    }
    db_label = db_labels.get(names["db_type"], names["db_type"])
    extras = render_extras(names["components"])
    component_rows = "\n".join(
        f"| {COMPONENTS[name]['label']} | {_impl_label(name, names['components'][name])} |"
        for name in COMPONENTS
        if names["components"].get(name) not in (None, "off")
    )
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

## 启用的组件（脚手架生成时选择）

| 组件     | 实现                                    |
| -------- | --------------------------------------- |
{component_rows}

## 快速开始

```bash
# 1) 创建虚拟环境（Windows）
python -m venv .venv
.venv\\Scripts\\activate

# 2) 安装框架依赖（extras 按组件选择生成；默认 Git 远程拉取，本机已 clone 框架时可改本地 editable）
pip install "flower-web-infrastructure[{extras}] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"

# 3) 安装项目自身（业务包 + 开发依赖）
pip install -e ".[dev]"

# 4) 复制 .env.example 为 .env 并填写敏感配置，然后启动
uvicorn {names['package']}.main:app --host 0.0.0.0 --port 8000 --reload
```

> 详细说明见 [docs/使用说明.md](docs/使用说明.md)；CI/CD 见 [docs/CI-CD.md](docs/CI-CD.md)。

## 目录结构

```
{names['project_name']}/
├── application.yml               # 应用配置（项目根，仅含所选组件配置段；敏感值用 ${{ENV:default}} 占位符）
├── .env.example                  # 本地敏感配置模板（复制为 .env 填写；.env 不提交仓库）
├── pyproject.toml                # 项目配置（框架依赖方式二选一，见注释）
├── alembic/                      # Alembic 权威迁移
├── db/                           # 手工 SQL（基线 init + 增量 versions）
├── src/{names['package']}/       # 业务包（选择自研 SPI 时含 spi/ 骨架目录）
├── tests/                        # pytest 测试（SQLite 内存库）
└── docs/                         # 使用说明 / CI/CD 文档
```

## 扩展新业务模块

参照 [docs/使用说明.md](docs/使用说明.md) 第 6 节：model → schema → repository → service → api 分层新增。
"""


def _impl_label(name: str, impl: str) -> str:
    """返回组件实现的中文说明（供 README 组件表使用）。"""
    spec = COMPONENTS[name]
    for opt in spec["options"]:
        if opt["id"] == impl:
            return opt["label"]
    return impl


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
    """执行重命名主流程（在目标目录内完成全部替换与组件裁剪）。

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
        # 按组件选择裁剪：移除未选组件标记块 + 替换已选组件实现占位符
        updated = apply_components_to_text(updated, names["components"])
        # 能力依赖装配段（app.capabilities.enabled）按组件选择渲染
        updated = apply_capabilities_to_text(updated, names["components"])
        if updated != content:
            path.write_text(updated, encoding="utf-8")
    _rename_package_dir(root, names["package"])
    _apply_db_type(root, names["db_type"])
    # 选择 custom（自研 SPI）的组件生成骨架文件到 src/<package>/spi/
    names["custom_spis"] = generate_spi_skeletons(root, names["package"], names["components"])
    (root / "README.md").write_text(_render_readme(names), encoding="utf-8")
    _remove_template_only_paths(root)
    _save_scaffold_info(root, names)
    if names["git_init"]:
        _git_init_and_commit(root, names["project_name"])
    return root


# ---------------------------------------------------------------------------
# 升级（upgrade）：三路合并 diff+patch
# ---------------------------------------------------------------------------


def _save_scaffold_info(root: Path, names: Dict[str, str]) -> None:
    """在项目根写入 .scaffold-info.json（记录脚手架版本、替换参数与组件选择，升级依据）。"""
    info = {
        "scaffold": TEMPLATE_REPO_NAME,
        "scaffold_version": TEMPLATE_VERSION,
        "framework": FRAMEWORK_NAME,
        "framework_pin": None,
        "components": names.get("components") or {},
        "params": {
            key: names.get(key)
            for key in ("project_name", "repo_name", "package", "db_name", "db_type", "org", "version", "author")
        },
    }
    (root / SCAFFOLD_INFO_FILE).write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_scaffold_info(project_dir: Path) -> Dict[str, object]:
    """读取项目根 .scaffold-info.json 并校验脚手架类型。"""
    path = project_dir / SCAFFOLD_INFO_FILE
    if not path.exists():
        sys.exit(
            f"不是本脚手架生成的项目（缺少 {SCAFFOLD_INFO_FILE}）：{project_dir}\n"
            "升级仅支持由 new 命令生成的、保留了 .scaffold-info.json 的项目。"
        )
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        sys.exit(f"{SCAFFOLD_INFO_FILE} 解析失败：{exc}")
    if not isinstance(info, dict):
        sys.exit(f"{SCAFFOLD_INFO_FILE} 格式错误：顶层应为 JSON 对象")
    if info.get("scaffold") != TEMPLATE_REPO_NAME:
        sys.exit(
            f"脚手架类型不匹配：{info.get('scaffold')!r} ≠ {TEMPLATE_REPO_NAME!r}\n"
            "请使用对应脚手架的 scripts/new_project.py 执行升级。"
        )
    return info


def _map_template_path(rel_path: str, params: Dict[str, object]) -> str:
    """将模板相对路径映射为项目相对路径（含目录重命名 src/app -> src/<package>）。"""
    parts = rel_path.split("/")
    if len(parts) >= 2 and parts[0] == "src" and parts[1] == "app":
        return f"src/{params['package']}/" + "/".join(parts[2:])
    return rel_path


def _read_text_optional(path: Path) -> Optional[str]:
    """读取文本文件；不存在或无法按文本解码时返回 None。"""
    try:
        return path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return None


def _three_way_merge(base: Optional[str], ours: Optional[str], theirs: Optional[str]) -> str:
    """三路合并判定。

    Args:
        base: 旧版模板内容（已转项目形态）；None 表示旧模板无此文件。
        ours: 项目当前内容；None 表示项目无此文件。
        theirs: 新版模板内容（已转项目形态）；None 表示新模板已废弃此文件。

    Returns:
        动作：skip（不处理）/ update（用新版覆盖）/ add（新增文件）/
              remove（删除文件）/ conflict（模板与业务均改动，需手工处理）/
              missing（业务删除了模板文件，需人工确认）。
    """
    if base is None:
        if ours is None:
            return "add"
        if ours == theirs:
            return "skip"
        return "conflict"
    if theirs is None:
        if ours is None:
            return "skip"
        if ours == base:
            return "remove"
        return "conflict"
    if theirs == base:
        return "skip"
    if ours is None:
        return "missing"
    if ours == base:
        return "update"
    if ours == theirs:
        return "skip"
    return "conflict"


def _run_upgrade(names: Dict[str, str]) -> Dict[str, List[str]]:
    """执行升级主流程：三路合并模板文件并（可选）更新框架版本。

    Args:
        names: _derive_upgrade_args 返回值（project_dir / to_version / framework_version / dry_run）。

    Returns:
        统计结果：updated / added / removed / conflict / missing 文件相对路径列表。
    """
    project_dir = Path(names["project_dir"])
    info = _load_scaffold_info(project_dir)
    params: Dict[str, object] = dict(info["params"])
    # 组件选择：沿用项目记录（旧版项目无记录时按 params.db_type 派生）；--components 可覆盖
    components = _project_components(info, params)
    if names["components"] is not None:
        components = resolve_components(names["components"])
        if components.get("db") and params.get("db_type") != components["db"]:
            params["db_type"] = components["db"]
    old_ver = str(info.get("scaffold_version") or "")
    new_ver = names["to_version"]
    base_dir = PROJECT_ROOT / VERSIONS_ROOT / f"v{old_ver}"
    if not base_dir.is_dir():
        sys.exit(f"缺少旧版模板基线 {base_dir}：请先在脚手架仓库生成 v{old_ver} 快照后重试")

    # 模板文件集合：旧版基线 ∪ 当前模板（相对路径，模板形态）
    base_files = {str(p.relative_to(base_dir)).replace("\\", "/") for p in _iter_text_files(base_dir)}
    theirs_files = {str(p.relative_to(PROJECT_ROOT)).replace("\\", "/") for p in _iter_text_files(PROJECT_ROOT)}

    updated, added, removed, conflicts, missing = [], [], [], [], []
    for rel in sorted(base_files | theirs_files):
        if rel in BUSINESS_ONLY_FILES:
            continue
        proj_rel = _map_template_path(rel, params)
        base_proj = _to_project_text(base_dir / rel, params, components)
        theirs_proj = _to_project_text(PROJECT_ROOT / rel, params, components)
        ours_path = project_dir / proj_rel
        ours = _read_text_optional(ours_path)
        action = _three_way_merge(base_proj, ours, theirs_proj)
        if action == "update":
            updated.append(proj_rel)
            if not names["dry_run"]:
                ours_path.write_text(theirs_proj, encoding="utf-8", errors="surrogateescape")
        elif action == "add":
            added.append(proj_rel)
            if not names["dry_run"]:
                ours_path.parent.mkdir(parents=True, exist_ok=True)
                ours_path.write_text(theirs_proj, encoding="utf-8", errors="surrogateescape")
        elif action == "remove":
            removed.append(proj_rel)
            if not names["dry_run"]:
                ours_path.unlink()
        elif action == "conflict":
            conflicts.append(proj_rel)
        elif action == "missing":
            missing.append(proj_rel)

    if not names["dry_run"]:
        info["scaffold_version"] = new_ver
        info["components"] = components
        if names["framework_version"]:
            info["framework_pin"] = names["framework_version"]
        (project_dir / SCAFFOLD_INFO_FILE).write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return {"updated": updated, "added": added, "removed": removed,
            "conflict": conflicts, "missing": missing}


def _project_components(info: Dict[str, object], params: Dict[str, object]) -> Dict[str, str]:
    """返回项目的组件选择记录（旧版项目无 components 字段时按 params.db_type 派生默认）。"""
    base = resolve_components("all")
    comps = info.get("components")
    if isinstance(comps, dict):
        for name, impl in comps.items():
            if isinstance(impl, str) and impl:
                base[name] = impl
    if params.get("db_type"):
        base["db"] = str(params["db_type"])
    return base


def _to_project_text(template_path: Path, params: Dict[str, object], components: Optional[Dict[str, str]] = None) -> Optional[str]:
    """读取模板文件内容并应用替换映射转成项目形态（None 表示文件不存在）。"""
    content = _read_text_optional(template_path)
    if content is None:
        return None
    text = _apply_text_replacements(content, params)
    # 按项目组件选择裁剪：移除未选组件标记块 + 替换实现占位符
    if components:
        text = apply_components_to_text(text, components)
        # 能力依赖装配段（app.capabilities.enabled）按项目组件选择渲染
        text = apply_capabilities_to_text(text, components)
    # db_type=sqlite 时 application.yml 需同步转换（与 new 行为一致；旧模板无标记块时兜底）
    if params.get("db_type") == "sqlite" and template_path.name == "application.yml":
        text = _apply_db_type_to_text(text, "sqlite")
    return text


def _print_upgrade_summary(names: Dict[str, str], stats: Dict[str, List[str]]) -> None:
    """输出升级结果：已更新 / 新增 / 删除 / 冲突 / 缺失 清单与下一步。"""
    dry = "（dry-run 预览，未写盘）" if names["dry_run"] else ""
    print("=" * 60)
    print(f"脚手架升级完成 {dry}：{names['to_version']}")
    print(f"  已更新 {len(stats['updated'])} 个模板文件")
    for rel in stats["updated"]:
        print(f"    ~ {rel}")
    print(f"  新增 {len(stats['added'])} 个模板文件")
    for rel in stats["added"]:
        print(f"    + {rel}")
    print(f"  删除 {len(stats['removed'])} 个已废弃模板文件")
    for rel in stats["removed"]:
        print(f"    - {rel}")
    if stats["conflict"] or stats["missing"]:
        print(f"  !! 冲突 {len(stats['conflict'])} / 缺失 {len(stats['missing'])}，需手工处理（未被修改）")
        for rel in stats["conflict"]:
            print(f"    ! 冲突：{rel}（模板与业务均有改动，请手工合并）")
        for rel in stats["missing"]:
            print(f"    ? 缺失：{rel}（业务已删除该模板文件，请确认）")
    if names["framework_version"]:
        print("=" * 60)
        print(f"框架升级到 v{names['framework_version']}（已在 .scaffold-info.json 记录）：")
        print(f'  pip install "{FRAMEWORK_NAME}[{FRAMEWORK_EXTRAS}] @ git+{FRAMEWORK_GIT_URL}@v{names["framework_version"]}"')
    print("=" * 60)
    print("说明：")
    print("  - README.md 为业务文件，未自动同步，请手工比对模板。")
    print("  - 业务新增的模板外文件不受影响；升级前建议先提交当前改动（git commit）。")


# ---------------------------------------------------------------------------
# 快照（snapshot）：发版时生成模板基线
# ---------------------------------------------------------------------------


def _snapshot_ignore(src: str, names: List[str]) -> set:
    """copytree ignore 回调：按相对路径精确排除脚手架专属内容与运行产物。

    说明：shutil.ignore_patterns 无法匹配含路径分隔符的子路径模式（如 docs/superpowers，
    Windows 路径分隔符与模式不兼容），故按相对路径逐项判断。
    """
    ignored = set()
    src_path = Path(src)
    for name in names:
        rel = str((src_path / name).relative_to(PROJECT_ROOT)).replace("\\", "/")
        if (
            name in IGNORED_DIRS
            or name in ("data", "minio_data")
            or name.endswith((".pyc", ".egg-info"))
            or _is_template_only(rel)
        ):
            ignored.add(name)
    return ignored


def _run_snapshot(version: str) -> Path:
    """将当前模板拷贝为 scaffold/versions/v<version>/ 基线（供 upgrade 作为旧版对照）。"""
    target = PROJECT_ROOT / VERSIONS_ROOT / f"v{version}"
    if target.exists() and any(target.iterdir()):
        sys.exit(f"快照目录已存在且非空：{target}")
    target.mkdir(parents=True)
    shutil.copytree(PROJECT_ROOT, target, ignore=_snapshot_ignore, dirs_exist_ok=True)
    return target


def _print_snapshot_summary(version: str, target: Path) -> None:
    """输出快照生成结果与发版指引。"""
    print("=" * 60)
    print(f"模板快照已生成：v{version} -> {target}")
    print("发版流程：")
    print(f"  1. 确认 scripts/new_project.py 的 TEMPLATE_VERSION 已更新为 {version}")
    print(f"  2. 提交并推送 scaffold/versions/v{version}/ 与脚本变更")
    print(f"  3. 打 git tag v{version}（可选，便于追溯）")
    print("=" * 60)


def _print_summary(names: Dict[str, str], root: Path) -> None:
    """输出生成结果（含组件选择与自研骨架）与下一步指引。"""
    git_hint = "（已执行 git init + 首次提交）" if names["git_init"] else ""
    extras = render_extras(names["components"])
    components = names["components"]
    enabled = [name for name in COMPONENTS if components.get(name) not in (None, "off")]
    print("=" * 60)
    print(f"新项目已生成：{names['project_name']}  {git_hint}")
    print(f"  目录：{root}")
    print(f"  项目名：{names['project_name']}")
    print(f"  Python 包：src/{names['package']}")
    print(f"  数据库：{names['db_name']}（{names['db_type']}）")
    print(f"  版本：{names['version']}")
    print(f"  启用组件（{len(enabled)}）：{'、'.join(enabled)}")
    custom_spis = names.get("custom_spis") or []
    if custom_spis:
        print(f"  自研 SPI 骨架（src/{names['package']}/spi/）：{'、'.join(custom_spis)}")
    print("=" * 60)
    print("下一步：")
    print(f"  1. cd {root}")
    print('  2. python -m venv .venv && .venv\\Scripts\\activate')
    print(f'  3. pip install "flower-web-infrastructure[{extras}] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"')
    print('  4. pip install -e ".[dev]"')
    print("  5. 复制 .env.example 为 .env 并填写敏感配置")
    print(f"  6. uvicorn {names['package']}.main:app --host 0.0.0.0 --port 8000 --reload")


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口。"""
    args = _parse_args(argv)
    if args.command == "new":
        names = _derive_names(args)
        root = _run(names)
        _print_summary(names, root)
    elif args.command == "upgrade":
        names = _derive_upgrade_args(args)
        stats = _run_upgrade(names)
        _print_upgrade_summary(names, stats)
    elif args.command == "snapshot":
        names = _derive_snapshot_args(args)
        target = _run_snapshot(names["version"])
        _print_snapshot_summary(names["version"], target)
    else:
        sys.exit("未知子命令，仅支持 new / upgrade / snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
