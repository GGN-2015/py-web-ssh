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


def test_frontend_defaults_to_english_and_has_language_cookie() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert '<html lang="en">' in markup
    assert 'const LANGUAGE_COOKIE = "py_web_ssh_lang";' in script
    assert "applyLanguage(currentLanguage);" in script
    assert "setLanguageCookie(currentLanguage);" in script
    assert "zh-CN" in script


def test_frontend_branding_comes_from_server_config_and_not_i18n() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert "<title>__APP_TITLE__</title>" in markup
    assert 'id="app-title">__APP_TITLE__' in markup
    assert 'id="app-subtitle">__APP_SUBTITLE__' in markup
    assert 'id="app-version">(py-web-ssh v__APP_VERSION__)' in markup
    assert 'data-i18n="subtitle"' not in markup
    assert "subtitle:" not in script
    assert "function applyBranding(config)" in script
    assert "document.title = title;" in script
    assert 'appVersionElement.textContent = `(py-web-ssh v${version})`;' in script


def test_frontend_has_lock_aware_fields_without_sensitive_values() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'id="password-lock-note"' in markup
    assert 'id="private-key-lock-note"' in markup
    assert "Password is forced by the server." in markup
    assert "Private key file is forced by the server." in markup
    assert 'fetch("/api/config")' in script
    assert 'lockTextInput("#host", locks.host);' in script
    assert 'lockTextInput("#username", locks.username);' in script


def test_upload_cancel_can_abort_the_xhr_request() -> None:
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert "return { xhr, promise };" in script
    assert "uploadState.xhr = xhrUpload.xhr;" in script
    assert "activeUpload.xhr.abort();" in script


def test_frontend_no_longer_exposes_agent_or_known_hosts_controls() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    forbidden = ["allow-agent", "strict-host-key", "SSH agent", "known_hosts", "allow_agent", "strict_host_key"]
    for text in forbidden:
        assert text not in markup
        assert text not in script


def test_frontend_exposes_algorithm_panel_and_disabled_algorithm_payload() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'id="algorithms-panel"' in markup
    assert 'id="algorithm-groups"' in markup
    assert 'fetch("/api/algorithms")' in script
    assert "collectDisabledAlgorithms()" in script
    assert "disabled_algorithms: collectDisabledAlgorithms()" in script


def test_frontend_no_longer_exposes_legacy_algorithm_toggle() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    forbidden = ["legacy-algorithms", "legacyAlgorithms", "legacy_algorithms"]
    for text in forbidden:
        assert text not in markup
        assert text not in script
