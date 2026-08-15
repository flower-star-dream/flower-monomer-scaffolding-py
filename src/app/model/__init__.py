"""
业务实体模型模块

@Author: 花海
@Date: 2026/08/15 14:00
@Description: 业务 ORM 模型汇总入口。后续新增实体模型在此导出；
              同时被 alembic/env.py 导入以注册 Base.metadata（autogenerate 依据）。
"""
from app.model.user_model import UserModel

__all__ = ["UserModel"]
