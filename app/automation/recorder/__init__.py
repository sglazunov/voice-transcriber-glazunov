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
    """Aggregate readiness. In Telemost mode only the browser matters (Telemost
    records itself); ffmpeg/loopback audio are only needed for screen mode."""
    mode = cfg.get("record_mode") or "telemost"
    b = browser.readiness(cfg)
    if mode == "telemost":
        host = (cfg.get("auth_mode") == "profile")
        cap = {"ready": True,
               "detail": ("Записывает сам Телемост (видно участникам). "
                          + ("Вход выполнен — ок." if host else
                             "ВАЖНО: запись доступна обычно только организатору — "
                             "войдите в Яндекс (режим «профиль») аккаунтом встречи."))}
        return {"ready": bool(b.get("ready")), "mode": mode,
                "browser": b, "capture": cap,
                "auth_mode": cfg.get("auth_mode") or "guest"}
    c = capture.readiness(cfg)
    return {"ready": bool(b.get("ready") and c.get("ready")), "mode": mode,
            "browser": b, "capture": c,
            "auth_mode": cfg.get("auth_mode") or "guest"}


def record_meeting(url: str, out_path: str, cfg: dict,
                   on_log=None, should_stop=None) -> dict:
    """Join `url`, record until the meeting ends, return the saved file.

    Two modes (cfg["record_mode"]):
      "telemost" — press Telemost's own «Запись на компьютер» (visible to all,
                   Telemost saves the file, no ffmpeg/loopback needed);
      "screen"   — ffmpeg desktop + loopback-audio capture (fallback).
    """
    log = on_log or (lambda *_: None)
    mode = cfg.get("record_mode") or "telemost"
    bot = browser.TelemostBot(cfg, on_log=log)
    try:
        if not bot.join(url, should_stop=should_stop):
            shot = str(Path(out_path).with_suffix(".join-failed.png"))
            bot.screenshot(shot)
            return {"ok": False,
                    "error": "Не удалось войти в встречу (см. скриншот). "
                             "Возможно, нужен вход в Яндекс (режим «профиль») "
                             "или изменилась вёрстка Телемоста.",
                    "screenshot": shot}

        max_sec = int(cfg.get("max_meeting_min", 240)) * 60
        alone_sec = int(cfg.get("end_when_alone_sec", 90))
        min_p = int(cfg.get("min_participants", 1))

        if mode == "telemost":
            log("В звонке — включаю запись Телемоста…")
            if not bot.start_recording(out_path):
                shot = str(Path(out_path).with_suffix(".rec-failed.png"))
                bot.screenshot(shot)
                return {"ok": False,
                        "error": "Не удалось включить запись (меню «•••» → «Записать "
                                 "на компьютер»). Если бот вошёл как гость — поставьте "
                                 "режим «Авторизованный» и войдите в Яндекс. См. "
                                 "скриншот — пришлите его, если кнопка на нём есть.",
                        "screenshot": shot}
            reason = bot.wait_until_end(should_stop, max_sec, alone_sec, min_p)
            log(f"Останавливаю запись Телемоста (причина: {reason}).")
            bot.stop_recording()
            path = bot.wait_for_download(timeout=300)
            if not path or not Path(path).exists() or Path(path).stat().st_size == 0:
                return {"ok": False, "reason": reason,
                        "error": "Запись остановлена, но файл от Телемоста не получен. "
                                 "Если в Телемосте выбрана запись на Яндекс Диск, а не "
                                 "на компьютер — файл там; иначе проверьте права на запись."}
            return {"ok": True, "path": path, "reason": reason,
                    "size": Path(path).stat().st_size}

        # ---- screen / ffmpeg fallback ----
        rec = capture.FFmpegRecorder(out_path, cfg, on_log=log)
        log("В звонке — начинаю захват экрана (ffmpeg).")
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
            bot.stop_recording()
        except Exception:
            pass
        return {"ok": False, "error": f"Ошибка записи: {e}"}
    finally:
        bot.close()
