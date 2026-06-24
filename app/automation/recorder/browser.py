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
_JOIN_BUTTONS = [
    'button:has-text("Подключиться")', 'button:has-text("Войти")',
    'button:has-text("Присоединиться")', 'button:has-text("Join")',
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
_IN_CALL = [
    'button[aria-label*="авершить"]', 'button[aria-label*="leave" i]',
    'button:has-text("Завершить")', '[data-testid*="hangup"]',
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
        headless = self.cfg.get("headless", True) if headless is None else headless
        mode = self.cfg.get("auth_mode") or "guest"
        # Persistent context so a logged-in profile (and media perms) survive.
        user_dir = str(_profile_dir(self.cfg) if mode == "profile"
                       else _profile_dir(self.cfg).parent / "browser-guest")
        Path(user_dir).mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_dir, headless=headless, args=_LAUNCH_ARGS,
            permissions=["microphone", "camera"],
            viewport={"width": 1280, "height": 720})
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def _click_first(self, selectors, timeout=2500) -> bool:
        for sel in selectors:
            try:
                el = self._page.wait_for_selector(sel, timeout=timeout,
                                                  state="visible")
                if el:
                    el.click()
                    return True
            except Exception:
                continue
        return False

    # -- joining ------------------------------------------------------------
    def join(self, url: str) -> bool:
        """Open the meeting and get into the call. Returns True on success."""
        self._launch()
        self._on_log(f"Открываю встречу: {url}")
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._page.wait_for_timeout(4000)

        # Set a display name if the guest form asks for one.
        name = self.cfg.get("bot_join_name") or "Протокол-бот"
        for sel in _NAME_INPUTS:
            try:
                el = self._page.wait_for_selector(sel, timeout=1500, state="visible")
                if el:
                    el.fill(name)
                    break
            except Exception:
                continue

        # Mute mic & camera before joining (best effort).
        self._click_first(_MUTE_MIC, timeout=1500)
        self._click_first(_MUTE_CAM, timeout=1500)

        joined = self._click_first(_JOIN_BUTTONS,
                                   timeout=self.cfg.get("join_timeout_sec", 60) * 1000)
        self._page.wait_for_timeout(5000)
        in_call = self.is_in_call()
        self._on_log(f"Клик по «подключиться»: {joined}; в звонке: {in_call}")
        return in_call or joined

    def is_in_call(self) -> bool:
        for sel in _IN_CALL:
            try:
                if self._page.query_selector(sel):
                    return True
            except Exception:
                continue
        return False

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
        while True:
            if should_stop and should_stop():
                return "stopped"
            if time.time() - start > max_sec:
                return "max_duration"
            if not self.is_in_call():
                return "left_call"
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
