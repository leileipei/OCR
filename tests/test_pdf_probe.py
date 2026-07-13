import fitz

from umi_web_spike.pdf_probe import add_invisible_text_layer, render_pages


def make_pdf(path):
    document = fitz.open()
    document.new_page(width=300, height=200)
    document.save(path)


def test_renders_every_page_and_adds_searchable_text(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "searchable.pdf"
    make_pdf(source)

    pages = render_pages(source, tmp_path / "pages", dpi=96)
    assert [path.name for path in pages] == ["page-000001.png"]

    add_invisible_text_layer(source, output, ["识别结果 ABC-123"])
    with fitz.open(output) as document:
        assert "ABC-123" in document[0].get_text()


def test_rejects_page_count_mismatch(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    try:
        add_invisible_text_layer(source, tmp_path / "out.pdf", [])
    except ValueError as error:
        assert "page count" in str(error)
    else:
        raise AssertionError("page count mismatch was accepted")
