from html.parser import HTMLParser
from pathlib import Path


class StaticHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags_by_id: dict[str, str] = {}
        self.attrs_by_id: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        element_id = attrs_dict.get("id")
        if element_id:
            self.tags_by_id[element_id] = tag
            self.attrs_by_id[element_id] = attrs_dict


def test_connect_form_exists_inside_accordion_panel() -> None:
    parser = StaticHtmlParser()
    parser.feed(Path("webssh/static/index.html").read_text(encoding="utf-8"))

    assert parser.tags_by_id["connect-panel"] == "div"
    assert parser.tags_by_id["connect-form"] == "form"
    assert "action" not in parser.attrs_by_id["connect-form"]
    assert "method" not in parser.attrs_by_id["connect-form"]


def test_connect_submit_uses_fetch_without_page_navigation() -> None:
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'document.querySelector("#connect-form").addEventListener("submit"' in script
    assert 'fetch("/api/sessions"' in script
    assert "event.preventDefault();" in script
    assert "window.location =" not in script
    assert "window.location.href" not in script
    assert "location.href" not in script
