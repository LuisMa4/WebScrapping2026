from dashboard.theme import badge_html, status_emoji, STATUS_META


class TestBadgeHtml:
    def test_known_status_uses_its_label_and_colors(self):
        html = badge_html("completed")
        assert "Completado" in html
        _, bg, fg = STATUS_META["completed"]
        assert bg in html
        assert fg in html

    def test_unknown_status_falls_back_to_raw_text_gray_badge(self):
        html = badge_html("algo_raro")
        assert "algo_raro" in html
        assert "<span" in html

    def test_all_meta_entries_produce_valid_span(self):
        for key in STATUS_META:
            html = badge_html(key)
            assert html.startswith('<span style="')
            assert html.endswith("</span>")


class TestStatusEmoji:
    def test_known_statuses_have_distinct_emoji(self):
        keys = ["completed", "running", "queued", "failed", "stopped"]
        emojis = {status_emoji(k) for k in keys}
        assert len(emojis) == len(keys), "cada estado debe tener un emoji distinto"

    def test_unknown_status_returns_default(self):
        assert status_emoji("no_existe") == "⚪"
