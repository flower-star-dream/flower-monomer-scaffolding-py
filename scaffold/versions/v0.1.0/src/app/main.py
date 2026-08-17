"""
应用启动入口

@Author: 花海
@Date: 2026/08/15 14:00
@Description: 脚手架应用入口：基于 web_infra.create_app 配置驱动装配（读取项目根 application.yml），
              注册业务路由后启动。启动命令需在项目根目录执行（配置读取依赖工作目录）：
              uvicorn app.main:app 或 python -m app.main。
"""
import uvicorn

from web_infra import create_app

from app.api.v1.user_controller import router as user_router

# 对外端口（与 Dockerfile EXPOSE / 文档端口规划对齐）
SERVICE_PORT = 8000


def create_application():
    """创建并装配 FastAPI 应用（配置驱动，读取项目根 application.yml）

    :return: 已装配的 FastAPI 实例
    """
    app = create_app()
    # 注册业务路由（可在此追加其它业务模块路由）
    app.include_router(user_router)
    return app


app = create_application()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=SERVICE_PORT, reload=True)
