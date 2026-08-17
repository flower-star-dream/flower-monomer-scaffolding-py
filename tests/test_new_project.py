"""
新建项目重命名脚本测试（test_new_project）

@Author: 花海
@Date: 2026/08/16
@Description: 覆盖 scripts/new_project.py 的参数派生、文本替换（含运行时实例属性保护）、
              端到端生成（迷你模板 → --dir 复制重命名）、组件与实现选择（--components /
              标记块裁剪 / 自研 SPI 骨架 / 注册中心禁内存实现）、升级三路合并（upgrade）、
              快照排除（snapshot）、非法项目名校验。
              用 importlib 加载脚本模块，不依赖脚手架仓库完整内容，测试轻量且隔离。
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

# 加载脚本模块（scripts/ 不在包内，用 importlib 按路径加载；组件模块同目录）
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "new_project.py"
sys.path.insert(0, str(_SCRIPT_PATH.parent))
_spec = importlib.util.spec_from_file_location("new_project", _SCRIPT_PATH)
np = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(np)


def _marker_block(name: str, body: str) -> str:
    """构造组件标记块文本（与模板文件一致）。"""
    return f"# <<<COMPONENT:{name}>>>\n{body}# <<</COMPONENT:{name}>>>\n"


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
        # 升级元数据已写入（脚手架类型 / 版本 / 替换参数）
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["scaffold"] == "flower-monomer-scaffolding-py"
        assert info["scaffold_version"] == "0.1.0"
        assert info["params"]["package"] == "my_project"
        assert info["params"]["db_name"] == "my_project"

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


# ---------------------------------------------------------------------------
# 单元测试：三路合并判定
# ---------------------------------------------------------------------------
class TestThreeWayMerge:
    """三路合并动作判定。"""

    def test_template_changed_business_untouched(self):
        assert np._three_way_merge("base", "base", "new") == "update"

    def test_template_unchanged_skip(self):
        assert np._three_way_merge("base", "ours", "base") == "skip"

    def test_both_changed_conflict(self):
        assert np._three_way_merge("base", "ours", "new") == "conflict"

    def test_new_template_file_add(self):
        assert np._three_way_merge(None, None, "new") == "add"

    def test_template_removed(self):
        assert np._three_way_merge("base", "base", None) == "remove"

    def test_template_removed_but_modified_conflict(self):
        assert np._three_way_merge("base", "ours", None) == "conflict"

    def test_business_deleted_template_file(self):
        assert np._three_way_merge("base", None, "new") == "missing"


# ---------------------------------------------------------------------------
# 集成测试：升级（upgrade）
# ---------------------------------------------------------------------------
class TestUpgrade:
    """生成项目 → 模拟新版模板 → 三路合并升级。"""

    def _generate_project(self, monkeypatch, mini_template: Path, tmp_path: Path) -> Path:
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_template)
        target = tmp_path / "generated"
        np.main(["new", "my-project", "--dir", str(target)])
        return target

    def _make_base_snapshot(self, mini_template: Path) -> Path:
        """把当前迷你模板拷贝为 base 快照（模拟脚手架发版时的 v0.1.0 基线）。"""
        base = mini_template / "scaffold" / "versions" / "v0.1.0"
        shutil.copytree(mini_template, base, ignore=shutil.ignore_patterns("scaffold", "scripts"))
        return base

    def test_upgrade_three_way(self, monkeypatch, mini_template: Path, tmp_path: Path):
        self._make_base_snapshot(mini_template)
        target = self._generate_project(monkeypatch, mini_template, tmp_path)

        # 新版模板变更（theirs）
        pyproject = mini_template / "pyproject.toml"
        pyproject.write_text(pyproject.read_text(encoding="utf-8") + "upgrade_flag = 1\n", encoding="utf-8")
        yml_tmpl = mini_template / "application.yml"
        yml_tmpl.write_text(yml_tmpl.read_text(encoding="utf-8") + "template: new\n", encoding="utf-8")
        (mini_template / "new_file.md").write_text("new template doc\n", encoding="utf-8")
        # 业务改动 application.yml（ours 与 base/theirs 均不同 → conflict）
        yml_proj = target / "application.yml"
        yml_proj.write_text(yml_proj.read_text(encoding="utf-8") + "biz: xxx\n", encoding="utf-8")

        # dry-run：预览不写盘
        stats = np._run_upgrade(np._derive_upgrade_args(np._parse_args(["upgrade", str(target), "--dry-run"])))
        assert "pyproject.toml" in stats["updated"]
        assert "new_file.md" in stats["added"]
        assert "application.yml" in stats["conflict"]
        assert "upgrade_flag" not in (target / "pyproject.toml").read_text(encoding="utf-8")

        # 实跑升级
        stats = np._run_upgrade(np._derive_upgrade_args(np._parse_args(["upgrade", str(target)])))
        assert "pyproject.toml" in stats["updated"]
        assert "application.yml" in stats["conflict"]
        assert "upgrade_flag = 1" in (target / "pyproject.toml").read_text(encoding="utf-8")
        assert (target / "new_file.md").exists()
        # 冲突文件未被覆盖（保留业务改动）
        yml_now = (target / "application.yml").read_text(encoding="utf-8")
        assert "biz: xxx" in yml_now
        assert "template: new" not in yml_now
        # 脚手架版本已更新
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["scaffold_version"] == "0.1.0"

    def test_upgrade_path_mapping_src_app(self, monkeypatch, mini_template: Path, tmp_path: Path):
        """src/app 模板路径映射到项目 src/<package>。"""
        self._make_base_snapshot(mini_template)
        target = self._generate_project(monkeypatch, mini_template, tmp_path)
        main_tmpl = mini_template / "src" / "app" / "main.py"
        main_tmpl.write_text(main_tmpl.read_text(encoding="utf-8") + "# new line\n", encoding="utf-8")
        np._run_upgrade(np._derive_upgrade_args(np._parse_args(["upgrade", str(target)])))
        assert "# new line" in (target / "src" / "my_project" / "main.py").read_text(encoding="utf-8")

    def test_upgrade_framework_version(self, monkeypatch, mini_template: Path, tmp_path: Path):
        """--framework-version 更新 .scaffold-info.json 的 framework_pin。"""
        self._make_base_snapshot(mini_template)
        target = self._generate_project(monkeypatch, mini_template, tmp_path)
        np._run_upgrade(np._derive_upgrade_args(
            np._parse_args(["upgrade", str(target), "--framework-version", "0.2.0"])
        ))
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["framework_pin"] == "0.2.0"

    def test_upgrade_missing_scaffold_info(self, monkeypatch, mini_template: Path, tmp_path: Path):
        """非脚手架生成项目（缺 .scaffold-info.json）应报错。"""
        plain = tmp_path / "plain"
        plain.mkdir()
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_template)
        with pytest.raises(SystemExit):
            np.main(["upgrade", str(plain)])


# ---------------------------------------------------------------------------
# 集成测试：快照（snapshot）
# ---------------------------------------------------------------------------
class TestSnapshot:
    """模板快照生成与脚手架专属内容排除。"""

    def test_snapshot_excludes_template_only(self, monkeypatch, mini_template: Path, tmp_path: Path):
        (mini_template / "docs" / "superpowers").mkdir()
        (mini_template / "docs" / "superpowers" / "design.md").write_text("design\n", encoding="utf-8")
        (mini_template / "docs" / "创建新项目.md").write_text("howto\n", encoding="utf-8")
        (mini_template / "tests" / "test_new_project.py").write_text("x\n", encoding="utf-8")
        monkeypatch.setattr(np, "PROJECT_ROOT", mini_template)
        target = np._run_snapshot("0.1.0")
        assert (target / "pyproject.toml").exists()
        assert (target / "docs" / "使用说明.md").exists()
        # 脚手架专属内容 / 脚本 / 快照自身均被排除
        assert not (target / "scripts").exists()
        assert not (target / "docs" / "superpowers").exists()
        assert not (target / "docs" / "创建新项目.md").exists()
        assert not (target / "tests" / "test_new_project.py").exists()
        assert not list(target.rglob("*.egg-info"))


# ---------------------------------------------------------------------------
# 单元测试：组件目录与参数解析
# ---------------------------------------------------------------------------
class TestComponentsCatalog:
    """组件目录完整性、注册中心禁内存实现、--components 解析。"""

    def test_registry_forbids_memory(self):
        """注册中心禁止内存实现（用户明确要求）。"""
        ids = [opt["id"] for opt in np.COMPONENTS["registry"]["options"]]
        assert "memory" not in ids
        assert "memory" in np.COMPONENTS["registry"].get("forbidden", ())

    def test_catalog_required_and_defaults(self):
        """必选组件（db）不可关闭；每个组件默认值为合法选项。"""
        assert np.COMPONENTS["db"]["off"] is False
        for name, spec in np.COMPONENTS.items():
            ids = [opt["id"] for opt in spec["options"]]
            if spec.get("off"):
                ids.insert(0, "off")
            default = spec.get("default", "off")
            assert default in ids, f"组件 {name} 默认实现 {default!r} 不在选项中"
            for opt in spec["options"]:
                for extra in spec.get("extras", {}).get(opt["id"], ()):
                    assert isinstance(extra, str)

    def test_parse_components_partial_fills_defaults(self):
        comps = np.resolve_components("cache:redis,mq:rocketmq")
        assert comps["cache"] == "redis"
        assert comps["mq"] == "rocketmq"
        assert comps["db"] == "mysql"          # 未显式指定取默认
        assert comps["registry"] == "off"      # 单体注册中心默认不使用
        assert "memory" not in {comps["registry"]}

    def test_parse_components_all_and_none(self):
        all_comps = np.resolve_components("all")
        assert all_comps["db"] == "mysql"
        assert all_comps["cache"] == "memory"
        none_comps = np.resolve_components("none")
        assert none_comps["db"] == "mysql"     # 必选组件保留默认
        assert none_comps["cache"] == "off"
        assert none_comps["registry"] == "off"

    def test_parse_components_unknown_raises(self):
        with pytest.raises(SystemExit):
            np.resolve_components("nacos:1")
        with pytest.raises(SystemExit):
            np.resolve_components("registry:memory")   # 未知实现（内存不在选项）
        with pytest.raises(SystemExit):
            np.resolve_components("bad_component:redis")

    def test_derive_names_components_from_args(self):
        names = np._derive_names(
            np._parse_args(["new", "my-project", "--components", "db:sqlite,cache:redis,registry:nacos"])
        )
        assert names["db_type"] == "sqlite"
        assert names["components"]["cache"] == "redis"
        assert names["components"]["registry"] == "nacos"

    def test_db_has_orm_custom_and_custom(self):
        """数据库组件提供两类自研选项：基于框架 ORM 自定义（orm_custom）与完全自定义（custom）。"""
        db = np.COMPONENTS["db"]
        ids = [opt["id"] for opt in db["options"]]
        assert "mysql" in ids and "sqlite" in ids
        assert "orm_custom" in ids and "custom" in ids
        orm_opt = next(o for o in db["options"] if o["id"] == "orm_custom")
        custom_opt = next(o for o in db["options"] if o["id"] == "custom")
        assert orm_opt.get("strategy") is True
        assert custom_opt.get("strategy") is True
        # 策略型实现不产生 mysql extra 之外的额外依赖（完全自定义由用户自定驱动）
        assert db["extras"]["orm_custom"] == ("mysql",)
        assert db["extras"]["custom"] == ()

    def test_render_capabilities(self):
        """能力装配清单（app.capabilities.enabled）：按组件选择映射、去重、未选不参与。"""
        comps = np.resolve_components("payment:memory,jwt:default,social:demo")
        # 默认启用的 db/cache/storage/mq + payment/pay + jwt/social 同属 authn（去重）
        assert np.render_capabilities(comps) == ["db", "cache", "storage", "mq", "pay", "authn"]
        comps = np.resolve_components("none")
        assert np.render_capabilities(comps) == ["db"]                  # 必选 db 默认启用

    def test_apply_capabilities_to_text(self):
        """能力装配段渲染：模板 enabled: [] 替换为所选能力清单；无映射组件保持空列表。"""
        text = "app:\n  capabilities:\n    enabled: []\n  cache:\n    type: memory\n"
        comps = np.resolve_components("payment:wechat,jwt:default")
        updated = np.apply_capabilities_to_text(text, comps)
        assert 'enabled: ["db", "cache", "storage", "mq", "pay", "authn"]' in updated
        # 未选择任何可映射组件（仅 db 必选）时仅保留 db
        comps = np.resolve_components("none")
        updated = np.apply_capabilities_to_text(text, comps)
        assert 'enabled: ["db"]' in updated


# ---------------------------------------------------------------------------
# 单元测试：标记块裁剪与实现替换
# ---------------------------------------------------------------------------
class TestComponentBlocks:
    """组件标记块移除与块内 type/enabled 替换。"""

    def test_remove_unselected_block(self):
        text = (
            "app:\n"
            "  name: x\n"
            "  # <<<COMPONENT:cache>>>\n"
            "  cache:\n"
            "    type: memory\n"
            "  # <<</COMPONENT:cache>>>\n"
            "  db:\n"
            "    type: mysql\n"
        )
        comps = {name: ("off" if name != "db" else "mysql") for name in np.COMPONENTS}
        updated = np.apply_components_to_text(text, comps)
        assert "COMPONENT:cache" not in updated
        assert "cache:" not in updated
        assert "type: mysql" in updated

    def test_type_replacement_within_block(self):
        text = (
            "  # <<<COMPONENT:cache>>>\n"
            "  cache:\n"
            "    type: memory\n"
            "  # <<</COMPONENT:cache>>>\n"
        )
        comps = {name: ("off" if name != "cache" else "redis") for name in np.COMPONENTS}
        updated = np.apply_components_to_text(text, comps)
        assert "type: redis" in updated
        assert "type: memory" not in updated
        assert "COMPONENT:cache" in updated  # 已选择组件的标记块保留（供 upgrade 对照）

    def test_flag_enable_within_block(self):
        text = (
            "  # <<<COMPONENT:ai>>>\n"
            "  ai:\n"
            "    enabled: false\n"
            "  # <<</COMPONENT:ai>>>\n"
        )
        comps = {name: ("off" if name != "ai" else "default") for name in np.COMPONENTS}
        updated = np.apply_components_to_text(text, comps)
        assert "enabled: true" in updated
        assert "enabled: false" not in updated

    def test_custom_keeps_default_type(self):
        """custom 实现保留模板默认 type，另由骨架生成兜底。"""
        text = (
            "  # <<<COMPONENT:cache>>>\n"
            "  cache:\n"
            "    type: memory\n"
            "  # <<</COMPONENT:cache>>>\n"
        )
        comps = {name: ("off" if name != "cache" else "custom") for name in np.COMPONENTS}
        updated = np.apply_components_to_text(text, comps)
        assert "type: memory" in updated
        assert "COMPONENT:cache" in updated

    def test_db_strategy_impls_keep_type(self):
        """db=orm_custom / db=custom：策略型实现不写 type（保持模板默认 mysql），避免框架装配非法 type。"""
        text = (
            "  # <<<COMPONENT:db>>>\n"
            "  db:\n"
            "    type: mysql\n"
            "  # <<</COMPONENT:db>>>\n"
        )
        for impl in ("orm_custom", "custom"):
            comps = {name: ("off" if name != "db" else impl) for name in np.COMPONENTS}
            updated = np.apply_components_to_text(text, comps)
            assert "type: mysql" in updated, f"db={impl} 不应改写 type"
            assert "COMPONENT:db" in updated

    def test_db_sqlite_replaces_type(self):
        """db=sqlite：type mysql -> sqlite（真实 type 值可写）。"""
        text = (
            "  # <<<COMPONENT:db>>>\n"
            "  db:\n"
            "    type: mysql\n"
            "  # <<</COMPONENT:db>>>\n"
        )
        comps = {name: ("off" if name != "db" else "sqlite") for name in np.COMPONENTS}
        updated = np.apply_components_to_text(text, comps)
        assert "type: sqlite" in updated
        assert "type: mysql" not in updated

    def test_render_extras(self):
        comps = np.resolve_components("cache:redis,mq:rocketmq,registry:nacos,mongo:default")
        extras = np.render_extras(comps)
        assert extras == "mysql,redis,rocketmq,nacos,mongo,migrate"

    def test_render_extras_db_strategy(self):
        """db=orm_custom 仍需 mysql extra（复用 SQLAlchemy）；db=custom 不强制 mysql。"""
        comps = np.resolve_components("db:orm_custom")
        assert np.render_extras(comps) == "mysql,migrate"
        comps = np.resolve_components("db:custom")
        assert np.render_extras(comps) == "migrate"

    def test_generate_spi_skeletons(self, tmp_path: Path):
        comps = np.resolve_components("cache:custom,registry:custom")
        generated = np.generate_spi_skeletons(tmp_path, "demo_pkg", comps)
        assert "cache" in generated and "registry" in generated
        skeleton = tmp_path / "src" / "demo_pkg" / "spi" / "cache_custom.py"
        assert skeleton.exists()
        assert "CacheBackendInterface" in skeleton.read_text(encoding="utf-8")
        assert (tmp_path / "src" / "demo_pkg" / "spi" / "__init__.py").exists()

    def test_generate_db_skeletons(self, tmp_path: Path):
        """db=orm_custom 生成 db_orm_custom.py；db=custom 生成 db_custom.py（两类自研骨架）。"""
        comps = np.resolve_components("db:orm_custom")
        generated = np.generate_spi_skeletons(tmp_path, "demo_pkg", comps)
        assert generated == ["db"]
        orm_sk = tmp_path / "src" / "demo_pkg" / "spi" / "db_orm_custom.py"
        assert orm_sk.exists()
        assert "OrmCustomDatabaseSession" in orm_sk.read_text(encoding="utf-8")
        assert "DatabaseSessionInterface" in orm_sk.read_text(encoding="utf-8")

        comps = np.resolve_components("db:custom")
        np.generate_spi_skeletons(tmp_path, "demo_pkg", comps)
        full_sk = tmp_path / "src" / "demo_pkg" / "spi" / "db_custom.py"
        assert full_sk.exists()
        assert "CustomDatabaseFactory" in full_sk.read_text(encoding="utf-8")
        assert "DatabaseFactoryInterface" in full_sk.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 集成测试：含标记块的迷你模板端到端生成（--components 裁剪 + 骨架）
# ---------------------------------------------------------------------------
class TestEndToEndComponents:
    """带组件标记块的模板按 --components 裁剪生成。"""

    def _make_template(self, tmp_path: Path) -> Path:
        root = tmp_path / "comp-template"
        (root / "src" / "app").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "docs").mkdir()
        (root / "tests").mkdir()
        (root / "pyproject.toml").write_text(
            'name = "flower-monomer-scaffolding"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        yml = (
            "app:\n"
            "  name: flower-monomer-scaffolding\n"
            "  # <<<COMPONENT:cache>>>\n"
            "  cache:\n"
            "    type: memory\n"
            "  # <<</COMPONENT:cache>>>\n"
            "  # <<<COMPONENT:mq>>>\n"
            "  mq:\n"
            "    type: memory\n"
            "  # <<</COMPONENT:mq>>>\n"
            "  # <<<COMPONENT:registry>>>\n"
            "  registry:\n"
            "    type: nacos\n"
            "  # <<</COMPONENT:registry>>>\n"
        )
        (root / "application.yml").write_text(yml, encoding="utf-8")
        (root / "src" / "app" / "main.py").write_text(
            "from app.api.v1.user_controller import router\n"
            "app.include_router(router)\n",
            encoding="utf-8",
        )
        (root / "docs" / "使用说明.md").write_text(
            "参考 flower-monomer-scaffolding 脚手架，库名 flower_monomer\n", encoding="utf-8"
        )
        (root / "scripts" / "keep_me.txt").write_text("scripts 目录应被整体删除\n", encoding="utf-8")
        (root / "tests" / "test_new_project.py").write_text("assert False\n", encoding="utf-8")
        return root

    def test_generate_with_components(self, monkeypatch, tmp_path: Path):
        template = self._make_template(tmp_path)
        monkeypatch.setattr(np, "PROJECT_ROOT", template)
        target = tmp_path / "generated"
        np.main([
            "new", "my-project", "--dir", str(target),
            "--components", "cache:redis,mq:rocketmq",
        ])
        yml = (target / "application.yml").read_text(encoding="utf-8")
        assert "type: redis" in yml
        assert "type: rocketmq" in yml
        # 未选择/关闭的组件（registry 默认 off）整块移除；已选组件标记块保留（供 upgrade 对照）
        assert "COMPONENT:registry" not in yml
        assert "registry" not in yml
        assert "COMPONENT:cache" in yml
        assert "COMPONENT:mq" in yml
        # 组件选择记录写入升级元数据
        info = json.loads((target / np.SCAFFOLD_INFO_FILE).read_text(encoding="utf-8"))
        assert info["components"]["cache"] == "redis"
        assert info["components"]["mq"] == "rocketmq"
        assert info["components"]["registry"] == "off"

    def test_generate_with_custom_skeleton(self, monkeypatch, tmp_path: Path):
        template = self._make_template(tmp_path)
        monkeypatch.setattr(np, "PROJECT_ROOT", template)
        target = tmp_path / "generated"
        np.main([
            "new", "my-project", "--dir", str(target),
            "--components", "cache:custom",
        ])
        skeleton = target / "src" / "my_project" / "spi" / "cache_custom.py"
        assert skeleton.exists()
        # custom 保留模板默认 type
        yml = (target / "application.yml").read_text(encoding="utf-8")
        assert "type: memory" in yml
        assert "COMPONENT:cache" in yml
