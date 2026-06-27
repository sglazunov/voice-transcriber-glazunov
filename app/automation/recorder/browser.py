"""Telemost join via Playwright/Chromium — guest and authenticated modes.

Two ways in (settings `auth_mode`):
  * "guest"   — open the link, type a display name, join without logging in.
  * "profile" — reuse a persistent browser profile that's already logged into a
                Yandex account (run `login()` once to sign in interactively).

Telemost's DOM is not a stable public contract, so selectors are best-effort
lists with fallbacks plus screenshots/logging for tuning on the real site.
Playwright is imported lazily so the rest of the app runs without it.
"""
from __future__ import annotations

import time
from pathlib import Path

from ... import config

# Candidate selectors (first match wins). Tune against the live site if needed.
_NAME_INPUTS = [
    'input[name="name"]', 'input[placeholder*="мя"]',
    'input[placeholder*="name" i]', 'input[type="text"]',
]
# Telemost first shows an interstitial ("Вы подключаетесь… → Продолжить в
# браузере") before the pre-join screen. We must click through it.
_CONTINUE_BROWSER = [
    'button:has-text("Продолжить в браузере")',
    'a:has-text("Продолжить в браузере")',
    'button:has-text("Continue in browser")',
    'a:has-text("Continue in browser")',
    'button:has-text("Продолжить")', 'a:has-text("Продолжить")',
]
_JOIN_BUTTONS = [
    'button:has-text("Подключиться")', 'button:has-text("Войти")',
    'button:has-text("Присоединиться")', 'button:has-text("Join")',
    'button:has-text("Продолжить")',
    '[data-testid*="join"]', 'button[type="submit"]',
]
_MUTE_MIC = [
    'button[aria-label*="икрофон"]', 'button[aria-label*="mic" i]',
    '[data-testid*="microphone"]',
]
_MUTE_CAM = [
    'button[aria-label*="амер"]', 'button[aria-label*="camera" i]',
    '[data-testid*="camera"]',
]
# Buttons whose label means the device is currently ON → clicking turns it OFF.
# (We only click these, so we never accidentally UN-mute an already-muted bot.)
_MIC_IS_ON = [
    'button[aria-label*="ыключить микрофон"]',   # "Выключить микрофон"
    'button[aria-label*="ыключить звук"]', 'button[aria-label*="mute" i]',
]
_CAM_IS_ON = [
    'button[aria-label*="ыключить камер"]', 'button[aria-label*="ыключить видео"]',
    'button[aria-label*="stop video" i]', 'button[aria-label*="turn off camera" i]',
]
# Controls that exist only while in the call (any one present = in call).
_IN_CALL = [
    'button:has-text("Участники")', 'button:has-text("Демонстрация")',
    'button:has-text("Чат")', 'button:has-text("Показать всех")',
    'button[aria-label*="частник"]', 'button[aria-label*="емонстрац"]',
    'button[aria-label*="авершить"]', 'button[aria-label*="окинуть"]',
    'button[aria-label*="ыйти"]', 'button[aria-label*="leave" i]',
    'button[aria-label*="hang" i]', '[data-testid*="hangup"]',
    'button:has-text("Завершить")', 'button:has-text("Покинуть")',
]
# --- Telemost native recording controls -------------------------------------
# Confirmed from the live UI: the bottom "•••" (More) button opens a menu whose
# first item is «Записать на компьютер»; while recording it becomes «Остановить
# запись».
_REC_MORE = [  # the bottom-bar "•••" (More) button that holds the record item
    'button[aria-label="Ещё"]', 'button[aria-label*="Ещё"]',
    'button[aria-label*="ещё"]', 'button[aria-label*="Дополнит"]',
    'button[aria-label*="More" i]', 'button[aria-label*="menu" i]',
    'button[aria-haspopup="menu"]', '[data-testid*="more"]',
    '[data-testid*="menu-button"]', 'button:has-text("•••")', 'button:has-text("…")',
]
_REC_START = [  # the «Записать на компьютер» menu item
    '[role="menuitem"]:has-text("Записать на компьютер")',
    'text="Записать на компьютер"', 'text=Записать на компьютер',
    'button:has-text("Записать на компьютер")',
    'text=Запись на компьютер', 'text=Сохранить на компьютер',
]
_REC_CONFIRM = [  # an optional confirmation dialog
    'button:has-text("Начать запись")', 'button:has-text("Записать")',
    'button:has-text("Начать")', 'button:has-text("Продолжить")',
    'button:has-text("Понятно")',
]
_REC_STOP = [
    '[role="menuitem"]:has-text("Остановить запись")',
    'text="Остановить запись"', 'text=Остановить запись',
    'button:has-text("Остановить запись")', 'text=Завершить запись',
]
# Launch args: auto-accept mic/cam prompts; fake mic so we never send real audio.
_LAUNCH_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-blink-features=AutomationControlled",
]


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def readiness(cfg: dict) -> dict:
    if not playwright_available():
        return {"ready": False,
                "detail": "Не установлен Playwright. Выполните: pip install "
                          "playwright  &&  playwright install chromium"}
    mode = cfg.get("auth_mode") or "guest"
    if mode == "profile":
        prof = _profile_dir(cfg)
        if not any(prof.iterdir()) if prof.exists() else True:
            return {"ready": False, "mode": mode,
                    "detail": "Режим 'profile': профиль пуст — войдите один раз "
                              "через кнопку «Войти в Яндекс»."}
        return {"ready": True, "mode": mode, "detail": f"Профиль: {prof}"}
    return {"ready": True, "mode": mode, "detail": "Режим: гость (по ссылке)."}


def login_status(cfg: dict) -> dict:
    """Check whether the recorder profile is actually logged into Yandex.

    Loads passport.yandex.ru/profile in a headless copy of the profile: if it
    stays on /profile the session is valid; if it redirects to /auth it isn't."""
    if (cfg.get("auth_mode") or "guest") != "profile":
        return {"logged_in": None,
                "detail": "Режим входа — «Гость»: вход в Яндекс не используется. "
                          "Для записи Телемоста переключите на «Авторизованный»."}
    if not playwright_available():
        return {"logged_in": None, "detail": "Playwright не установлен."}
    try:
        from playwright.sync_api import sync_playwright
        user_dir = str(_profile_dir(cfg))
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_dir, headless=True, args=_LAUNCH_ARGS)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://passport.yandex.ru/profile",
                      wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)
            url = page.url
            try:
                ctx.close()
            except Exception:
                pass
        logged = "/auth" not in url
        return {"logged_in": logged,
                "detail": ("Вход в Яндекс выполнен ✓ — бот будет писать как этот аккаунт."
                           if logged else
                           "Не вошли в Яндекс. Нажмите «Войти в Яндекс» и авторизуйтесь "
                           "аккаунтом, создавшим встречу.")}
    except Exception as e:  # noqa: BLE001
        return {"logged_in": None, "detail": f"Не удалось проверить вход: {e}"}


def _profile_dir(cfg: dict) -> Path:
    raw = (cfg.get("browser_profile_dir") or "").strip()
    base = Path(raw) if raw else (config.DATA_DIR / "browser-profile")
    base.mkdir(parents=True, exist_ok=True)
    return base


class TelemostBot:
    """Drive a Chromium instance into a Telemost call and back out."""

    def __init__(self, cfg: dict, on_log=None):
        self.cfg = cfg
        self._on_log = on_log or (lambda *_: None)
        self._pw = None
        self._ctx = None
        self._page = None

    # -- lifecycle ----------------------------------------------------------
    def _launch(self, headless: bool | None = None):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        # Screen capture needs a real on-screen window for ffmpeg to grab, so the
        # recording browser is never headless (the explicit param still wins, e.g.
        # the login helper).
        headless = False if headless is None else headless
        mode = self.cfg.get("auth_mode") or "guest"
        use_profile = (mode == "profile")
        # Persistent context so a logged-in profile (and media perms) survive.
        user_dir = str(_profile_dir(self.cfg) if use_profile
                       else _profile_dir(self.cfg).parent / "browser-guest")
        Path(user_dir).mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_dir, headless=headless, args=_LAUNCH_ARGS,
            permissions=["microphone", "camera"],
            accept_downloads=True,   # Telemost "Запись на компьютер" → a download
            viewport={"width": 1280, "height": 720})
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._download_path = None
        self._ctx.on("download", self._on_download)

    # -- Telemost native recording -----------------------------------------
    def _on_download(self, dl) -> None:
        """Capture the file Telemost produces when recording stops."""
        try:
            suggested = dl.suggested_filename or "recording.webm"
            ext = Path(suggested).suffix or ".webm"
            target = str(Path(self._out_path).with_suffix(ext)) if getattr(
                self, "_out_path", None) else suggested
            dl.save_as(target)
            self._download_path = target
            self._on_log(f"Файл записи получен от Телемоста: {target}")
        except Exception as e:  # noqa: BLE001
            self._on_log(f"Не удалось сохранить запись: {e}")

    def _aborted(self) -> bool:
        sc = getattr(self, "_should_stop", None)
        try:
            return bool(sc and sc())
        except Exception:
            return False

    def _click_any(self, selectors, overall_ms=12000, poll_ms=500) -> bool:
        """Poll ALL selectors repeatedly until one is clickable or we time out.

        Much better than waiting `timeout` on each selector in turn (that could
        block for selectors×timeout — minutes — when the page hasn't loaded the
        expected control yet). Bails early if the user pressed «Остановить»."""
        deadline = time.time() + overall_ms / 1000
        while time.time() < deadline and not self._aborted():
            for sel in selectors:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        return True
                except Exception:
                    pass
            self._page.wait_for_timeout(poll_ms)
        return False

    def _fill_any(self, selectors, value, overall_ms=6000) -> bool:
        deadline = time.time() + overall_ms / 1000
        while time.time() < deadline:
            for sel in selectors:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible():
                        el.fill(value)
                        return True
                except Exception:
                    pass
            self._page.wait_for_timeout(400)
        return False

    # -- joining ------------------------------------------------------------
    def join(self, url: str, should_stop=None) -> bool:
        """Open the meeting and get into the call. Returns True on success."""
        self._should_stop = should_stop
        join_budget = int(self.cfg.get("join_timeout_sec", 60))
        self._launch()
        self._on_log(f"Открываю встречу: {url}")
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._page.wait_for_timeout(3000)

        # 1) Interstitial: "Продолжить в браузере".
        if self._click_any(_CONTINUE_BROWSER, overall_ms=10000):
            self._on_log("Прошёл заглушку «Продолжить в браузере».")
            self._page.wait_for_timeout(4000)
        else:
            self._on_log("Заглушки «Продолжить в браузере» не было (или уже пройдена).")

        # 2) Display name on the guest pre-join form (if asked).
        name = self.cfg.get("bot_join_name") or "Протокол-бот"
        if self._fill_any(_NAME_INPUTS, name, overall_ms=8000):
            self._on_log(f"Указал имя: {name}")

        # 3) Mute mic & camera before joining (best effort).
        self._click_any(_MUTE_MIC, overall_ms=2500)
        self._click_any(_MUTE_CAM, overall_ms=2500)

        # 4) Join the call (poll up to the configured budget).
        joined = self._click_any(_JOIN_BUTTONS, overall_ms=join_budget * 1000)
        self._on_log(f"Клик по кнопке входа: {joined}")
        self._page.wait_for_timeout(6000)
        # Make sure the bot is muted in the call (no sound goes OUT from it).
        self.ensure_muted()
        in_call = self.is_in_call()
        self._on_log(f"В звонке: {in_call}")
        return in_call or joined

    def window_title(self) -> str | None:
        """The browser window's title — used by ffmpeg to grab just this window.

        Brings the window to the foreground first so gdigrab captures it cleanly
        (a fully occluded window can grab black)."""
        try:
            self._page.bring_to_front()
        except Exception:
            pass
        try:
            t = (self._page.title() or "").strip()
            return t or None
        except Exception:
            return None

    def ensure_muted(self) -> None:
        """Turn the bot's mic and camera OFF (only if currently ON, so we never
        un-mute). Prevents the bot from sending any audio/video into the call."""
        for sels, what in ((_MIC_IS_ON, "микрофон"), (_CAM_IS_ON, "камеру")):
            for sel in sels:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        self._on_log(f"Выключил {what} бота.")
                        break
                except Exception:
                    pass

    def is_in_call(self) -> bool:
        for sel in _IN_CALL:
            try:
                if self._page.query_selector(sel):
                    return True
            except Exception:
                continue
        return False

    def _open_more_and_click(self, item_selectors, overall_ms: int = 12000) -> bool:
        """Open the bottom «•••» menu and click one of `item_selectors`.

        Polls so it works whether the menu is already open or needs opening, and
        whether the «•••» button has an aria-label we recognise."""
        deadline = time.time() + overall_ms / 1000
        while time.time() < deadline and not self._aborted():
            # menu already open?
            for sel in item_selectors:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        return True
                except Exception:
                    pass
            # open a "•••" candidate, then look for the item
            for msel in _REC_MORE:
                try:
                    mb = self._page.query_selector(msel)
                    if mb and mb.is_visible():
                        mb.click()
                        self._page.wait_for_timeout(600)
                        for sel in item_selectors:
                            it = self._page.query_selector(sel)
                            if it and it.is_visible():
                                it.click()
                                return True
                        # close the menu (Esc) so the next candidate is clean
                        try:
                            self._page.keyboard.press("Escape")
                        except Exception:
                            pass
                except Exception:
                    pass
            self._page.wait_for_timeout(500)
        return False

    def start_recording(self, out_path: str) -> bool:
        """Open «•••» → «Записать на компьютер». Returns True if it started."""
        self._out_path = out_path
        self._download_path = None
        started = self._open_more_and_click(_REC_START, overall_ms=15000)
        if started:
            self._page.wait_for_timeout(1200)
            self._click_any(_REC_CONFIRM, overall_ms=2500)  # optional dialog
            self._on_log("Запись Телемоста запущена.")
        else:
            self._on_log("Не нашёл пункт «Записать на компьютер».")
        return started

    def stop_recording(self) -> None:
        """Open «•••» → «Остановить запись» so Telemost finalises & saves."""
        try:
            stopped = self._open_more_and_click(_REC_STOP, overall_ms=8000)
            self._click_any(_REC_CONFIRM, overall_ms=2000)  # confirm "завершить"
            self._on_log(f"Остановка записи Телемоста: {stopped}")
        except Exception as e:  # noqa: BLE001
            self._on_log(f"Стоп записи: {e}")

    def wait_for_download(self, timeout: int = 240) -> str | None:
        """Wait until Telemost's recording file has been saved locally."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._download_path:
                return self._download_path
            self._page.wait_for_timeout(1000)
        return self._download_path

    def participant_count(self) -> int | None:
        """Best-effort count of participants (None if it can't be read)."""
        for sel in ['[data-testid*="participants"]', '[class*="participant"]']:
            try:
                els = self._page.query_selector_all(sel)
                if els:
                    return len(els)
            except Exception:
                continue
        return None

    def screenshot(self, path: str) -> None:
        try:
            self._page.screenshot(path=path, full_page=False)
        except Exception as e:
            self._on_log(f"Скриншот не удался: {e}")

    def wait_until_end(self, should_stop, max_sec: int, alone_sec: int,
                       min_participants: int = 1) -> str:
        """Block until the meeting ends. Returns the reason it stopped.

        Stop conditions (first wins): manual stop (`should_stop`), hard time cap
        (`max_sec`), the bot dropped out of the call, or the room thinned to
        `min_participants` or fewer for `alone_sec` — but only AFTER real
        participants were seen, so joining early (empty room) doesn't end it.
        """
        start = time.time()
        thin_since = None
        seen_others = False           # has anyone besides the bot ever appeared?
        gone_since = None             # since when is_in_call has been False
        # Give the call a moment to render its controls before we judge it.
        self._page.wait_for_timeout(6000)
        while True:
            if should_stop and should_stop():
                return "stopped"
            if time.time() - start > max_sec:
                return "max_duration"
            if not self.is_in_call():
                # Don't bail on a transient miss (UI re-render); only conclude the
                # call ended after the controls have been absent for a while.
                gone_since = gone_since or time.time()
                if time.time() - gone_since > 25:
                    return "left_call"
                time.sleep(3)
                continue
            gone_since = None
            n = self.participant_count()
            if n is not None:
                if n >= 2:
                    seen_others = True
                if seen_others and n <= max(1, min_participants):
                    thin_since = thin_since or time.time()
                    if time.time() - thin_since > alone_sec:
                        return "thinned_out"
                else:
                    thin_since = None
            time.sleep(5)

    def close(self) -> None:
        for closer in (lambda: self._ctx and self._ctx.close(),
                       lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception:
                pass
        self._ctx = self._page = self._pw = None


def login(cfg: dict, on_log=None) -> None:
    """Open a HEADED browser on the profile so the user can log into Yandex once.
    Blocks until the window is closed; the session is saved in the profile dir."""
    from playwright.sync_api import sync_playwright
    log = on_log or (lambda *_: None)
    user_dir = str(_profile_dir(cfg))
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_dir, headless=False, args=_LAUNCH_ARGS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://passport.yandex.ru/auth", wait_until="domcontentloaded")
        log("Войдите в Яндекс в открывшемся окне, затем закройте его.")
        # Wait until the user closes the context.
        try:
            while ctx.pages:
                page.wait_for_timeout(1000)
        except Exception:
            pass
