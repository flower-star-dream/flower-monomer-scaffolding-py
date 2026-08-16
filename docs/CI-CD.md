# flower 单体应用脚手架 CI/CD 文档

> 本文档说明本项目的持续集成（CI）与持续交付（CD）流水线：触发时机、前置条件、流水线结构、门禁策略、本地复现与镜像推送规范。
>
> - 上位框架：[flower-web-infrastructure CI/CD 文档](../flower-web-infrastructure/docs/CI-CD.md)（框架流水线负责构建/推送框架基础镜像）
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

## 1. 触发时机与前置条件

### 1.1 触发时机

| 事件 | 分支/范围 | 说明 |
| ---- | ---- | ---- |
| `push` | `main` | 合并到主干后运行全量流水线，并推送测试标签镜像（含 `latest`） |
| `push` | `v*` 版本 tag | 打版本标签时运行全量流水线，并推送正式版镜像（SemVer + `latest`） |
| `pull_request` | 任意 | PR 提交/更新时运行，作为合入门禁；只构建/扫描/冒烟，**不推送**镜像 |

### 1.2 前置条件（跨仓库访问）

本流水线依赖框架仓库与其 GHCR 基础镜像，需要以下访问权限（两处均满足其一即可）：

1. **检出框架仓库**（`test` Job）：`actions/checkout` 检出 `flower-star-dream/flower-web-infrastructure`。
   - 仓库**公开**：无需额外配置；
   - 仓库**私有**：在仓库 Settings → Secrets 配置 PAT（`contents:read`，存为 `FRAMEWORK_PAT`），并取消 `ci.yml` 中 checkout 步骤的 `token` 注释。
2. **拉取框架基础镜像**（`build-image` Job）：`docker pull ghcr.io/flower-star-dream/flower-web-infrastructure:latest`。
   - 在**框架仓库** Settings → Packages → flower-web-infrastructure 镜像包 → 设置 "Manage Actions access"，授权本仓库可拉取；或将本镜像包设为 public；
   - 或在本仓库配置带 `read:packages` 的 PAT 用于 GHCR 登录（修改登录步骤的 `password` 指向该 Secret）。
3. **框架基础镜像已发布**：`latest` 标签由框架流水线在每次 push `main` 时更新（见框架 CI/CD 文档 §4），首次构建前请先在框架仓库推送一次 `main`，或直接打框架版本 tag 发布正式版。

> 说明：`GITHUB_TOKEN` 默认仅作用于当前仓库，无法直接访问其他仓库的代码与包；上述跨仓库访问需按 1.2 处理，这是本工作流与框架工作流（单仓库）的主要差异。

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
| 检出框架仓库 | `actions/checkout@v4`（`repository: flower-star-dream/flower-web-infrastructure`） | 框架依赖以本地 editable 方式安装（跨仓库访问见 [1.2](#12-前置条件跨仓库访问)） |
| 安装 Python | `actions/setup-python@v5` | Python 3.11，启用 pip 缓存 |
| 安装框架依赖 | `pip install -e ./flower-web-infrastructure[mysql,redis,migrate]` | 与 [使用说明 §1](使用说明.md#1-安装) 本地安装方式一致 |
| 安装脚手架依赖 | `pip install -e ".[dev]"` | 业务包 + dev 依赖（pytest / pytest-asyncio / pytest-cov / httpx / pyright） |
| 静态类型检查 | `pyright` | 新增代码必须 0 错误（既有基线容忍见框架文档 §3） |
| 单元测试 | `pytest -q` | 硬性门禁：任一失败即中断流水线，镜像不构建 |

### 2.2 build-image —— Docker 业务镜像构建与验证

| 步骤 | 行为 |
| ---- | ---- |
| 登录 GHCR | `docker/login-action@v3`，`ghcr.io`，使用 `secrets.GITHUB_TOKEN`（Job 已声明 `packages: write` 权限） |
| 拉取框架基础镜像 | `docker pull ghcr.io/flower-star-dream/flower-web-infrastructure:latest` 并打本地标签 `flower-web-infrastructure:latest`，使业务镜像 `Dockerfile` 的 `FROM` 可解析 |
| 构建业务镜像 | `docker build -t flower-monomer-scaffolding:ci .`，基于 `Dockerfile`（`FROM flower-web-infrastructure:latest` + 业务代码 + `application.yml`） |
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
# 安装依赖（与使用说明 §1 一致）
.venv\Scripts\python.exe -m pip install -e "f:\baseProject\flower-web-infrastructure[mysql,redis,migrate]"
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 静态类型检查
.venv\Scripts\pyright.exe

# 单元测试
.venv\Scripts\python.exe -m pytest

# 镜像构建与冒烟（本机需安装 Docker）
docker build -t flower-web-infrastructure:latest f:\baseProject\flower-web-infrastructure
docker build -t flower-monomer-scaffolding:ci .
docker run -d --name scaffold-smoke -p 18001:8000 flower-monomer-scaffolding:ci
curl http://127.0.0.1:18001/health/live
docker rm -f scaffold-smoke
```

## 6. 镜像保留与清理

> 规范 §20.5：镜像保留策略 + 悬空清理 + 回收审计属**运维配置**（框架边界），CI 负责按标签规范推送，仓库侧保留规则与清理任务由运维按环境配置。基线建议与配置入口见 [框架 CI/CD 文档 §5](../flower-web-infrastructure/docs/CI-CD.md#5-镜像保留与清理)，本仓库按同一策略执行。

## 7. 维护指南

| 场景 | 操作位置 |
| ---- | ---- |
| 调整触发分支 | `ci.yml` 中 `on.push.branches` |
| 更换框架仓库地址 | `ci.yml` 中 checkout 的 `repository` 与 `build-image` Job 的 `docker pull` 地址，同步更新 [1.2](#12-前置条件跨仓库访问) 与本文档各处地址 |
| 更换 GHCR 目标仓库 | `build-image` Job 登录与推送步骤（`IMAGE=ghcr.io/${{ github.repository }}` 默认跟随当前仓库，无需改动） |
| 升级 Python 版本 | `ci.yml` 中 `setup-python.python-version`，同步确认框架基础镜像版本 |
| 新增依赖 | 修改 `pyproject.toml` 的 `dependencies` / `optional-dependencies`（框架能力走框架 extras，见 pyproject 注释） |
| 版本发布 | 遵循 SemVer，同步更新 `pyproject.toml` 版本号，然后打 `v<版本>` tag 触发正式版镜像推送（SemVer + `latest`） |

## 8. 常见问题

- **pytest 失败**：`test` Job 中断，镜像不构建。按 `pytest` 输出定位失败用例，修复后重新推送/更新 PR。
- **检出框架仓库 404 / Permission denied**：`GITHUB_TOKEN` 无法访问其他仓库，见 [1.2](#12-前置条件跨仓库访问)：公开仓库无需配置，私有仓库需 PAT。
- **拉取框架基础镜像 401/403**：框架镜像包未授权本仓库拉取，见 [1.2](#12-前置条件跨仓库访问)；若框架 `latest` 尚未发布，先在框架仓库推送一次 `main` 或打版本 tag。
- **冒烟验证超时**：容器 30 秒内 `/health/live` 不可达。查看 Job 输出的 `docker logs`，常见原因：`application.yml` 配置异常、业务代码 import 报错、启动端口被占。
- **GHCR 推送失败（403 / denied）**：确认 `build-image` Job 的 `permissions.packages: write` 已声明；首次推送时需在 GitHub Settings → Packages 中授权本镜像包（Package visibility 至少设为 private，并为本组织成员配置读权限）。
