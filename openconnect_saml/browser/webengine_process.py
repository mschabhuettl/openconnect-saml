import asyncio
import contextlib
import json
import multiprocessing
import signal
import sys
from importlib import resources
from urllib.parse import urlparse

import attr
import structlog
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSlot
from PyQt6.QtNetwork import QNetworkCookie, QNetworkProxy
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# WebAuthn UX support arrived in QtWebEngine 6.7. Older versions don't expose
# QWebEngineWebAuthUxRequest, so we feature-detect and fall back gracefully (#24).
try:
    from PyQt6.QtWebEngineCore import QWebEngineWebAuthUxRequest

    _HAS_WEBAUTHN_UX = True
except ImportError:  # pragma: no cover - depends on Qt build
    QWebEngineWebAuthUxRequest = None
    _HAS_WEBAUTHN_UX = False

from openconnect_saml import config

app = None
profile = None
logger = structlog.get_logger("webengine")


def configure_webengine_logger():
    """Configure structlog for the webengine subprocess to use stderr (#208)."""
    import logging as _logging

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    formatter = structlog.stdlib.ProcessorFormatter(processor=structlog.dev.ConsoleRenderer())
    handler = _logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger = _logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(_logging.DEBUG)


@attr.s
class Url:
    url = attr.ib()


@attr.s
class Credentials:
    credentials = attr.ib()


@attr.s
class StartupInfo:
    url = attr.ib()
    credentials = attr.ib()


@attr.s
class SetCookie:
    name = attr.ib()
    value = attr.ib()


class Process(multiprocessing.Process):
    def __init__(self, proxy, display_mode, window_width=800, window_height=600):
        super().__init__()

        self._commands = multiprocessing.Queue()
        self._states = multiprocessing.Queue()
        self.proxy = proxy
        self.display_mode = display_mode
        self.window_width = window_width
        self.window_height = window_height

    def authenticate_at(self, url, credentials):
        self._commands.put(StartupInfo(url, credentials))

    async def get_state_async(self):
        while self.is_alive():
            try:
                return self._states.get_nowait()
            except multiprocessing.queues.Empty:
                await asyncio.sleep(0.01)
        if not self.is_alive():
            raise EOFError()

    def run(self):
        # To work around funky GC conflicts with C++ code by ensuring QApplication terminates last
        global app
        global profile

        # Redirect all logging to stderr to avoid polluting stdout (#208)
        configure_webengine_logger()

        signal.signal(signal.SIGTERM, on_sigterm)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        cfg = config.load()

        argv = sys.argv.copy()
        if self.display_mode == config.DisplayMode.HIDDEN:
            argv += ["-platform", "minimal"]
        app = QApplication(argv)
        profile = QWebEngineProfile("openconnect-saml")

        if self.proxy:
            parsed = urlparse(self.proxy)
            if parsed.scheme.startswith("socks5"):
                proxy_type = QNetworkProxy.Socks5Proxy
            elif parsed.scheme.startswith("http"):
                proxy_type = QNetworkProxy.HttpProxy
            else:
                raise ValueError("Unsupported proxy type", parsed.scheme)
            proxy = QNetworkProxy(proxy_type, parsed.hostname, parsed.port)

            QNetworkProxy.setApplicationProxy(proxy)

        # In order to make Python able to handle signals
        force_python_execution = QTimer()
        force_python_execution.start(200)

        def ignore():
            pass

        force_python_execution.timeout.connect(ignore)
        web = WebBrowser(cfg.auto_fill_rules, self._states.put, profile)
        web.resize(self.window_width, self.window_height)

        startup_info = self._commands.get()
        logger.info("Browser started", startup_info=startup_info)

        logger.info("Loading page", url=startup_info.url)

        web.authenticate_at(QUrl(startup_info.url), startup_info.credentials)

        web.show()
        rc = app.exec()

        logger.info("Exiting browser")
        return rc

    async def wait(self):
        while self.is_alive():
            await asyncio.sleep(0.01)
        self.join()


def on_sigterm(signum, frame):
    global profile
    logger.info("Terminate requested.")
    # Force flush cookieStore to disk. Without this hack the cookieStore may
    # not be synced at all if the browser lives only for a short amount of
    # time. Something is off with the call order of destructors as there is no
    # such issue in C++.

    # See: https://github.com/qutebrowser/qutebrowser/commit/8d55d093f29008b268569cdec28b700a8c42d761
    cookie = QNetworkCookie()
    profile.cookieStore().deleteCookie(cookie)

    # Give some time to actually save cookies
    exit_timer = QTimer(app)
    exit_timer.timeout.connect(QApplication.quit)
    exit_timer.start(1000)  # ms


class WebBrowser(QWebEngineView):
    def __init__(self, auto_fill_rules, on_update, profile):
        super().__init__()
        self._on_update = on_update
        self._auto_fill_rules = auto_fill_rules
        self._webauthn_request = None
        page = QWebEnginePage(profile, self)
        self.setPage(page)
        cookie_store = self.page().profile().cookieStore()
        cookie_store.cookieAdded.connect(self._on_cookie_added)
        self.page().loadFinished.connect(self._on_load_finished)
        self._wire_webauthn(page)

    def _wire_webauthn(self, page):
        """Connect the QtWebEngine WebAuthn UX signal so hardware tokens work (#24).

        Without this handler QtWebEngine silently drops WebAuthn challenges,
        so Yubikey/Nitrokey LEDs never light up when DUO/Cisco asks for a
        security key. Requires Qt 6.7+; older versions degrade to the previous
        broken behavior with a logged warning instead of crashing.
        """
        if not _HAS_WEBAUTHN_UX:
            logger.warning(
                "QtWebEngine < 6.7 detected — hardware security keys (FIDO2/WebAuthn) "
                "are not supported in qt mode. Use --browser chrome instead."
            )
            return
        signal_name = (
            "webAuthUxRequested"
            if hasattr(page, "webAuthUxRequested")
            else "webAuthnUxRequested"
            if hasattr(page, "webAuthnUxRequested")
            else None
        )
        if signal_name is None:
            logger.warning(
                "QtWebEngine has QWebEngineWebAuthUxRequest but no UX signal — "
                "hardware security keys may not work."
            )
            return
        getattr(page, signal_name).connect(self._on_webauthn_ux_requested)
        logger.debug("WebAuthn UX handler connected", signal=signal_name)

    @pyqtSlot(object)
    def _on_webauthn_ux_requested(self, request):
        """Driver for the WebAuthn UX state machine (#24)."""
        self._webauthn_request = request
        with contextlib.suppress(AttributeError, TypeError):
            request.stateChanged.connect(lambda s, r=request: self._handle_webauthn_state(r))
        self._handle_webauthn_state(request)

    def _handle_webauthn_state(self, request):
        if QWebEngineWebAuthUxRequest is None:
            return
        states = QWebEngineWebAuthUxRequest.WebAuthUxState
        try:
            state = request.state()
        except (AttributeError, TypeError):
            return

        if state == states.SelectAccount:
            names = list(getattr(request, "userNames", lambda: [])() or [])
            if not names:
                request.cancel()
                return
            choice, ok = QInputDialog.getItem(
                self, "Select security key account", "Account:", names, 0, False
            )
            if ok and choice:
                request.setSelectedAccount(choice)
            else:
                request.cancel()

        elif state == states.CollectPin:
            pin, ok = QInputDialog.getText(
                self,
                "Security key PIN",
                "Enter your security key PIN:",
                QLineEdit.EchoMode.Password,
            )
            if ok and pin:
                request.setPin(pin)
            else:
                request.cancel()

        elif state == states.FinishTokenCollection:
            QMessageBox.information(
                self,
                "Touch your security key",
                "Touch your security key (Yubikey, Nitrokey, …) to continue.",
            )

        elif state == states.RequestFailed:
            QMessageBox.critical(
                self,
                "Security key error",
                "WebAuthn request failed. Try --browser chrome if this persists.",
            )
            request.cancel()

    def createWindow(self, type):
        if type == QWebEnginePage.WebDialog:
            self._popupWindow = WebPopupWindow(self.page().profile())
            return self._popupWindow.view()

    def authenticate_at(self, url, credentials):
        script_source = resources.read_text(__package__, "user.js", encoding="utf-8")
        script = QWebEngineScript()
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        script.setSourceCode(script_source)
        self.page().scripts().insert(script)

        if credentials:
            logger.info("Initiating autologin", user=getattr(credentials, "username", "<unknown>"))
            for url_pattern, rules in self._auto_fill_rules.items():
                script = QWebEngineScript()
                script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
                script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
                script.setSourceCode(
                    f"""
// ==UserScript==
// @include {url_pattern}
// ==/UserScript==

function autoFill() {{
    {get_selectors(rules, credentials)}
    setTimeout(autoFill, 1000);
}}
autoFill();
"""
                )
                self.page().scripts().insert(script)

        self.load(QUrl(url))

    def _on_cookie_added(self, cookie):
        logger.debug("Cookie set", name=to_str(cookie.name()))
        self._on_update(SetCookie(to_str(cookie.name()), to_str(cookie.value())))

    def _on_load_finished(self, success):
        url = self.page().url().toString()
        logger.debug("Page loaded", url=url)

        self._on_update(Url(url))


class WebPopupWindow(QWidget):
    def __init__(self, profile):
        super().__init__()
        self._view = QWebEngineView(self)

        super().setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        super().setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

        layout = QVBoxLayout()
        super().setLayout(layout)
        layout.addWidget(self._view)

        self._view.setPage(QWebEnginePage(profile, self._view))

        self._view.titleChanged.connect(super().setWindowTitle)
        self._view.page().geometryChangeRequested.connect(self.handleGeometryChangeRequested)
        self._view.page().windowCloseRequested.connect(super().close)

    def view(self):
        return self._view

    @pyqtSlot("const QRect")
    def handleGeometryChangeRequested(self, newGeometry):
        self._view.setMinimumSize(newGeometry.width(), newGeometry.height())
        super().move(newGeometry.topLeft() - self._view.pos())
        super().resize(0, 0)
        super().show()


def to_str(qval):
    return bytes(qval).decode()


def get_selectors(rules, credentials):
    statements = []
    for rule in rules:
        selector = json.dumps(rule.selector)
        if rule.action == "stop":
            statements.append(
                f"""var elem = document.querySelector({selector}); if (elem) {{ return; }}"""
            )
        elif rule.fill:
            value = json.dumps(getattr(credentials, rule.fill, None))
            if value:
                statements.append(
                    f"""var elem = document.querySelector({selector}); if (elem) {{ elem.dispatchEvent(new Event("focus")); elem.value = {value}; elem.dispatchEvent(new Event("change", {{bubbles: true}})); elem.dispatchEvent(new Event("input", {{bubbles: true}})); elem.dispatchEvent(new Event("blur")); }}"""
                )
            else:
                logger.warning(
                    "Credential info not available",
                    type=rule.fill,
                    possibilities=dir(credentials),
                )
        elif rule.action == "click":
            statements.append(
                f"""var elem = document.querySelector({selector}); if (elem) {{ elem.dispatchEvent(new Event("focus")); elem.click(); }}"""
            )
    return "\n".join(statements)
