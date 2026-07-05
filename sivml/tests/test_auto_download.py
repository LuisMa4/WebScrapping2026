import base64

from dashboard.auto_download import build_auto_download_html


class TestBuildAutoDownloadHtml:
    def test_contains_base64_of_file_bytes(self):
        content = b"fake excel bytes"
        html = build_auto_download_html(content, "SIVML_test.xlsx", "application/vnd.test")
        assert base64.b64encode(content).decode("ascii") in html

    def test_contains_filename_in_download_attribute(self):
        html = build_auto_download_html(b"x", "SIVML_abc.xlsx", "application/vnd.test")
        assert 'download="SIVML_abc.xlsx"' in html

    def test_contains_mime_type_in_data_uri(self):
        html = build_auto_download_html(b"x", "f.xlsx", "application/vnd.openxmlformats")
        assert "data:application/vnd.openxmlformats;base64," in html

    def test_contains_script_that_clicks_the_link(self):
        html = build_auto_download_html(b"x", "f.xlsx", "application/vnd.test")
        assert "document.getElementById(\"sivml_auto_dl\").click();" in html

    def test_strips_quotes_from_filename_to_avoid_breaking_html(self):
        html = build_auto_download_html(b"x", 'evil".xlsx', "application/vnd.test")
        assert 'download="evil.xlsx"' in html
