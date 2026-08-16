# =====================================================================
# flower-monomer-scaffolding 业务镜像
# @Author: 花海
# @Date: 2026/08/15 14:30
# @Description: 业务镜像基于框架基础镜像（flower-web-infrastructure:latest）构建：
#               复制业务代码与配置后以 python -m uvicorn 启动（含 /health/live /health/ready /metrics）。
#               数据库/缓存依赖（MySQL/SQLite/Redis/Alembic）由框架基础镜像内置（min-monolith + migrate extras）。
#               构建前需先构建框架基础镜像：
#               docker build -t flower-web-infrastructure:latest f:\baseProject\flower-web-infrastructure
# =====================================================================
FROM flower-web-infrastructure:latest

WORKDIR /app

# 业务代码与运行配置（src 加入 PYTHONPATH，无需重新安装）
COPY src ./src
COPY application.yml ./application.yml

ENV PYTHONPATH=/app/src \
    TZ=Asia/Shanghai

EXPOSE 8000

# 生产环境需通过环境变量覆盖数据库等配置（或挂载 application.yml）
# 用 python -m uvicorn 启动（而非 uvicorn 控制台脚本）：基础镜像只拷贝 site-packages，
# 运行时无 /usr/local/bin 下的控制台脚本（Trivy 安全整改后亦移除了构建期工具）
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
