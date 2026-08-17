"""
业务常量模块

@Author: 花海
@Date: 2026/08/15 14:00
@Description: 业务域常量汇总入口（后续新增业务模块常量在此导出，权限点常量遵循 AUTH_PERM_ 前缀规范 §6.6）。
"""
from app.constants.user_constant import UserConstant

__all__ = ["UserConstant"]
