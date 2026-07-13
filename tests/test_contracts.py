import json

from umi_web_spike.contracts import OcrBlock, OcrResult, ProbeResult


def test_normalizes_umi_plugin_result(tmp_path):
    raw = {
        "code": 100,
        "data": [
            {
                "text": "示例",
                "score": 0.98,
                "box": [[1, 2], [11, 2], [11, 12], [1, 12]],
            }
        ],
    }
    result = OcrResult.from_plugin_dict(raw)
    assert result.code == 100
    assert result.blocks == (
        OcrBlock(
            text="示例",
            score=0.98,
            box=((1.0, 2.0), (11.0, 2.0), (11.0, 12.0), (1.0, 12.0)),
        ),
    )

    output = tmp_path / "probe.json"
    ProbeResult(ok=True, name="contracts", details={"blocks": 1}).write_json(output)
    assert json.loads(output.read_text(encoding="utf-8"))["ok"] is True


def test_rejects_malformed_success_result():
    try:
        OcrResult.from_plugin_dict({"code": 100, "data": "not-a-list"})
    except ValueError as error:
        assert "data must be a list" in str(error)
    else:
        raise AssertionError("malformed plugin result was accepted")
