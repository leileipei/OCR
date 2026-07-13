from pathlib import Path

from umi_web_spike.plugin_runner import PluginRunner


def test_runs_plugin_without_qt_or_qml():
    plugin_root = Path(__file__).parent / "fakes"
    runner = PluginRunner(plugin_root, "fake_ocr_plugin", {"model": "fake"})
    runner.start({"language": "简体中文"})
    result = runner.run_path(Path("sample.png"))
    runner.close()

    assert result.code == 100
    assert result.blocks[0].text == "sample.png"


def test_rejects_non_ocr_plugin(tmp_path):
    package = tmp_path / "bad_plugin"
    package.mkdir()
    (package / "__init__.py").write_text("PluginInfo = {'group': 'other'}", encoding="utf-8")
    try:
        PluginRunner(tmp_path, "bad_plugin", {})
    except ValueError as error:
        assert "group must be ocr" in str(error)
    else:
        raise AssertionError("invalid plugin was accepted")
