-- =====================================================================
-- 用户表基线 DML（初始数据）
-- @Author: 花海
-- @Date: 2026/08/15 14:30
-- @Description: 初始管理员账号（admin，默认密码 admin123，密码为 bcrypt 哈希）。
--               生产部署前务必修改默认密码或删除该初始数据。
-- =====================================================================

INSERT INTO t_user (username, password_hash, nickname, status)
VALUES ('admin', '$2b$12$7.Vg7PKGYXaTWb43pmcb1eL1.9IIQO3TMniE7SZFHYc6YFrv6SpdC', '系统管理员', 1);
