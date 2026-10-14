from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ("name", "function", "modules", "input", "output", "contract", "depends", "tests")
NON_EMPTY = ("contract", "tests")


def _load_all() -> dict[str, dict]:
    found: dict[str, dict] = {}
    pending = [ROOT]
    while pending:
        module_dir = pending.pop()
        data = yaml.safe_load((module_dir / "interface.yaml").read_text(encoding="utf-8"))
        key = module_dir.relative_to(ROOT).as_posix() if module_dir != ROOT else "."
        found[key] = data
        for child in data.get("modules") or []:
            pending.append(module_dir / child["path"])
    return found


MODULES = _load_all()


def test_every_interface_yaml_is_registered():
    on_disk = {
        p.parent.relative_to(ROOT).as_posix() if p.parent != ROOT else "."
        for p in ROOT.rglob("interface.yaml")
        if not {".conda", "build", "dist", ".git"} & set(p.relative_to(ROOT).parts)
    }
    assert on_disk == set(MODULES)


@pytest.mark.parametrize("module", sorted(MODULES))
def test_required_fields(module):
    data = MODULES[module]
    missing = [f for f in REQUIRED if f not in data]
    assert not missing, f"{module} 缺字段 {missing}"
    for field in NON_EMPTY:
        assert data[field], f"{module} 的 {field} 不能为空"
    for field in ("modules", "input", "output", "depends"):
        assert isinstance(data[field], list), f"{module} 的 {field} 须为列表"


@pytest.mark.parametrize("module", sorted(MODULES))
def test_child_function_matches_parent_registration(module):
    base = ROOT / module
    for child in MODULES[module]["modules"]:
        child_key = (base / child["path"]).relative_to(ROOT).as_posix()
        assert MODULES[child_key]["function"] == child["function"], child_key


@pytest.mark.parametrize("module", sorted(MODULES))
def test_depends_point_to_modules(module):
    for dep in MODULES[module]["depends"]:
        assert dep in MODULES, f"{module} depends 未知 Module {dep}"
        assert dep != module


def test_no_dependency_cycles():
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        if state.get(node) == 2:
            return
        assert state.get(node) != 1, "循环依赖：" + " -> ".join(stack + [node])
        state[node] = 1
        for dep in MODULES[node]["depends"]:
            visit(dep, stack + [node])
        state[node] = 2

    for module in MODULES:
        visit(module, [])
