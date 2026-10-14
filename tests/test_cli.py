"""The console commands explain a missing extra instead of dumping a traceback."""

import sys

import pytest

from moriti import cli


@pytest.mark.parametrize(
    ("entry", "blocked", "extra"),
    [(cli.proxy, "mcp", "mcp"), (cli.serve, "starlette", "serve")],
)
def test_missing_extra_is_an_instruction_not_a_traceback(monkeypatch, capsys, entry, blocked, extra):
    for module in ("moriti.mcp.proxy", "moriti.http.service", "moriti.http"):
        monkeypatch.delitem(sys.modules, module, raising=False)
    # `import <blocked>` now raises ImportError, even when other tests already imported its submodules.
    for name in [m for m in sys.modules if m == blocked or m.startswith(blocked + ".")] + [blocked]:
        monkeypatch.setitem(sys.modules, name, None)

    with pytest.raises(SystemExit) as excinfo:
        entry()

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert f"pip install 'moriti[{extra}]'" in err
    assert "Traceback" not in err


def test_a_missing_moriti_module_is_not_hidden(monkeypatch):
    with pytest.raises(ModuleNotFoundError):
        cli._run("moriti.does_not_exist", "moriti-proxy", "mcp")
