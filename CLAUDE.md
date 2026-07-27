# Конспект проекта (для Claude) — voice-transcriber

Рабочая память по проекту. Читается автоматически в начале каждой сессии, чтобы
не изучать репозиторий заново. **Держать в актуальном состоянии:** после
заметных изменений дописывать сюда факты и решения (кратко, без воды).

## Что это
Локальный сервис: **распознавание речи → протокол встречи (Word)** + подсистема
**автоматической записи встреч в Телемосте** по задачам из Weeek.
Репозиторий: `sglazunov/voice-transcriber-glazunov` (приватный).
Владелец — Сергей (`sglazunov`), общается по-русски. Команда — CRM-разработка.

Документация в `docs/`: `РУКОВОДСТВО.md` (пользователь), `АРХИТЕКТУРА.md`
(стек/схемы), `ШПАРГАЛКА.md` + `.pdf` (1 стр. для коллег), `automation-plan.md`.

## Окружение и запуск (важно!)
- **Python 3.12** обязателен (3.14 ломает ctranslate2/onnxruntime). Venv:
  `.venv/Scripts/python.exe` (Windows). Пины: `ctranslate2==4.4.0` (4.8 падает),
  `setuptools<80`. Нужен VC++ Redistributable.
- Bash-инструмент: **cwd сбрасывается** — начинать с
  `cd /c/Users/user/voice-transcriber`.
- **Порт 8000 часто занят собственным сервером пользователя — не убивать его.**
  Для проверок поднимать превью на другом порту либо тестировать через TestClient.
- Запуск для пользователя: `install.bat` → `run.bat` → http://localhost:8000.

### Проверка изменений без запуска сервера
```bash
cd /c/Users/user/voice-transcriber && D=$(mktemp -d) && \
PYTHONUTF8=1 VTX_OLLAMA=0 VTX_DATA_DIR="$D" .venv/Scripts/python.exe -c "
from fastapi.testclient import TestClient
import app.main as m
with TestClient(m.app) as c:      # context manager обязателен: иначе не сработает startup
    print(c.get('/healthz').json())
"
```
`VTX_DATA_DIR` во временную папку — чтобы не портить рабочие данные.

## Git-процесс
- Ветки: **`main`** (веб) и **`desktop`** (сборка .exe: PyInstaller + Inno Setup
  + pywebview). Изменения делаются в `main`, затем
  `git checkout desktop && git merge main --no-edit && git push`.
  **`desktop` часто уходит вперёд** (пользователь коммитит туда) → перед мержем
  `git pull origin desktop`, иначе push отклонится.
- Коммит: `git -c commit.gpgsign=false commit -F /tmp/msg.txt` (heredoc).
  НЕ использовать PowerShell here-string `@'...'@` в bash — попадёт литеральный `@`.
- Трейлер: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Пользователь параллельно работает в других сессиях → **всегда `git pull` перед
  работой** и `git status` перед `git add` (коммитить только свои файлы).

## Карта кода
```
app/main.py            FastAPI: ~45 эндпоинтов, рендер index.html/automation.html,
                       старт планировщика на startup
app/config.py          env-конфиг, PROVIDER_ORDER/PROVIDER_LABELS/PROVIDER_MODELS,
                       рантайм-ключи (в памяти), available_providers/resolve_provider
app/jobs.py            JobStore: очередь (1 воркер), пауза/отмена через _control,
                       персист data/jobs.json, ретеншн 24ч, reanalyze()
app/transcribe.py      faster-whisper, кэш модели на 1 слот
app/analyze.py         промпт протокола, map-reduce, AnalysisCancelled
app/llm.py             провайдеры: ollama/groq/gemini/yandex/gigachat/anthropic
app/docx_export.py     Word-протокол
app/diarize.py         pyannote (опц.)   app/screen_ocr.py  Tesseract+PyAV (опц.)
app/glossary.py formats.py   замены терминов, TXT/SRT/JSON
app/ollama_setup.py    установка Ollama из UI
app/deps_setup.py      установка опц. пакетов В .venv приложения (sys.executable -m pip)
app/whisper_setup.py   предзагрузка Whisper-моделей с прогрессом
app/automation/
  settings.py          НАСТРОЙКИ+ТОКЕНЫ НА ДИСКЕ: data/automation.json (0600),
                       вложенные словари мержатся; redacted() прячет секреты
  weeek.py             клиент Weeek, извлечение Телемост-ссылки и времени
  clouds/              local | yandex_disk | gdrive (только stdlib urllib)
  recorder/browser.py  Playwright: заход в Телемост, mute, in-call детект
  recorder/capture.py  ffmpeg gdigrab(title=)+dshow, test_audio_level, лог stderr
  recorder/__init__.py оркестрация + machine-wide lock (двойной заход запрещён)
  scheduler.py         демон-цикл: опрос Weeek → запись → облако → jobs.store.create
```

## Ключевые факты и решения

### Протокол (analyze.py) — ОБЕЗЛИЧЕННЫЙ
- **Без спикеров**: не указывать «кто что сказал», нет `participants`, метки
  «Спикер N:» игнорируются. Причина: с ними протокол выходил плохим.
- **Задачи общие**, без ответственных: `tasks`/`done_tasks`/`minor_tasks` —
  простые строки («Доработать выгрузку», не «Сергею доработать»). Старые данные
  с `owner` терпимо парсятся (текст берётся, owner отбрасывается).
- **Чёткое разделение тем**: каждая тема — самостоятельный блок; на reduce-шаге
  одинаковые темы из разных чанков **сливаются в одну**.
- Схема: `summary, detailed[{topic,details}], key_thoughts, conclusions,
  decisions, done_tasks, tasks, minor_tasks, _provider`.
- Длинные транскрипты — map-reduce (`_MAX_CHARS=16000`, `_CHUNK_CHARS=10000`,
  overlap 800, до 16 чанков). Пауза/отмена — кооперативные (`cancel_check`).
- В Word и в UI нет разделов «Участники» и колонки «Ответственный».

### Weeek (проверено на живом аккаунте)
- API: `https://api.weeek.net/public/v1`, `Authorization: Bearer <token>` —
  персональный API-токен из настроек воркспейса, **не** cookie `weeek_session`.
- `GET /tm/tasks?projectId=`, `GET /tm/tasks/{id}`, `GET /tm/projects`.
- **Ссылка на Телемост лежит в кастом-поле задачи** (`customFields[].value`,
  type `link`), не в описании. Парсер сканирует все кастом-поля (link — первыми),
  затем описание/заголовок; regex матчит только `telemost.yandex.ru`.
- Время: `dueDateTime` приходит уже как UTC (`...Z`). Наивные `date`
  («DD.MM.YYYY») + `time` — локальные, зона из настройки `timezone`
  (по умолчанию `Europe/Moscow`; нужен пакет `tzdata` — у Windows нет базы TZ).

### Рекордер
- У Телемоста **нет публичного API ботов** → пишем экран через ffmpeg
  (`record_mode: "screen"`). Нативная запись Телемоста была отвергнута
  (лимит 30 мин у Яндекса).
- Захват — окно браузера (`gdigrab title=`) с фолбэком на весь экран; звук —
  loopback-устройство (VB-CABLE / «Стерео микшер»), проверка кнопкой
  «Проверить звук» (`volumedetect`).
- Бот **не должен издавать звук**: fake-mic из тишины + кнопки mute нажимаются
  только если устройство ВКЛючено (чтобы случайно не включить обратно).
- Режимы входа: `guest` и `profile` (сохранённый профиль с входом в Яндекс,
  `login_status()` проверяет реальную сессию).
- Селекторы Телемоста — списки кандидатов с фолбэками, **вёрстка меняется**;
  при неудаче сохраняется скриншот + лог ffmpeg.

### Остановка записи (нет фиксированной длительности)
Первое из: ручная кнопка «Остановить запись» → потолок `max_meeting_min` →
бот выпал из звонка → комната истончилась до `min_participants` дольше
`end_when_alone_sec`. Истончение считается **только после того, как в комнате
реально были люди** (ранний вход не завершает запись).

### Планировщик
- Демон-поток, гейт по `enabled`; одна запись за раз (браузер+ffmpeg эксклюзивны),
  атомарный «захват» встречи, machine-wide lock.
- **Не заходит во встречу, начавшуюся до запуска приложения** (`_boot_time`):
  после рестарта такие помечаются `missed`, а не записываются. Ручной
  «Записать сейчас» (`run_now`) это ограничение обходит.
- Состояние `skipped` — отфильтрованные; при смене решения возвращаются в
  `scheduled` (если начало не раньше `_boot_time`).
- Этапы после записи — независимые флаги: `do_transcribe`, `do_protocol`
  (требует transcribe), `ocr_screen`. Запись и выгрузка в облако — всегда.
- Фильтр «какие встречи писать» (`_passes_filter`): ручное решение по встрече
  (`rec_decisions`) важнее всего → режим `rec_default_on` → стоп-слова
  `rec_exclude`/`rec_include` → дни `rec_days` → окно `rec_time_from/to`.
- Состояния: `scheduled|no_time|skipped|missed|recording|uploading|transcribing|
  done|error`. Из прошедших в списке показывается только последняя.
- Блокировка от двойного захода — два слоя: внутрипроцессный lock + PID-файл
  `data/recorder.lock` (треды одного процесса делят PID, файла мало).

### Токены и секреты
- Токены автоматики (Weeek, Я.Диск, Google) — **на диске**, `data/automation.json`,
  переживают рестарт (сервер работает без человека). Ключи LLM ядра — в памяти/env.
- Я.Диск: OAuth со scope `cloud_api:disk.write`; ClientID/secret ≠ токен;
  публикация ссылки — best-effort (таймаут не валит job, файл уже загружен).

### Грабли провайдеров LLM
YandexGPT: нужен folder id (`b1g…`, не `aje…`), роль `ai.languageModels.user`,
привязанный биллинг, ключ со scope `yc.ai.languageModels.execute`.
GigaChat: нужен Authorization-ключ (base64), не Client ID/Secret; SSL unverified.
Groq: 429 на бесплатном тарифе → ретраи/бэкофф; браузерный User-Agent (Cloudflare).
Gemini: без биллинга квоты может не быть. Есть выбор «тира» модели (PROVIDER_MODELS).

## Стиль и договорённости
- Общение с пользователем — **по-русски**; код и комментарии — по-английски.
- UI: тёмная «стеклянная» тема, две страницы (`/` и `/automation`), главная
  свёрстана «в один экран без скролла» — не ломать layout.
- Опциональные тяжёлые фичи (диаризация, OCR, Ollama, Playwright) —
  выключены по умолчанию, с подсказками о готовности в UI.
- Быть честным про непроверенное: рекордер и облака частично не гонялись
  вживую; так и говорить, а не выдавать за проверенное.
- Пользователь просит обновлять документацию (`docs/`) вместе с фичами.
