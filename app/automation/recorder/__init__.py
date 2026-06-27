"""Record a Telemost meeting: a Chromium bot joins, ffmpeg captures A/V.

Public surface:
  readiness(cfg)                          -> what's installed / still missing
  record_meeting(url, out_path, cfg, ...) -> {ok, path, reason} | {ok: False, error}

The bot join (browser.py) and the capture (capture.py) are kept separate so the
capture backend can be swapped (Windows dshow now, Linux PulseAudio later) and so
each can be tuned independently. Live recording requires Playwright + Chromium +
ffmpeg + a loopback audio device on the host — see docs/automation-plan.md.
"""
from __future__ import annotations

from pathlib import Path

from . import browser, capture


def readiness(cfg: dict) -> dict:
    """What the screen recorder needs: a browser (Playwright) + ffmpeg + audio."""
    b = browser.readiness(cfg)
    c = capture.readiness(cfg)
    return {"ready": bool(b.get("ready") and c.get("ready")), "mode": "screen",
            "browser": b, "capture": c,
            "auth_mode": cfg.get("auth_mode") or "guest"}


def record_meeting(url: str, out_path: str, cfg: dict,
                   on_log=None, should_stop=None) -> dict:
    """Join `url` and screen-record the meeting (ffmpeg) until it ends.

    The bot joins (as a guest — no login needed) and ffmpeg captures the whole
    screen + the configured audio device for the full meeting (no 30-min limit).
    """
    log = on_log or (lambda *_: None)
    bot = browser.TelemostBot(cfg, on_log=log)
    rec = None
    try:
        if not bot.join(url, should_stop=should_stop):
            shot = str(Path(out_path).with_suffix(".join-failed.png"))
            bot.screenshot(shot)
            return {"ok": False,
                    "error": "Не удалось войти в встречу (см. скриншот). "
                             "Возможно, изменилась вёрстка Телемоста или встреча "
                             "требует входа в Яндекс.",
                    "screenshot": shot}

        max_sec = int(cfg.get("max_meeting_min", 240)) * 60
        alone_sec = int(cfg.get("end_when_alone_sec", 90))
        min_p = int(cfg.get("min_participants", 1))

        # Capture only the meeting's browser window (not the whole desktop).
        title = bot.window_title()
        rec = capture.FFmpegRecorder(out_path, cfg, on_log=log, window_title=title)
        log(f"В звонке — пишу окно «{title or 'весь экран (заголовок не найден)'}» (ffmpeg).")
        rec.start()
        reason = bot.wait_until_end(should_stop, max_sec, alone_sec, min_p)
        log(f"Останавливаю запись (причина: {reason}).")
        rec.stop()
        p = Path(out_path)
        if not p.exists() or p.stat().st_size == 0:
            return {"ok": False, "reason": reason,
                    "error": "Файл записи пуст — проверьте аудио-устройство и ffmpeg."}
        return {"ok": True, "path": out_path, "reason": reason, "size": p.stat().st_size}
    except Exception as e:  # noqa: BLE001
        try:
            if rec:
                rec.stop()
        except Exception:
            pass
        return {"ok": False, "error": f"Ошибка записи: {e}"}
    finally:
        bot.close()
