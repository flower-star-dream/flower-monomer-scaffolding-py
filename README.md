# flower 单体应用脚手架（flower-monomer-scaffolding-py）

[![version](https://img.shields.io/badge/version-v0.1.0-blue)](https://github.com/flower-star-dream/flower-monomer-scaffolding-py)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/flower-star-dream/flower-monomer-scaffolding-py)
[![license](https://img.shields.io/badge/license-MIT-green)](https://github.com/flower-star-dream/flower-monomer-scaffolding-py)
[![framework](https://img.shields.io/badge/framework-flower--web--infrastructure-blue)](https://github.com/flower-star-dream/flower-web-infrastructure)
[![CI](https://img.shields.io/github/actions/workflow/status/flower-star-dream/flower-monomer-scaffolding-py/ci.yml?label=CI&logo=github)](https://github.com/flower-star-dream/flower-monomer-scaffolding-py/actions)

> 基于 [flower-web-infrastructure](https://github.com/flower-star-dream/flower-web-infrastructure) 的单体应用脚手架：可快速复制的业务项目模板，开箱即用。

| 项目     | 值                                              |
| -------- | ----------------------------------------------- |
| 当前版本 | v0.1.0                                          |
| Python   | >= 3.10                                         |
| 依赖框架 | flower-web-infrastructure（本地 editable 默认） |
| 数据库   | MySQL（默认）/ SQLite（测试与轻量场景）         |

## 1. 目录结构

```
flower-monomer-scaffolding-py/
├── application.yml               # 应用配置（项目根，MySQL 默认；敏感值用 ${ENV} 占位符）
├── .env.example                  # 本地敏感配置模板（复制为 .env 填写；.env 不提交仓库）
├── pyproject.toml                # 项目配置（框架依赖方式二选一，见注释）
├── alembic/                      # Alembic 权威迁移（env.py 已接入业务模型）
│   └── versions/0001_user_init.py
├── db/                           # 手工 SQL（规范 §13.2，供 DBA / 参考）
│   ├── init/ddl|dml/             # 基线脚本（001-user-init-ddl/dml.sql）
│   └── versions/                 # 增量脚本（DDL/DML 同版本成对）
├── docs/使用说明.md              # 脚手架使用说明
├── docs/CI-CD.md                # CI/CD 流水线文档（触发时机 / 门禁 / 镜像推送）
├── src/app/                      # 业务包（复制后按业务改名）
│   ├── main.py                   # 启动入口（create_app + 路由注册）
│   ├── api/v1/                   # 接口层（Controller）
│   ├── service/                  # 服务层（Service）
│   ├── repository/               # 仓储层（Repository）
│   ├── model/                    # ORM 模型（Model，继承 web_infra.Base）
│   ├── schema/                   # 请求/响应 DTO
│   └── constants/                # 业务常量（权限点 / 状态 / 缓存 Key）
├── tests/                        # pytest 测试（SQLite 内存库，不依赖外部 MySQL）
├── Dockerfile                    # 业务镜像（FROM 框架基础镜像）
└── .github/workflows/ci.yml      # CI/CD：静态检查 + 单测 + Docker 构建/扫描/冒烟/推送
```

## 2. 从脚手架创建新项目

本脚手架用于快速派生业务项目，支持两种方式（详细步骤见 [docs/创建新项目.md](docs/创建新项目.md)）：

- **方式一（推荐）**：GitHub 打开脚手架仓库 → **Use this template** 创建新仓库（GitHub 原生生成全新 git 历史，不继承脚手架提交）→ clone 到本地 → 运行内置脚本重命名：

  ```bash
  python scripts/new_project.py new my-project
  ```
- **方式二（手动）**：`git clone` 脚手架 → `rm -rf .git` → `git init`（新仓库用新 git，不被脚手架历史覆盖）→ 脚本重命名。

脚本自动替换项目名 / 仓库名 / Python 包名 / 数据库名 / 版本 / 作者，覆盖生成初始化 README，并删除脚手架专属内容（`scripts/` 等）。

## 3. 快速开始

### 3.1 创建虚拟环境并安装依赖

```bash
# 1) 创建虚拟环境（Windows）
python -m venv .venv
.venv\Scripts\activate

# 2) 安装框架依赖（默认 Git 远程拉取，不假设本机有框架仓库；本机已 clone 框架时可用 pyproject.toml 注释中的方式二）
pip install "flower-web-infrastructure[mysql,redis,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"

# 3) 安装脚手架自身（业务包 app + 开发依赖 pytest/pyright 等）
pip install -e ".[dev]"
```

### 3.2 初始化数据库

```bash
# 建库（按 application.yml 的 mysql 配置）
# 方式一：Alembic 迁移（权威）
set DATABASE_URL=mysql+aiomysql://root:密码@127.0.0.1:3306/flower_monomer
alembic upgrade head

# 方式二：手工执行基线脚本（DBA / 非 Python 环境）
#   db/init/ddl/001-user-init-ddl.sql + db/init/dml/001-user-init-dml.sql
```

### 3.3 启动

```bash
# 在项目根目录启动（配置读取依赖工作目录）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

验证：

- 健康检查：`curl http://127.0.0.1:8000/health/live`
- 接口文档：`http://127.0.0.1:8000/docs`
- 指标：`curl http://127.0.0.1:8000/metrics`

## 3. 示例业务模块（用户管理）

脚手架内置用户管理示例，演示框架核心能力（统一响应 / 错误码 / ORM 会话 / 密码加密 / 缓存防穿透 / 分页）：

| 方法  | 路径                                 | 说明                                    |
| ----- | ------------------------------------ | --------------------------------------- |
| GET   | `/v1/users/{user_id}`              | 查询用户详情（带缓存 + 空值占位防穿透） |
| GET   | `/v1/users?page_no=1&page_size=10` | 分页查询（PageResult 结构）             |
| POST  | `/v1/users`                        | 创建用户（用户名查重 + bcrypt 加密）    |
| PATCH | `/v1/users/{user_id}/status`       | 更新用户状态（写后失效缓存）            |

接口统一返回 `Result`（`{ code, message, data }`）；业务异常（如用户不存在）经全局异常处理器自动转为统一错误响应。

## 4. 数据库变更

- **权威变更工具**：Alembic（`alembic/versions/`）。`alembic/env.py` 已导入业务模型（`app.model`），`autogenerate` 可对比模型与库表生成迁移：

```bash
alembic revision --autogenerate -m "add_xxx_table"
alembic upgrade head
```

- **手工 SQL 参考**：基线 `db/init/`（禁止回改）、增量 `db/versions/`（`V{版本}-{模块}-{描述}-ddl/dml.sql` 成对，涉及存量数据语义变更必须提供幂等 DML）。

## 5. 测试与质量

```bash
.venv\Scripts\python.exe -m pytest                    # 全部测试（SQLite 内存库，无需 MySQL）
.venv\Scripts\python.exe -m pytest tests/test_user_module.py -q
.venv\Scripts\pyright.exe                             # 静态类型检查（新增代码 0 错误）
```

## 6. Docker

```bash
# 1) 拉取框架基础镜像（GHCR 远程拉取，不假设本机构建过框架镜像）
docker pull ghcr.io/flower-star-dream/flower-web-infrastructure:latest
docker tag ghcr.io/flower-star-dream/flower-web-infrastructure:latest flower-web-infrastructure:latest

# 2) 构建脚手架业务镜像
docker build -t flower-monomer-scaffolding:latest .

docker run -d -p 8000:8000 -v "$(pwd)/application.yml:/app/application.yml" flower-monomer-scaffolding:latest
```

> CI 中业务镜像由流水线自动构建并推送 GHCR（`ghcr.io/flower-star-dream/flower-monomer-scaffolding-py`）；数据库/缓存依赖（MySQL/SQLite/Redis/Alembic）由框架基础镜像内置（框架 `min-monolith + migrate` extras），业务镜像无需再安装。仅修改文档/非代码文件（`*.md`、`docs/**`、`LICENSE`、`.gitignore`、`.env.example`、`db/**`、`data/**`）时不触发流水线，版本 tag `v*` 无条件触发。触发时机 / 门禁 / 标签规范见 [docs/CI-CD.md](docs/CI-CD.md)。

## 8. 扩展新业务模块

1. `model/` 新增实体模型（继承 `web_infra.Base`），在 `model/__init__.py` 导出；
2. `schema/` 新增请求/响应 DTO；
3. `repository/` 新增仓储（统一走 `db.orm_session()`）；
4. `service/` 新增服务（错误码 / 日志 / 缓存）；
5. `api/v1/` 新增控制器，注册到 `api/v1/__init__.py` 的 `api_router`；
6. `main.py` 注册 `api_router`；`alembic/env.py` 已导入 `app.model`，新模型自动纳入迁移对比；
7. 编写 Alembic 迁移 + 配套 DDL/DML + 测试。

详细说明见 [docs/使用说明.md](docs/使用说明.md)。
