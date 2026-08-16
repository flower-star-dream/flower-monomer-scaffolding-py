"""
新建项目重命名脚本测试（test_new_project）

@Author: 花海
@Date: 2026/08/16
@Description: 覆盖 scripts/new_project.py 的参数派生、文本替换（含运行时实例属性保护）、
              端到端生成（迷你模板 → --dir 复制重命名）、非法项目名校验。
              用 importlib 加载脚本模块，不依赖脚手架仓库完整内容，测试轻量且隔离。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# 加载脚本模块（scripts/ 不在包内，用 importlib 按路径加载）
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "new_project.py"
_spec = importlib.util.spec_from_file_location("new_project", _SCRIPT_PATH)
np = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(np)


@pytest.fixture
def mini_template(tmp_path: Path) -> Path:
    """构造迷你脚手架模板（含需替换标识与需保护的运行时实例属性）。"""
    root = tmp_path / "mini-template"
    (root / "src" / "app").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "docs").mkdir()
    (root / "tests").mkdir()

    (root / "pyproject.toml").write_text(
        'name = "flower-monomer-scaffolding"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "application.yml").write_text(
        "app:\n  name: flower-monomer-scaffolding\n  db:\n    type: mysql\n"
        "    database: ${APP_DB_MYSQL_DATABASE:flower_monomer}\n",
        encoding="utf-8",
    )
    (root / "src" / "app" / "main.py").write_text(
        "from app.api.v1.user_controller import router\n"
        "app.include_router(router)\n"
        "app.state.db  # 运行时实例属性，不能被替换\n",
        encoding="utf-8",
    )
    (root / "docs" / "使用说明.md").write_text(
        "参考 flower-monomer-scaffolding 脚手架，库名 flower_monomer\n",
        encoding="utf-8",
    )
    (root / "scripts" / "keep_me.txt").write_text("scripts 目录应被整体删除\n", encoding="utf-8")
    (root / "README.md").write_text("# flower 单体应用脚手架（flower-monomer-scaffolding-py）\n", encoding="utf-8")
    # 脚手架专属内容：CLI 测试 / 构建产物（生成新项目时应排除）
    (root / "tests" / "test_new_project.py").write_text("assert False  # CLI 测试，业务项目不需要\n", encoding="utf-8")
    (root / "src" / "app" / "demo.egg-info").mkdir()
    (root / "src" / "app" / "demo.egg-info" / "PKG-INFO").write_text("Name: flower-monomer-scaffolding\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# 单元测试：参数派生
# ---------------------------------------------------------------------------
class TestDeriveNames:
    """参数派生与校验。"""

    def test_project_name_derives_package_and_db(self):
        names = np._derive_names(np._parse_args(["new", "my-project"]))
        assert names["project_name"] == "my-project"
        assert names["repo_name"] == "my-project"
        assert names["package"] == "my_project"
        assert names["db_name"] == "my_project"
        assert names["db_type"] == "mysql"

    def test_explicit_package_and_db_name(self):
        names = np._derive_names(
            np._parse_args(["new", "my-project", "--package", "biz_pkg", "--db-name", "my_db"])
        )
        assert names["package"] == "biz_pkg"
        assert names["db_name"] == "my_db"

    def test_invalid_project_name_raises(self):
        with pytest.raises(SystemExit):
            np._derive_names(np._parse_args(["new", "Bad..Name"]))
        with pytest.raises(SystemExit):
            np._derive_names(np._parse_args(["new", "bad.git"]))


# ---------------------------------------------------------------------------
# 单元测试：文本替换
# ---------------------------------------------------------------------------
class TestTextReplacements:
    """文本替换规则与运行时实例属性保护。"""

    def test_apply_replacements_basic(self):
        names = np._derive_names(np._parse_args(["new", "my-project"]))
        text = (
            "name = \"flower-monomer-scaffolding\"\n"
            "org = flower-star-dream/flower-monomer-scaffolding-py\n"
            "db = flower_monomer\n"
        )
        updated = np._apply_text_replacements(text, names)
        assert "flower-monomer-scaffolding" not in updated
        assert "flower-monomer-scaffolding-py" not in updated
        assert "flower_monomer" not in updated
        assert "my-project" in updated
        assert "my_project" in updated

    def test_app_instance_attrs_protected(self):
        """app.state / app.include_router / app.routes / app.url_path_for 必须原样保留。"""
        names = np._derive_names(np._parse_args(["new", "my-project"]))
        text = (
            "from app.api.v1 import router\n"
            "app.include_router(router)\n"
            "x = app.state.db\n"
            "y = request.app.state.cache\n"
            "z = app.url_path_for('get_user')\n"
        )
        updated = np._apply_text_replacements(text, names)
        # import 引用被替换
        assert "from my_project.api.v1 import router" in updated
        # 运行时实例属性原样保留
        assert "app.include_router(router)" in updated
        assert "app.state.db" in updated
        assert "request.app.state.cache" in updated
        assert "app.url_path_for('get_user')" in updated
        # 不应残留占位符
        assert "@@FLOWER_APP_INSTANCE" not in updated

    def test_version_and_author(self):
        names = np._derive_names(np._parse_args(["new", "my-project", "--version", "0.2.0", "--author", "张三"]))
        text = 'version = "0.1.0"\n@Author: 花海\n'
        updated = np._apply_text_replacements(text, names)
        assert 'version = "0.2.0"' in updated
        assert "@Author: 张三" in updated

    def test_db_type_sqlite(self):
        names = np._derive_names(np._parse_args(["new", "my-project", "--db", "sqlite"]))
        assert names["db_type"] == "sqlite"


# ---------------------------------------------------------------------------
# 集成测试：迷你模板端到端生成
# ---------------------------------------------------------------------------
class TestEndToEnd:
    """从迷你模板复制生成新项目并校验替换结果。"""

    def _generate(self, monkeypatch, mini_template: Path, tmp_path: Path, *extra_args: str) -> Path:
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_template)
        target = tmp_path / "generated"
        np.main(["new", "my-project", "--dir", str(target), *extra_args])
        return target

    def test_generate_basic(self, monkeypatch, mini_template: Path, tmp_path: Path):
        target = self._generate(monkeypatch, mini_template, tmp_path)
        # 包目录重命名
        assert (target / "src" / "my_project").exists()
        assert not (target / "src" / "app").exists()
        # import 引用替换 + 实例属性保留
        main_py = (target / "src" / "my_project" / "main.py").read_text(encoding="utf-8")
        assert "from my_project.api.v1.user_controller import router" in main_py
        assert "app.include_router(router)" in main_py
        assert "app.state.db" in main_py
        # pyproject 项目名与版本
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "my-project"' in pyproject
        # application.yml 库名
        yml = (target / "application.yml").read_text(encoding="utf-8")
        assert "name: my-project" in yml
        assert "flower_monomer" not in yml
        assert "my_project" in yml
        # docs 替换
        doc = (target / "docs" / "使用说明.md").read_text(encoding="utf-8")
        assert "my-project" in doc
        assert "flower_monomer" not in doc
        # scripts 目录已删除、README 已覆盖
        assert not (target / "scripts").exists()
        readme = (target / "README.md").read_text(encoding="utf-8")
        assert readme.startswith("# my-project")
        assert "img.shields.io" in readme
        # 脚手架专属内容已排除：CLI 测试 / egg-info 构建产物
        assert not (target / "tests" / "test_new_project.py").exists()
        assert not list(target.rglob("*.egg-info"))

    def test_generate_sqlite_and_author(self, monkeypatch, mini_template: Path, tmp_path: Path):
        target = self._generate(
            monkeypatch, mini_template, tmp_path, "--db", "sqlite", "--author", "李四"
        )
        yml = (target / "application.yml").read_text(encoding="utf-8")
        assert "type: sqlite" in yml
        # author 替换（迷你模板无 @Author，验证不报错即可；文档类文件头场景由真实仓库覆盖）

    def test_keep_scripts_in_source_template(self, monkeypatch, mini_template: Path, tmp_path: Path):
        """--dir 模式：源模板目录保持不动，脚本目录不被删除。"""
        self._generate(monkeypatch, mini_template, tmp_path)
        assert (mini_template / "scripts" / "keep_me.txt").exists()
        assert (mini_template / "src" / "app").exists()

    def test_illegal_name_via_main(self, monkeypatch, mini_template: Path):
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_template)
        with pytest.raises(SystemExit):
            np.main(["new", "bad.git"])


def test_module_importable():
    """脚本可独立加载（语法与导入无异常）。"""
    assert callable(np.main)
    assert callable(np._apply_text_replacements)
