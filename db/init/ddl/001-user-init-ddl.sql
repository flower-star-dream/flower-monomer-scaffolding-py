-- =====================================================================
-- 用户表基线 DDL（脚手架示例，脚本规范 §13.2）
-- @Author: 花海
-- @Date: 2026/08/15 14:30
-- @Description: 用户表 t_user 基线结构（等价 alembic/versions/0001_user_init.py）。
--               本基线 SQL 供 DBA 手工建库 / 非 Python 环境参考，
--               Alembic 为权威迁移工具（规范 §13.1），新变更优先编写 Alembic 迁移。
-- =====================================================================

CREATE TABLE IF NOT EXISTS t_user (
    id            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    username      VARCHAR(64)  NOT NULL COMMENT '用户名',
    password_hash VARCHAR(128) NOT NULL COMMENT '密码哈希（bcrypt）',
    nickname      VARCHAR(64)  NULL COMMENT '昵称',
    status        TINYINT      NOT NULL DEFAULT 1 COMMENT '状态：1 启用 / 0 禁用',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at    DATETIME     NULL COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_username (username)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '用户表';
