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


def test_completed_upload_replaces_cancel_action_with_translated_disabled_button() -> None:
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'setUploadActionState("cancel");' in script
    assert 'setUploadActionState("complete");' in script
    assert "function setUploadActionState(state)" in script
    assert "cancelUploadButton.disabled = completed;" in script
    assert 'completed ? t("uploadComplete") : t("cancelUpload")' in script
    assert 'cancelUploadButton.dataset.uploadActionState || "cancel"' in script


def test_upload_progress_displays_eta() -> None:
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert "startedAt: Date.now()" in script
    assert "function formatUploadEta(done, total, uploadState)" in script
    assert "function formatDuration(seconds)" in script
    assert 'parts.push(`${hours}h`);' in script
    assert 'if (minutes) parts.push(`${minutes}m`);' in script
    assert 'parts.push(`${secs}s`);' in script
    assert 't("eta")' in script
    assert "${eta}" in script


def test_upload_form_exposes_initial_probe_size_control() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'id="upload-probe-size"' in markup
    assert 'id="upload-probe-unit"' in markup
    assert '<option value="tb">TB</option>' in markup
    assert '<option value="gb">GB</option>' in markup
    assert '<option value="mb" selected>MB</option>' in markup
    assert '<option value="kb">KB</option>' in markup
    assert '<option value="b">B</option>' in markup
    assert 'form.append("upload_command_size_bytes", String(uploadProbeSizeBytes()));' in script
    assert "function uploadProbeSizeBytes()" in script
    assert "const MIN_UPLOAD_PROBE_BYTES = 64;" in script
    assert "uploadProbeSizeInput.addEventListener(\"blur\", normalizeUploadProbeSize);" in script
    assert "uploadProbeUnitSelect.addEventListener(\"change\", normalizeUploadProbeSize);" in script
    assert "function applyUploadDefaults(config)" in script
    assert "applyUploadDefaults(runtimeConfig);" in script
    assert "const UPLOAD_PROBE_UNITS_DESC = [\"tb\", \"gb\", \"mb\", \"kb\", \"b\"];" in script
    assert "setUploadProbeSizeFromBytes(bytes);" in script
    assert 'uploadProbeSizeInput.value = String(MIN_UPLOAD_PROBE_BYTES);' in script
    assert 'uploadProbeUnitSelect.value = "b";' in script


def test_files_panel_tracks_remote_current_directory_for_upload_defaults() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'id="cwd-sync" type="checkbox" checked' in markup
    assert 'data-i18n="cwdSync"' in markup
    assert 'id="current-directory"' in markup
    assert 'data-i18n="currentDirectory"' in markup
    assert "readonly" in markup
    assert 'const currentDirectoryInput = document.querySelector("#current-directory");' in script
    assert 'const uploadPathInput = document.querySelector("#upload-path");' in script
    assert 'const cwdSyncInput = document.querySelector("#cwd-sync");' in script
    assert 'cwdSync: "CWD Sync"' in script
    assert 'currentDirectory: "Current directory"' in script
    assert 'currentDirectory: "当前目录"' in script
    assert "cwd_sync: cwdSyncInput.checked" in script
    assert 'ws.send(JSON.stringify({ type: "cwd_sync", enabled: cwdSyncEnabled }));' in script
    assert 'message.type === "cwd_sync"' in script
    assert 'setCurrentWorkingDirectory(message.cwd || "");' in script
    assert 'message.type === "cwd"' in script
    assert 'currentDirectoryInput.classList.toggle("locked", !cwdSyncEnabled);' in script
    assert "function updateUploadPathDefault()" in script
    assert "uploadPathInput.value = currentWorkingDirectory;" in script


def test_frontend_enforces_target_host_security_policies_before_submit() -> None:
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert "function validateTargetHostPolicy(host)" in script
    assert "const security = runtimeConfig.security || {};" in script
    assert "security.ban_dns && !address" in script
    assert "security.ban_ipv6 && address && address.version === 6" in script
    assert "function parseIpLiteral(host)" in script
    assert "function isIpv4Literal(value)" in script
    assert "function isIpv6Literal(value)" in script
    assert "const policyError = validateTargetHostPolicy(payload.host);" in script
    assert "appendLogLine(policyError);" in script
    assert 'return t("dnsHostBlocked");' in script
    assert 'return t("ipv6HostBlocked");' in script


def test_closed_non_empty_terminal_is_guarded_from_focus_and_clicks() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    styles = Path("webssh/static/styles.css").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'id="terminal-guard"' in markup
    assert ".terminal-guard" in styles
    assert "pointer-events: auto;" in styles
    assert "#terminal.terminal-disabled" in styles
    assert "function setSessionState(state)" in script
    assert 'currentSessionState === "closed" && terminalHasText()' in script
    assert 'terminalGuardElement.hidden = !disabled;' in script
    assert 'terminalElement.classList.toggle("terminal-disabled", disabled);' in script
    assert 'focusTarget.setAttribute("tabindex", "-1");' in script
    assert "focusTarget.blur();" in script
    assert "setTerminalSessionState(\"\");" in script


def test_terminal_directory_panel_uses_cwd_sync_listing_and_download_progress() -> None:
    markup = Path("webssh/static/index.html").read_text(encoding="utf-8")
    styles = Path("webssh/static/styles.css").read_text(encoding="utf-8")
    script = Path("webssh/static/app.js").read_text(encoding="utf-8")

    assert 'id="directory-panel"' in markup
    assert 'id="directory-panel-toggle"' in markup
    assert 'id="directory-panel-cwd"' in markup
    assert 'id="directory-table-body"' in markup
    assert 'id="download-progress"' in markup
    assert 'id="cancel-download"' in markup
    assert ".directory-panel.collapsed" in styles
    assert ".directory-panel.busy" in styles
    assert 'cwdSyncDisabledHint: "Enable CWD Sync to display content."' in script
    assert 'cwdSyncDisabledHint: "启用 CWD Sync 以显示内容。"' in script
    assert 'message.type === "directory_listing"' in script
    assert "function renderDirectoryPanel()" in script
    assert "function startDirectoryDownload(entry)" in script
    assert "function startDownload(remotePath)" in script
    assert 'fetch(`/api/sessions/${sessionId}/files/downloads`' in script
    assert 'fetch(`/api/transfers/${downloadState.transferId}/download`' in script
    assert 'await fetch(`/api/transfers/${activeDownload.transferId}`, { method: "DELETE" });' in script
    assert "downloadForm.querySelectorAll(\"input, button\")" in script


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
