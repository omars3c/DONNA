# ЗАДАЧА: добавить в DONNA отдельный сервис отслеживания ошибок — DONNA SENTINEL

## Контекст проекта (не выдумывай, это проверенные факты)

DONNA — голосовой ассистент на Python, микросервисная архитектура, 6 сервисов:

| Сервис | Модуль | Порт |
|---|---|---|
| channel_gateway_service | `services.channel_gateway_service.app` | 8000 |
| brain_orchestrator | `services.brain_orchestrator.app` | 8001 |
| cortex_memory_service | `services.cortex_memory_service.app` | 8002 |
| research_agent_service | `services.research_agent_service.app` | 8003 |
| windows_host_agent | `services.windows_host_agent.app` | 8004 |
| audio_stream_service | `services.audio_stream_service.app` | 8005 |

Существующие конвенции, которым обязательно следовать:

- `shared/config.py` — все порты/хосты через `os.getenv("DONNA_<X>_HOST"/"DONNA_<X>_PORT", default)`, плюс собранные `<X>_SERVICE_URL = f"http://{HOST}:{PORT}"`.
- Каждый сервис: папка `services/<name>/` с `__init__.py` и `app.py`, внутри FastAPI-приложение с `CORSMiddleware(allow_origins=["*"])`.
- Эндпоинт здоровья у всех одинаковый: `GET /health` → `{"status": "healthy", "service": "<name>", "port": <port>}`.
- В начале `app.py` добавляется корень проекта в `sys.path` через `BASE_DIR = Path(__file__).resolve().parent.parent.parent`.
- На Windows в начале делается `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.
- Запуск: `run.ps1` (switch по targets: cortex/brain/research/channel/hostagent/audio/smoke/all/health/stop) и `run_microservices.py` (список `SERVICES` со словарями `{name, module, port, color}`, вывод дочерних процессов пробрасывается через `_stream_output`).
- Общие pydantic-модели лежат в `shared/models/`.
- `.gitignore` уже исключает `config/api_keys.json`, `config/certs/`, `memory/cortex.db`.

Референс из монолита (коммит `f516f98a`, ветка `feature/error-tracker`): там был класс `ErrorTrackerPanel` в `ui.py` — плавающая панель PyQt с severity `CRITICAL / ERROR / WARNING`, полями `source`, `message`, `traceback`, лимитом 200 записей, и потокобезопасным методом `JarvisUI.log_error()`. **Ту реализацию не переноси** — она однопроцессная. Нужна микросервисная версия, описанная ниже. Но сохрани её модель данных (severity/source/message/traceback) и красно-киберпанковую стилистику.

---

## Что нужно построить

Новый **седьмой** сервис `sentinel_service` на порту **8006** — центральный сборщик ошибок со всех сервисов, с хранением в SQLite и веб-дашбордом в браузере.

Главная цель: **когда Донна сбоит, я открываю `http://localhost:8006` и понимаю, какой сервис сломался первым и почему**, даже если процесс уже умер и перезапустился.

### Ключевое отличие от монолита

В микросервисах сбой почти всегда каскадный: упал `cortex` → `brain` словил таймаут → `audio` отвалился. Поэтому Sentinel обязан отвечать не на вопрос «какие были ошибки», а на вопрос **«что сломалось первым»**. Отсюда три требования, которые нельзя выкидывать:

1. **correlation_id** — сквозной идентификатор одной голосовой команды, проходящий через все сервисы.
2. **автодетект падения сервиса** — Sentinel сам пингует `/health` всех шести и фиксирует переход UP→DOWN.
3. **группировка в инциденты** — ошибки разных сервисов в пределах окна времени объединяются в один инцидент с указанием первопричины.

---

## Файлы, которые нужно создать

### 1. `shared/models/sentinel.py`

Pydantic-модели:

- `ErrorSeverity` — строковый enum: `CRITICAL`, `ERROR`, `WARNING`, `INFO`.
- `ErrorReport` — то, что сервис шлёт в Sentinel:
  - `service: str` (например `brain_orchestrator`)
  - `severity: ErrorSeverity`
  - `source: str` — где именно (например `gemini_session`, `mic_capture`, `tool_dispatch`)
  - `message: str`
  - `traceback: str | None`
  - `correlation_id: str | None`
  - `context: dict[str, Any] | None` — произвольные поля (имя инструмента, код ответа, URL и т.п.)
  - `ts: float` — unix-время возникновения на стороне сервиса (не на стороне Sentinel)
- `ErrorRecord` — то же плюс `id: int`, `fingerprint: str`, `received_ts: float`.
- `ServiceStatusEvent` — `service`, `status` (`UP` / `DOWN`), `ts`, `detail`.
- `IncidentSummary` — `incident_id`, `started_ts`, `ended_ts`, `services: list[str]`, `root_cause: ErrorRecord | None`, `error_count`, `severity`.

### 2. `services/sentinel_service/store.py`

Слой хранения на **SQLite** (стандартный модуль `sqlite3`, без ORM), файл БД `memory/sentinel.db`.

- Включи `PRAGMA journal_mode=WAL` — Sentinel пишет из нескольких потоков.
- Таблица `errors`: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `ts REAL`, `received_ts REAL`, `service TEXT`, `severity TEXT`, `source TEXT`, `message TEXT`, `traceback TEXT`, `correlation_id TEXT`, `context TEXT` (JSON-строка), `fingerprint TEXT`, `incident_id TEXT`. Индексы по `ts`, `service`, `correlation_id`, `fingerprint`, `incident_id`.
- Таблица `service_status`: `id`, `ts REAL`, `service TEXT`, `status TEXT`, `detail TEXT`.
- **fingerprint** — sha1 от `service + severity + source + нормализованный message`. Нормализация: выбрось из сообщения числа, hex-адреса, UUID, пути и таймстемпы, чтобы «Connection refused to port 8002» и «Connection refused to port 8003» не считались одной ошибкой, а «request 4471 failed» и «request 9982 failed» — считались. Fingerprint нужен, чтобы 500 одинаковых ошибок схлопывались в одну строку со счётчиком.
- **incident_id** — присваивается при записи: если предыдущая ошибка (любого сервиса) была меньше чем `INCIDENT_WINDOW_SEC` (по умолчанию 30) назад, наследуй её `incident_id`, иначе заведи новый (`uuid4`). Так каскад попадает в один инцидент.
- Ротация: удаляй записи старше `SENTINEL_RETENTION_DAYS` (по умолчанию 7) и держи жёсткий потолок в 50 000 строк, удаляя самые старые. Чистку запускай раз в час фоново, а не на каждой вставке.
- Методы: `insert_error`, `insert_status`, `query_errors(filters)`, `get_trace(correlation_id)`, `get_incidents(limit)`, `get_incident(incident_id)`, `get_stats(window_sec)`, `clear_all()`.

### 3. `shared/error_reporter.py` — клиентская библиотека

Её импортируют все сервисы. **Критическое требование: она не имеет права уронить или затормозить сервис.** Ни одна функция не должна бросать исключение наружу и не должна блокировать вызывающий поток.

Реализация:

- Внутренняя `queue.Queue(maxsize=1000)` + один фоновый daemon-поток, который батчами (до 50 штук или раз в 0.5 с) шлёт `POST` на `http://127.0.0.1:8006/v1/errors/batch` с коротким таймаутом (2 с).
- Если очередь переполнена — молча дропай самые старые, не блокируй.
- Если Sentinel недоступен — пиши в fallback-файл `logs/sentinel_fallback.jsonl` (по строке JSON), и при следующем успешном коннекте досылай накопленное. Папку `logs/` создавай при старте.
- Весь фоновый поток обёрнут в `try/except Exception: pass` на верхнем уровне — падение репортера не должно быть заметно.

Публичный API:

```python
init_reporter(service_name: str) -> None
report(severity, source, message, exc=None, correlation_id=None, **context) -> None
report_exception(source, exc, correlation_id=None, **context) -> None   # сам берёт traceback.format_exc()
set_correlation_id(cid: str) -> None       # пишет в contextvars.ContextVar
get_correlation_id() -> str | None
new_correlation_id() -> str
install_sentinel(app: FastAPI, service_name: str) -> None
```

`install_sentinel(app, service_name)` — это те самые «2 строки в сервис». Он должен навесить:

1. **HTTP middleware**: читает заголовок `X-Donna-Correlation-ID` (если нет — генерирует), кладёт в ContextVar, возвращает его же в заголовке ответа. Оборачивает вызов в `try/except`: при необработанном исключении репортит `CRITICAL` с полным traceback и **пробрасывает исключение дальше** (не глотает). Также репортит `ERROR`, если ответ вернулся с кодом 5xx.
2. `sys.excepthook` и `threading.excepthook` — необработанные исключения в потоках.
3. `loop.set_exception_handler(...)` на asyncio-цикле — необработанные исключения в тасках (это важно для `brain_orchestrator`, где Gemini-сессия живёт в `asyncio.create_task`).
4. `logging.Handler`, подписанный на root-логгер с уровнем `WARNING`, который зеркалит записи в Sentinel. **Обязательно защити от рекурсии**: если запись пришла от самого репортера или от `httpx`/`urllib3` при отправке в Sentinel — игнорируй, иначе получишь бесконечный цикл.
5. Обработчики `startup` / `shutdown`, репортящие `INFO` события жизненного цикла сервиса.

Ещё нужен хелпер для исходящих HTTP-вызовов между сервисами:

```python
donna_headers() -> dict   # возвращает {"X-Donna-Correlation-ID": <текущий cid>}
```

чтобы correlation_id проходил сквозь цепочку `brain → cortex → research`.

### 4. `services/sentinel_service/__init__.py` и `services/sentinel_service/app.py`

FastAPI-сервис на 8006 по общей конвенции проекта. **Сам себя он не инструментирует** — не вызывает `install_sentinel` на собственном приложении, иначе получится петля.

Эндпоинты:

- `GET /health` — в общем формате проекта.
- `POST /v1/errors` — приём одной ошибки (`ErrorReport`).
- `POST /v1/errors/batch` — приём списка (основной путь для репортера).
- `GET /v1/errors` — выборка с query-фильтрами: `service`, `severity`, `since` (unix ts), `correlation_id`, `incident_id`, `search` (подстрока в message), `limit` (по умолчанию 200), `group` (если `true` — схлопнуть по fingerprint со счётчиком).
- `GET /v1/incidents` — список инцидентов, новые сверху.
- `GET /v1/incidents/{incident_id}` — все события инцидента по времени + вычисленная первопричина.
- `GET /v1/trace/{correlation_id}` — полная хронология одной команды по всем сервисам.
- `GET /v1/stats` — счётчики за последний час/сутки, разбивка по сервисам и severity, текущий UP/DOWN статус шести сервисов.
- `DELETE /v1/errors` — очистка (аналог кнопки CLEAR из монолитной панели).
- `WS /ws/errors` — вебсокет, пушит новые ошибки в дашборд в реальном времени.
- `GET /` — отдаёт HTML-дашборд.

**Фоновый health-поллер** (запускать в `lifespan`): раз в 10 секунд `GET /health` каждого из шести сервисов с таймаутом 2 с. При смене состояния пиши `ServiceStatusEvent` и синтетическую запись в `errors` с severity `CRITICAL` и source `health_monitor` — то есть падение сервиса выглядит в ленте как ошибка. Не спамь: пиши только переходы UP→DOWN и DOWN→UP, а не каждый опрос.

**Определение первопричины инцидента**: внутри инцидента бери самое раннее событие с severity `CRITICAL` или `ERROR`; при равенстве времени приоритет у события `health_monitor` (падение процесса важнее, чем таймаут у того, кто в него стучался).

### 5. `services/sentinel_service/dashboard.html`

Одностраничный дашборд, полностью самодостаточный: инлайновые CSS и JS, **без внешних CDN и без npm** (сервис должен работать офлайн). Без сборки — просто отдаётся как статика.

Визуальный стиль — продолжение тактического киберпанка DONNA, как в монолитной панели: почти чёрный фон (`#04060 8` / `#060809`), красный акцент `#cc4444` для ERROR, `#ff2244` для CRITICAL, янтарный `#d4a820` для WARNING, приглушённый серый для текста, моноширинный шрифт для логов. Скруглений минимум, тонкие рамки 1px.

Структура экрана:

- Сверху — **строка состояния шести сервисов**: шесть плиток с именем, портом и индикатором UP/DOWN. Это первое, что должно бросаться в глаза при сбое.
- Под ней — **лента инцидентов** (не плоский список ошибок!). Каждый инцидент: время, затронутые сервисы, счётчик событий, и явно подсвеченная первопричина. По клику раскрывается хронология всех событий инцидента с раскрывающимися traceback.
- Фильтры: по сервису, по severity, поиск по тексту, переключатель «группировать одинаковые».
- Живое подключение по вебсокету с автопереподключением; при обрыве показывать это в интерфейсе, а не молчать.
- Кнопка очистки с подтверждением.
- Пустое состояние — не «нет данных», а понятная фраза вроде «Ошибок нет. Sentinel слушает шесть сервисов».

Тексты интерфейса — на русском.

---

## Правки существующих файлов

### `shared/config.py`
Добавь по образцу остальных:
```python
SENTINEL_HOST = os.getenv("DONNA_SENTINEL_HOST", "127.0.0.1")
SENTINEL_PORT = int(os.getenv("DONNA_SENTINEL_PORT", "8006"))
SENTINEL_SERVICE_URL = f"http://{SENTINEL_HOST}:{SENTINEL_PORT}"
SENTINEL_ENABLED = os.getenv("DONNA_SENTINEL_ENABLED", "1") == "1"
```
`SENTINEL_ENABLED=0` должен полностью отключать отправку в репортере — чтобы сервисы можно было запускать без Sentinel.

### Все шесть `services/*/app.py`
Добавь ровно две строки после создания `app`:
```python
from shared.error_reporter import install_sentinel
install_sentinel(app, "brain_orchestrator")   # имя своё для каждого сервиса
```
`audio_stream_service` — проверь, есть ли там FastAPI-приложение; если это не FastAPI, ограничься `init_reporter("audio_stream_service")` и хуками исключений.

Ничего больше в логике сервисов не меняй.

### Ручные вызовы в ключевых местах
Кроме автоматики, добавь явные `report_exception(...)` в местах, где ошибки сейчас просто печатаются через `print` и теряются:

- `services/brain_orchestrator/app.py` — обработка Gemini Live сессии (обрывы вебсокета, коды закрытия, ошибки отправки аудио-чанков); source `gemini_session`. Указывай в `context` код закрытия сессии и модель.
- `services/brain_orchestrator/app.py` — диспетчеризация инструментов к другим сервисам; source `tool_dispatch`, в `context` — имя инструмента и целевой сервис.
- `services/audio_stream_service/app.py` — захват микрофона и воспроизведение; source `mic_capture` / `audio_playback`.
- `services/channel_gateway_service/app.py` — в `_forward_command_to_brain` и в RSS-мониторе уже есть `except Exception as e` с `print`; добавь туда репорт, `print` оставь.
- `services/windows_host_agent/app.py` — захват экрана через `mss`; source `screenshot`. Session 0 isolation здесь — реальная известная проблема, её нужно видеть в ленте явно.
- `services/research_agent_service/app.py` — Playwright и генерация `.docx`; source `research_pipeline`.

### `run.ps1`
- Добавь target `sentinel` → `python -m uvicorn services.sentinel_service.app:app --port 8006`.
- Добавь `sentinel` в target `all` (запускать **первым**, до остальных, чтобы поймать ошибки их старта).
- Добавь порт 8006 в хэштаблицу `$ports` в target `health`.
- Обнови комментарий-справку в шапке файла.

### `run_microservices.py`
- Добавь SENTINEL в список `SERVICES` первым элементом, порт 8006, модуль `services.sentinel_service.app`, свой цвет.
- В `_stream_output` добавь **скрейпер логов** как страховочную сеть: если строка вывода дочернего процесса содержит `Traceback`, `ERROR`, `CRITICAL`, `Exception` или `Failed` — отправляй её в Sentinel как ошибку с source `stdout_scrape`. Это ловит всё, что печатается через `print` и не проходит через репортер, включая падения на старте до инициализации. Сам скрейпер обязательно защити `try/except`, и не скрейпь вывод самого SENTINEL.

### `.gitignore`
Добавь:
```
memory/sentinel.db
memory/sentinel.db-wal
memory/sentinel.db-shm
logs/
```

### `scripts/smoke_test.py`
Добавь импорт-проверку `services.sentinel_service.app` и `shared.error_reporter` по образцу существующих проверок.

---

## Требования к качеству

1. **Sentinel не должен влиять на работу Донны.** Если сервис 8006 не запущен, выключен через `DONNA_SENTINEL_ENABLED=0` или отвечает ошибкой — все шесть сервисов работают ровно как раньше. Это надо явно проверить.
2. **Никакой блокировки**: отправка только из фонового потока, вызывающий код не ждёт сеть.
3. **Никакой рекурсии**: логи самого репортера и HTTP-клиента не попадают обратно в репортер.
4. **Секреты не утекают в БД**: перед записью маскируй в `message`, `traceback` и `context` всё, что похоже на ключ или токен — значения по ключам `api_key`, `gemini_api_key`, `token`, `authorization`, `password`, а также длинные строки, похожие на ключи. В проекте есть живой `gemini_api_key` в `config/api_keys.json`, и он не должен оказаться в `sentinel.db` или на дашборде.
5. **Кодировка**: русские сообщения об ошибках должны корректно сохраняться и отображаться. В SQLite пиши UTF-8, в FastAPI отдавай `application/json; charset=utf-8`, на HTML-странице укажи `<meta charset="utf-8">`. Учти известную проблему проекта: кракозябры в PowerShell-консоли — это кодировка терминала, а не данных; в БД и на веб-странице должно быть чисто.
6. **Новых тяжёлых зависимостей не добавлять.** Хватает того, что уже в `requirements.txt` (`fastapi`, `uvicorn[standard]`, `requests`) плюс стандартной библиотеки. `sqlite3`, `queue`, `threading`, `contextvars`, `hashlib` — из stdlib.

---

## Как проверить, что готово

Опиши в ответе результат каждого шага:

1. `.\run.ps1 sentinel` → сервис поднялся на 8006, `http://localhost:8006/health` отдаёт 200.
2. `.\run.ps1 all` → в target `health` все семь сервисов зелёные.
3. Открыть `http://localhost:8006` → видны шесть плиток со статусом UP.
4. Искусственно уронить один сервис (остановить `cortex`) → в течение ~10 секунд его плитка становится DOWN и в ленте появляется инцидент с первопричиной `health_monitor: cortex_memory_service DOWN`.
5. Поднять cortex обратно → плитка возвращается в UP, событие восстановления в ленте.
6. Отправить голосовую команду → в `/v1/trace/{correlation_id}` видна цепочка событий через несколько сервисов с одним correlation_id.
7. Убить Sentinel, вызвать ошибку в brain → brain продолжает работать, ошибка легла в `logs/sentinel_fallback.jsonl`; после подъёма Sentinel она досылается и появляется на дашборде.
8. Перезапустить всё → старые ошибки на месте, читаются из `memory/sentinel.db`.
9. Проверить, что `gemini_api_key` нигде не встречается: `sqlite3 memory/sentinel.db "select * from errors"` — ключа нет.

Тестируй под Windows в обычной залогиненной desktop-сессии, не как службу. Для проверки эндпоинтов используй `Invoke-RestMethod`, а не `curl` — в PowerShell `curl` это алиас `Invoke-WebRequest` и он не понимает `-H`/`-d`.

Работай в отдельной ветке `feature/sentinel-service`, коммить логическими частями. В конце дай краткий отчёт: какие файлы созданы, какие изменены, что из чек-листа проверки прошло, а что нет.
