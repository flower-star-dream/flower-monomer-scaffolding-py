# 设计文档：从脚手架创建新项目（Template 仓库 + 内置重命名脚本）

> @Author: 花海
> @Date: 2026/08/16
> @Description: 脚手架派生新项目的方案设计：GitHub Template repository + 仓库内置单文件重命名脚本，
>               解决"新仓库用新 git（不继承脚手架历史）"与"拉取脚手架后改造"两大诉求。

## 1. 背景与目标

脚手架仓库 `flower-monomer-scaffolding-py` 用于快速复制业务项目，但缺少以下能力：

1. 新仓库如何用全新 git 历史（不被脚手架本身 git 历史覆盖）；
2. 如何拉取脚手架引用（clone / fork）后在其基础上改造；
3. 能否有命令行工具按参数（项目名等）自动完成改造。

目标：

- 提供一条零安装、零长命令的派生路径；
- 自动完成项目名 / 包名 / 数据库名 / 作者 / 版本 的全局重命名；
- 新项目 git 历史天然全新（不继承脚手架历史）；
- 文档覆盖手动方式与推荐方式。

## 2. 方案选型

| 方案 | 结论 |
| ---- | ---- |
| pip 安装 console script（flower-new，git clone + 重命名 + git init） | 弃用：安装命令长（`pip install git+...`），且 git 历史问题可被 GitHub 原生能力解决 |
| cookiecutter / copier 模板 | 弃用：需引入依赖，破坏脚手架"目录即真实项目"形态 |
| **GitHub Template repository + 内置单文件脚本** | **采用**：GitHub 原生"Use this template"生成全新 git 历史（零继承）；`scripts/new_project.py` 单文件（Python 标准库）完成重命名，零安装 |

## 3. 总体设计

### 3.1 形态

- 脚手架仓库为 GitHub **Template repository**（是否开启属仓库管理员职责，不在用户文档范围，用户文档只写 "Use this template" 使用方式）。
- 仓库内置 `scripts/new_project.py`：单文件、Python 标准库（argparse / re / shutil / pathlib / subprocess），**零第三方依赖**。
- 无 console script、无 pip 安装需求、无 `src/scaffold_cli` 包。

### 3.2 用户使用路径（两种）

**方式一（推荐）：Use this template**

```bash
# 1) GitHub 上点 "Use this template" 创建新仓库（GitHub 生成全新 git 历史，不继承脚手架提交）
# 2) clone 新仓库到本地
git clone https://github.com/<org>/<new-repo>.git
cd <new-repo>
# 3) 运行重命名脚本（原地重命名，自动删除 scripts/ 自身）
python scripts/new_project.py new my-project
# 4) 按输出提示安装依赖、配置 .env、启动
```

**方式二（手动）：clone 脚手架后清 git 历史**

```bash
git clone https://github.com/flower-star-dream/flower-monomer-scaffolding-py.git my-project
cd my-project
rm -rf .git            # 关键：删除脚手架 git 历史
git init               # 新仓库全新历史
python scripts/new_project.py new my-project   # 重命名（默认原地；脚本会删除 scripts/ 自身）
git add . && git commit -m "chore: 从脚手架初始化 my-project"
```

> 说明：方式二更适用于无法使用 Template 的场景（如仓库未开启 Template、需要本地离线生成）。

### 3.3 脚本运行方式

```bash
python scripts/new_project.py new <project-name> [options]
python scripts/new_project.py --help
```

- 默认**原地重命名**：在模板目录（clone 后的脚手架/新仓库）内运行，原地替换文件内容、重命名 `src/app` 目录、覆盖 README、最后删除 `scripts/` 自身目录。
- 可选 `--dir <target>`：复制到目标目录再重命名（模板目录保持不动）。
- 可选 `--git-init`：手动方式下自动执行 `git init + 首次提交`（推荐方式无需，Template 已给新 git）。

## 4. 命令与参数

| 参数 | 必填 | 默认 | 说明 |
| ---- | ---- | ---- | ---- |
| `project-name` | 是 | — | 新项目名（如 `my-project`），用于 pyproject / README / 镜像名 / GHCR 仓库名 |
| `--package` | 否 | 项目名转 snake_case | Python 包名（`src/<package>`） |
| `--db mysql\|sqlite` | 否 | `mysql` | 默认数据库类型（sqlite 时改 `application.yml` 的 `app.db.type`） |
| `--db-name` | 否 | 项目名转 snake_case | 数据库名（替换 `flower_monomer`） |
| `--org` | 否 | `flower-star-dream` | GitHub 组织（替换 README 徽章链接；ci.yml 用 `github.repository` 自动跟随，无需改） |
| `--version` | 否 | `0.1.0` | 初始版本号 |
| `--author` | 否 | 不替换 | 作者（替换 `@Author: 花海` 与 pyproject authors） |
| `--dir` | 否 | 当前目录 | 目标输出目录（提供则复制生成，否则原地重命名） |
| `--git-init` | 否 | false | 自动 `git init` + 首次提交（手动 clone 方式使用） |

校验：`project-name` 必须是合法 Python 包名（`[a-zA-Z_][a-zA-Z0-9_]*` 允许连字符变体）与合法仓库名（小写字母数字连字符），非法即报错退出。

## 5. 重命名替换清单

替换顺序：先长串后短串（避免子串误伤）；运行时属性 `app.state` / `app.include_router` / `app.routes` / `app.url_path_for` 先占位保护、替换完成后再恢复（它们是小写 `app` 实例变量，非包名）。

| # | 查找 | 替换为 | 说明 |
| ---- | ---- | ---- | ---- |
| 1 | `flower-star-dream/flower-monomer-scaffolding-py` | `<org>/<repo>` | README 徽章、docs/CI-CD.md 的 GHCR 地址 |
| 2 | `flower-monomer-scaffolding-py` | `<repo>` | 目录树、docs 仓库名引用 |
| 3 | `flower-monomer-scaffolding` | `<project-name>` | pyproject name、application.yml、.env.example、ci.yml 镜像 tag（`:ci`/`:latest`）、docs |
| 4 | `flower_monomer` | `<db-name>` | .env.example、application.yml 默认值、alembic/env.py 错误提示、db/init SQL、README DATABASE_URL 示例 |
| 5 | `\bapp\.`（import 模块引用） | `<package>.` | `from app.` / `import app.` / 字符串 `"app.main:app"`；`app.state` 等实例属性先保护 |
| 6 | `src/app` 目录 | `src/<package>` | 目录重命名 |
| 7 | `0.1.0` | `<version>` | 仅版本上下文：pyproject `version`、application.yml `app.version`、README 徽章/表格、docs 标签示例 |
| 8 | `@Author: 花海` | `@Author: <author>` | 提供 `--author` 时全量替换 |
| — | 删除 `scripts/` 目录 | — | 脚本自身，新项目不再需要 |
| — | 删除 `.github/workflows/ci.yml` 中的脚手架特有注释 | — | 可选（ci.yml 逻辑用 `github.repository` 自动跟随，注释同步替换即可） |

**保留不动**：框架仓库地址 `flower-star-dream/flower-web-infrastructure`（依赖，新项目仍依赖框架）、`request.app.state` 等运行时访问、`create_app` / `application` 标识。

替换实现要点：

- 遍历模板全部文本文件（白名单扩展名：py/toml/yml/yaml/ini/sql/md/sh/yml 等，跳过 `.git`、`__pycache__`、`.venv`、二进制）。
- 步骤 5 前先执行占位：`app.state|app.include_router|app.routes|app.url_path_for` → `@@APP_INSTANCE_@@`，`\bapp\.` → `<package>.` 后再恢复为 `app.<attr>`。
- 目录重命名用 `os.rename`，`src/app` → `src/<package>`。

## 6. 新项目初始化 README 模板

脚本覆盖生成 `README.md`（`<...>` 为运行时变量）：

```markdown
# <project-name>

[![version](https://img.shields.io/badge/version-v<version>-blue)](https://github.com/<org>/<repo>)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/<org>/<repo>)
[![license](https://img.shields.io/badge/license-MIT-green)](https://github.com/<org>/<repo>)
[![CI](https://img.shields.io/github/actions/workflow/status/<org>/<repo>/ci.yml?label=CI&logo=github)](https://github.com/<org>/<repo>/actions)

> 基于 [flower-web-infrastructure](../../flower-web-infrastructure) 的单体应用，由
> [flower-monomer-scaffolding](https://github.com/flower-star-dream/flower-monomer-scaffolding-py) 脚手架生成。

| 项目 | 值 |
| ---- | -- |
| 当前版本 | v<version> |
| Python | >= 3.10 |
| 依赖框架 | flower-web-infrastructure |
| 数据库 | <db>（默认）/ SQLite |

## 快速开始
（venv + 框架依赖 [mysql,redis,migrate] + .env + 启动，指向 docs/使用说明.md）

## 目录结构
（简表，src/<package> 已替换）

## 文档
- docs/使用说明.md / docs/CI-CD.md
```

## 7. 脚手架仓库自身文档更新

1. **新建 `docs/创建新项目.md`**：
   - 推荐方式：Use this template → clone → `python scripts/new_project.py new my-project`；
   - 手动方式：clone → `rm -rf .git` → `git init` → 脚本重命名（讲清"新仓库用新 git、不继承脚手架历史"）；
   - 脚本参数表与重命名清单说明；
   - 常见问题：改了源码但 git 历史仍属脚手架怎么办（推荐 Template 重新生成或按方式二手动 init）；是否把脚手架更新同步过来（不建议，新项目独立演进）。
2. **README.md**：新增「从脚手架创建新项目」章节（指向 docs/创建新项目.md）。
3. **docs/使用说明.md**：章节指引指向新文档。
4. Template repository 开关由脚手架仓库管理员在 GitHub 配置，用户文档不含开启方法（属仓库管理职责，不在业务开发者文档范围）。

## 8. 测试与验证

- 新增 `tests/test_new_project.py`：用 `tmp_path` 构造迷你模板 fixture（含 `src/app/`、`application.yml`、`README.md`、含 `app.state` 的 py 文件），调用脚本重命名，断言：
  - 项目名 / 包名 / 数据库名已替换；
  - `app.state` / `app.include_router` 等运行时属性未被误替换；
  - `src/app` → `src/<package>` 目录已重命名；
  - `scripts/` 已删除、README 已覆盖；
  - 非法项目名报错。
- 手工验证：本地对脚手架副本运行 `python scripts/new_project.py new demo-project --dir <tmp>`，检查生成项目可 `pytest`、可 `uvicorn` 启动。
- CI：脚手架 test job 自动纳入新测试（`pytest -q`）。

## 9. 影响面与边界

- Dockerfile / ci.yml **无需改动**：脚本位于 `scripts/`，不进入镜像（Dockerfile 只 `COPY src`）；ci.yml 用 `github.repository` 自动跟随新仓库。
- 生成的新项目 ci.yml / Dockerfile / docs 开箱即用，仅首次推送前需在 GitHub 创建对应新仓库并设置镜像包可见性。
- 不引入任何第三方依赖；脚本本身遵循仓库注释规范（@Author / @Date / @Description）。
