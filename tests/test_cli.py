import json

import fitz
from PIL import Image

from umi_web_spike.cli import main


def test_validate_ocr_with_fake_plugin(tmp_path):
    image = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), "white").save(image)
    pdf = tmp_path / "sample.pdf"
    document = fitz.open()
    document.new_page(width=200, height=100)
    document.save(pdf)

    global_options = tmp_path / "global.json"
    local_options = tmp_path / "local.json"
    global_options.write_text(json.dumps({}), encoding="utf-8")
    local_options.write_text(json.dumps({}), encoding="utf-8")
    output = tmp_path / "results"

    code = main(
        [
            "validate-ocr",
            "--plugin-root",
            "tests/fakes",
            "--plugin-name",
            "fake_ocr_plugin",
            "--global-options-json",
            str(global_options),
            "--local-options-json",
            str(local_options),
            "--image",
            str(image),
            "--pdf",
            str(pdf),
            "--output-dir",
            str(output),
        ]
    )

    assert code == 0
    assert (output / "ocr-image.json").exists()
    assert (output / "ocr-pdf.json").exists()
    assert (output / "resources.json").exists()
    assert (output / "searchable.pdf").exists()
