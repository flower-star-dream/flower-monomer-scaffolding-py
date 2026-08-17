# flower 单体应用脚手架 CI/CD 文档

> 本文档说明本项目的持续集成（CI）与持续交付（CD）流水线：触发时机、前置条件、流水线结构、门禁策略、本地复现与镜像推送规范。
>
> - 上位框架：[flower-web-infrastructure CI/CD 文档](https://github.com/flower-star-dream/flower-web-infrastructure/blob/main/docs/CI-CD.md)（框架流水线负责构建/推送框架基础镜像）
> - 工作流文件：[`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
> - 平台：GitHub Actions（组织 `flower-star-dream`）
> - 关联文件：`Dockerfile`、`.dockerignore`

## 目录

- [1. 触发时机与前置条件](#1-触发时机与前置条件)
- [2. 流水线结构](#2-流水线结构)
- [3. 门禁策略](#3-门禁策略)
- [4. 镜像推送（已启用）](#4-镜像推送已启用)
- [5. 本地复现](#5-本地复现)
- [6. 镜像保留与清理](#6-镜像保留与清理)
- [7. 维护指南](#7-维护指南)
- [8. 常见问题](#8-常见问题)
- [9. 仓库配置（Settings / Secrets）](#9-仓库配置settings--secrets)

## 1. 触发时机与前置条件

### 1.1 触发时机

| 事件 | 分支/范围 | 说明 |
| ---- | ---- | ---- |
| `push` | `main` | 合并到主干后运行全量流水线，并推送测试标签镜像（含 `latest`） |
| `push` | `v*` 版本 tag | 打版本标签时运行全量流水线，并推送正式版镜像（SemVer + `latest`）。**无条件触发**（不受 `paths-ignore` 影响，保证正式版必发布） |
| `pull_request` | 任意 | PR 提交/更新时运行，作为合入门禁；只构建/扫描/冒烟，**不推送**镜像 |

> **非代码变更不触发**（`push` main / PR 均生效）：仅修改文档与非代码文件（`*.md`、`docs/**`、`LICENSE`、`.gitignore`、`.env.example`、`db/**`、`data/**`）时不运行流水线；这些变更不参与单元测试与镜像构建。版本 tag 发布除外。

### 1.2 前置条件（跨仓库访问）

本流水线依赖框架仓库与其 GHCR 基础镜像，而 `GITHUB_TOKEN` 默认仅作用于当前仓库，无法直接访问其他仓库的代码与包。完整配置项清单（Secret 名称、权限要求、配置位置）见 [9. 仓库配置（Settings / Secrets）](#9-仓库配置settings--secrets)，此处仅列访问关系：

1. **检出框架仓库**（`test` Job）：`actions/checkout` 检出 `flower-star-dream/flower-web-infrastructure`。框架仓库公开则无需配置；私有则需配置 `FRAMEWORK_PAT`。
2. **拉取框架基础镜像**（`build-image` Job）：`docker pull ghcr.io/flower-star-dream/flower-web-infrastructure:latest`。需框架镜像包授权本仓库拉取（推荐，无需 Secret），或配置带 `read:packages` 的 PAT。
3. **框架基础镜像已发布**：`latest` 标签由框架流水线在每次 push `main` 时更新（见框架 CI/CD 文档 §4），首次构建前请先在框架仓库推送一次 `main`，或直接打框架版本 tag 发布正式版。

## 2. 流水线结构

流水线包含两个 Job，`build-image` 依赖 `test`（测试失败则不构建镜像）：

```
CI
├── test          (静态检查 + 单元测试)
└── build-image   (拉取框架基础镜像 → 构建业务镜像 + 漏洞扫描 + 冒烟 + 推送 GHCR)  needs: test
```

### 2.1 test —— 静态检查 + 单元测试

运行环境：`ubuntu-latest`，Python 3.11。

| 步骤 | 命令 | 行为 |
| ---- | ---- | ---- |
| 检出脚手架 | `actions/checkout@v4` | 拉取本仓库代码 |
| 检出框架仓库 | `actions/checkout@v4`（`repository: flower-star-dream/flower-web-infrastructure`） | CI 远程拉取框架源码，随后以 editable 方式安装（跨仓库访问见 [1.2](#12-前置条件跨仓库访问)） |
| 安装 Python | `actions/setup-python@v5` | Python 3.11，启用 pip 缓存 |
| 安装框架依赖 | `pip install -e ./flower-web-infrastructure[mysql,redis,migrate]` | 框架由 CI 检出（远程 git）后安装，与 [使用说明 §1](使用说明.md#1-安装) 的安装方式等效 |
| 安装脚手架依赖 | `pip install -e ".[dev]"` | 业务包 + dev 依赖（pytest / pytest-asyncio / pytest-cov / httpx / pyright） |
| 静态类型检查 | `pyright` | 新增代码必须 0 错误（既有基线容忍见框架文档 §3） |
| 单元测试 | `pytest -q` | 硬性门禁：任一失败即中断流水线，镜像不构建 |

### 2.2 build-image —— Docker 业务镜像构建与验证

| 步骤 | 行为 |
| ---- | ---- |
| 登录 GHCR | `docker/login-action@v3`，`ghcr.io`，使用 `secrets.GITHUB_TOKEN`（Job 已声明 `packages: write` 权限） |
| 拉取框架基础镜像 | `docker pull ghcr.io/flower-star-dream/flower-web-infrastructure:latest` 并打本地标签 `flower-web-infrastructure:latest`，使业务镜像 `Dockerfile` 的 `FROM` 可解析 |
| 构建业务镜像 | `docker build -t flower-monomer-scaffolding:ci .`，基于 `Dockerfile`（`FROM flower-web-infrastructure:latest` + 业务代码 + `application.yml`）。数据库/缓存依赖（MySQL/SQLite/Redis/Alembic）由框架基础镜像内置（框架 `min-monolith + migrate` extras），业务镜像无需再安装 |
| 镜像漏洞扫描 | Trivy 扫描（`HIGH,CRITICAL`，`exit-code=1`），存在高危/严重漏洞即阻断（规范 §20.2） |
| 冒烟验证 | 启动容器并轮询 `GET /health/live`（30 次 × 1s，存活探针，整改 S19-1），失败时输出容器日志 |
| 推送镜像（GHCR） | 已启用：push `main` 推测试标签 + `latest`；版本 tag `v*` 推 SemVer + `latest`；PR 不推送。详见 [4. 镜像推送](#4-镜像推送已启用) |

## 3. 门禁策略

| 检查项 | 门禁级别 | 说明 |
| ---- | ---- | ---- |
| 单元测试（pytest） | 硬性 | 失败即阻断合并与镜像构建 |
| 静态类型检查（pyright） | 软性 | 新增代码本地须保持 0 错误（本地门禁） |
| 镜像漏洞扫描（Trivy） | 硬性 | 存在高危/严重漏洞即阻断镜像留存（规范 §20.2） |
| 镜像构建 + `/health/live` 冒烟 | 硬性 | 业务镜像必须可启动且存活探针通过（整改 S19-1；就绪探测 `/health/ready` 由编排层使用） |

## 4. 镜像推送（已启用）

工作流已启用 GHCR 推送（镜像地址 `ghcr.io/flower-star-dream/flower-monomer-scaffolding-py`）。CI 内部构建标签固定为 `flower-monomer-scaffolding:ci`，仅用于流水线内构建/扫描/冒烟，不对外推送。

**推送标签规范**（整改 S20-3，`ghcr.io/<org>/<repo>` 命名，与框架仓库一致）：

| 触发 | 推送标签 | 说明 |
| ---- | ---- | ---- |
| push `main` | `main-<时间戳>-<构建号>` | 测试版，如 `main-20260816103000-42` |
| push `main` | `latest` | 跟随最新 main 构建 |
| 版本 tag `v*` | `<SemVer>` | 正式版，如 tag `v0.1.0` → 推送 `0.1.0`（与 `pyproject.toml` 版本号保持一致） |
| 版本 tag `v*` | `latest` | 正式版发布时覆盖为最新正式版 |
| PR | 不推送 | 只构建/扫描/冒烟，避免测试镜像污染仓库 |

> 与框架联动：脚手架 `latest` 的**基础镜像来源**是框架 `latest`（框架流水线 push `main` 时同步更新，见框架 CI/CD 文档 §4）。发布脚手架正式版前，建议先发布并推送对应版本的框架镜像。

## 5. 本地复现

在提交前执行与 CI 相同的检查：

```bash
# 安装依赖（默认 Git 远程拉取框架，与使用说明 §1 一致；本机已 clone 框架时可改用本地 editable）
.venv\Scripts\python.exe -m pip install "flower-web-infrastructure[mysql,redis,migrate] @ git+https://github.com/flower-star-dream/flower-web-infrastructure.git"
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 静态类型检查
.venv\Scripts\pyright.exe

# 单元测试
.venv\Scripts\python.exe -m pytest

# 镜像构建与冒烟（本机需安装 Docker；框架基础镜像从 GHCR 拉取）
docker pull ghcr.io/flower-star-dream/flower-web-infrastructure:latest
docker tag ghcr.io/flower-star-dream/flower-web-infrastructure:latest flower-web-infrastructure:latest
docker build -t flower-monomer-scaffolding:ci .
docker run -d --name scaffold-smoke -p 18001:8000 flower-monomer-scaffolding:ci
curl http://127.0.0.1:18001/health/live
docker rm -f scaffold-smoke
```

## 6. 镜像保留与清理

> 规范 §20.5：镜像保留策略 + 悬空清理 + 回收审计属**运维配置**（框架边界），CI 负责按标签规范推送，仓库侧保留规则与清理任务由运维按环境配置。基线建议与配置入口见 [框架 CI/CD 文档 §5](https://github.com/flower-star-dream/flower-web-infrastructure/blob/main/docs/CI-CD.md#5-镜像保留与清理)，本仓库按同一策略执行。

## 7. 维护指南

| 场景 | 操作位置 |
| ---- | ---- |
| 调整触发分支 | `ci.yml` 中 `on.push.branches` |
| 更换框架仓库地址 | `ci.yml` 中 checkout 的 `repository` 与 `build-image` Job 的 `docker pull` 地址，同步更新 [1.2](#12-前置条件跨仓库访问) 与本文档各处地址 |
| 更换 GHCR 目标仓库 | `build-image` Job 登录与推送步骤（`IMAGE=ghcr.io/${{ github.repository }}` 默认跟随当前仓库，无需改动） |
| 升级 Python 版本 | `ci.yml` 中 `setup-python.python-version`，同步确认框架基础镜像版本 |
| 新增依赖 | 修改 `pyproject.toml` 的 `dependencies` / `optional-dependencies`（框架能力走框架 extras，见 pyproject 注释） |
| 版本发布 | 遵循 SemVer，同步更新 `pyproject.toml` 版本号，然后打 `v<版本>` tag 触发正式版镜像推送（SemVer + `latest`） |
| 配置/变更 Secret 或包权限 | 见 [9. 仓库配置（Settings / Secrets）](#9-仓库配置settings--secrets) |

## 8. 常见问题

- **pytest 失败**：`test` Job 中断，镜像不构建。按 `pytest` 输出定位失败用例，修复后重新推送/更新 PR。
- **检出框架仓库 404 / Permission denied**：`GITHUB_TOKEN` 无法访问其他仓库，见 [1.2](#12-前置条件跨仓库访问)：公开仓库无需配置，私有仓库需 PAT。
- **拉取框架基础镜像 401/403**：框架镜像包未授权本仓库拉取，见 [1.2](#12-前置条件跨仓库访问)；若框架 `latest` 尚未发布，先在框架仓库推送一次 `main` 或打版本 tag。
- **冒烟验证超时**：容器 30 秒内 `/health/live` 不可达。查看 Job 输出的 `docker logs`，常见原因：`application.yml` 配置异常、业务代码 import 报错、启动端口被占。
- **冒烟失败且日志报 `ModuleNotFoundError`（如 sqlalchemy/redis）**：业务代码依赖的框架 extras 由框架基础镜像提供（框架 `min-monolith + migrate`）。若框架 `latest` 是旧版本（仅核心依赖），先在框架仓库推送修复后的 `main` 再重跑本流水线。
- **冒烟失败且日志报 `uvicorn: executable file not found`**：框架基础镜像只拷贝 site-packages，运行时无 `uvicorn` 控制台脚本。业务镜像 `CMD` 必须用 `python -m uvicorn`（本仓库 Dockerfile 已修复；如复制本脚手架为业务项目，勿改回 `uvicorn`）。
- **GHCR 推送失败（403 / denied）**：确认 `build-image` Job 的 `permissions.packages: write` 已声明；首次推送时需在 GitHub Settings → Packages 中授权本镜像包（Package visibility 至少设为 private，并为本组织成员配置读权限）。

## 9. 仓库配置（Settings / Secrets）

流水线所需配置项一览。`GITHUB_TOKEN` 由 GitHub 自动注入（`build-image` Job 已声明 `packages: write`，无需配置）；其余配置项按是否跨仓库访问/是否正式版发布决定是否必需。Secret 名称必须与 `ci.yml` 中的引用（`secrets.XXX`）完全一致。

| 配置项 | 类型 | 配置位置 | 必需性 | 用途与说明 |
| ---- | ---- | ---- | ---- | ---- |
| `FRAMEWORK_PAT` | Actions Secret | 本仓库 Settings → Secrets and variables → Actions → New repository secret | 可选（**框架仓库为私有时必需**） | `test` Job 检出框架仓库 `flower-star-dream/flower-web-infrastructure` 的凭据。PAT 权限要求：fine-grained 需对框架仓库 `Contents: Read`；classic 需 `repo`（组织启用 SSO 时需在 PAT 上授权）。配置后取消 `ci.yml` 中 checkout 步骤的 `token: ${{ secrets.FRAMEWORK_PAT }}` 注释。框架仓库公开时无需配置 |
| 框架镜像包拉取授权 | 包设置 | **框架仓库** Settings → Packages → flower-web-infrastructure → 右侧 "Manage Actions access" | 可选（推荐方式，无需 Secret） | 授权本仓库（flower-monomer-scaffolding-py）可拉取 `ghcr.io/flower-star-dream/flower-web-infrastructure:latest`；或直接将框架镜像包设为 public。配置后 `build-image` Job 的 `docker pull` 无需额外凭据 |
| 拉取 PAT（备选方案） | Actions Secret | 本仓库 Settings → Secrets and variables → Actions | 可选（方式二，替代上一条） | 带 `read:packages` 的 PAT，用于 GHCR 登录步骤拉取框架基础镜像。配置后需将 `docker/login-action` 的 `password` 改为 `${{ secrets.<PAT 名称> }}` |
| 本仓库镜像包可见性 | 包设置 | 本仓库 Settings → Packages → flower-monomer-scaffolding-py | 首次推送后配置 | 首次 CI 推送成功后在 GitHub 生成镜像包，设置可见性（public/private）与组织成员读权限；私有包需为拉取方（如部署环境）配置读权限 |
| `GITHUB_TOKEN` | 自动注入 | 无需配置 | — | GHCR 登录与推送凭据（`packages: write` 已在 ci.yml 声明） |

**配置顺序建议**（首次接入时按序执行）：

1. （框架仓库私有时）在本仓库创建 Secret `FRAMEWORK_PAT`，并取消 `ci.yml` 中 checkout 的 `token` 注释；
2. 在框架仓库给框架镜像包授权本仓库拉取（或设为 public）；
3. 推送框架仓库 `main`，确认框架镜像 `latest` 已发布；
4. 推送本仓库 `main`，观察流水线；首次推送成功后到 Settings → Packages 设置本仓库镜像包可见性。
