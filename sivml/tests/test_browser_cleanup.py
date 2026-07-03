"""
Regresion: cuando un proceso de scraping muere abruptamente (crash, kill
forzado, conflicto de puertos, reinicio de Streamlit por cambio de codigo),
el `finally: browser.close()` de Playwright nunca se ejecuta y el proceso
de Chromium queda huerfano corriendo indefinidamente. Estos tests cubren
la logica de IDENTIFICACION (que proceso es seguro terminar) -- la parte
critica de seguridad: nunca debe marcar como huerfano el navegador
personal del usuario.
"""
from scrapers.browser_cleanup import _is_playwright_browser, _has_live_python_ancestor


class FakeProcess:
    def __init__(self, exe_path="", name="chrome.exe", parent=None):
        self._exe_path = exe_path
        self._name = name
        self._parent = parent

    def exe(self):
        return self._exe_path

    def name(self):
        return self._name

    def parent(self):
        return self._parent


class TestIsPlaywrightBrowser:
    def test_recognizes_ms_playwright_path(self):
        proc = FakeProcess(exe_path=r"C:\Users\LM\AppData\Local\ms-playwright\chromium-1223\chrome-win\chrome.exe")
        assert _is_playwright_browser(proc) is True

    def test_ignores_regular_installed_chrome(self):
        proc = FakeProcess(exe_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        assert _is_playwright_browser(proc) is False

    def test_ignores_other_processes(self):
        proc = FakeProcess(exe_path=r"C:\Windows\explorer.exe", name="explorer.exe")
        assert _is_playwright_browser(proc) is False

    def test_case_insensitive_path_match(self):
        proc = FakeProcess(exe_path=r"C:\Users\LM\AppData\Local\MS-PLAYWRIGHT\chromium-1223\chrome.exe")
        assert _is_playwright_browser(proc) is True


class TestHasLivePythonAncestor:
    def test_direct_python_parent(self):
        parent = FakeProcess(name="python.exe")
        proc = FakeProcess(parent=parent)
        assert _has_live_python_ancestor(proc) is True

    def test_python_grandparent(self):
        grandparent = FakeProcess(name="python.exe")
        parent = FakeProcess(name="chrome.exe", parent=grandparent)
        proc = FakeProcess(parent=parent)
        assert _has_live_python_ancestor(proc) is True

    def test_no_python_ancestor_orphaned_under_explorer(self):
        # Windows reasigna procesos huerfanos a explorer.exe cuando su
        # padre original muere -- este es exactamente el caso a detectar.
        parent = FakeProcess(name="explorer.exe", parent=None)
        proc = FakeProcess(parent=parent)
        assert _has_live_python_ancestor(proc) is False

    def test_no_parent_at_all(self):
        proc = FakeProcess(parent=None)
        assert _has_live_python_ancestor(proc) is False
