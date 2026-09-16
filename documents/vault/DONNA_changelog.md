# Журнал изменений микросервисов и интерфейса DONNA

**Дата:** 15 сентября 2026 г.  
**Статус:** Все исправления протестированы, компиляция `py_compile` успешна (код 0).

---

## 1. Сводка выполненных работ

В ходе ревизии были устранены ошибки типизации (Pyright), потенциальные падения в рантайме (Runtime Errors) и дефекты обработки событий Qt:

1. **`services/brain_orchestrator/app.py`**:
   - Миграция с устаревшего обработчика FastAPI `@app.on_event("startup")` на современный механизм `lifespan`.
   - Защита от сбоев при пустых ответах от Gemini Live (`parts` и `function_calls` теперь безопасно проверяются на `None`).
   - Устранение ложных предупреждений типизации для модулей `google.genai` (`genai: Any`, `types: Any`).
   - Безопасная переконфигурация кодировки `sys.stdout` / `sys.stderr` на Windows.
   - Удаление избыточных вызовов `str()` на строках вывода результатов инструментов.

2. **`services/brain_orchestrator/client_bridge.py`**:
   - Приведение сигнатур методов (`manage_cortex_tasks`, `computer_settings`, `web_search`, `youtube_video`) к стандартам PEP 484: параметры со значениями по умолчанию `None` теперь явно типизированы через `Optional[...]`. Это исключило конфликты типов при пробросе аргументов из тулов.

3. **`actions/web_search.py`**:
   - Безопасное извлечение `candidates[0].content.parts`: добавлена проверка на `None` для `first_cand.content` и `content.parts` (предотвращает падение при блокировках ответов Gemini Safety).
   - Обработка ссылок BeautifulSoup (`href`): значения атрибута приводятся к `str` перед проверками подстроки и вызовом `urllib.parse`.
   - Оптимизирован импорт DuckDuckGo: приоритетный импорт `duckduckgo_search` с безопасным fallback на `ddgs`.
   - Исправлена ошибка отступов в функции `_ddg_news`.

4. **`ui.py`**:
   - **Устранено дублирование `resizeEvent` в `MainWindow`**: ранее второй обработчик на строке 2309 полностью затирал первый обработчик со строки 1464, из-за чего оверлей сканлайнов не ресайзился. Оба обработчика объединены в один.
   - **Приведение сигнатур событий PyQt6**: переопределённые методы (`mouseMoveEvent`, `leaveEvent`, `mousePressEvent`, `paintEvent`, `dragEnterEvent`, `dropEvent`, `closeEvent`) приведены к базовому имени параметра `a0`.
   - Для Drag & Drop (`dragEnterEvent` и `dropEvent`) типы аргументов обновлены до `QDragEnterEvent | None` и `QDropEvent | None` с защитной проверкой `if a0 is None: return`.
   - **Защита от вызовов методов на `None`**: добавлены проверки для `self.centralWidget()`, `QApplication.primaryScreen()`, `QApplication.clipboard()`, `self._log.verticalScrollBar()` и `a0.mimeData()`.
   - Объявлен атрибут `self.on_clicked = None` в конструкторе `FridaySphereCanvas`.
   - Устранены избыточные вызовы `int()` и добавлена аннотация `_nvml_ok: Optional[bool] = None`.
   - Добавлены `# type: ignore` для внешних модулей `psutil`, `qrcode` и `win32com.client`.

---

## 2. Детальный разбор изменений по файлам

### Файл 1: `services/brain_orchestrator/app.py`

#### A. Добавление Lifespan вместо `@app.on_event("startup")`
**Было:**
```python
app = FastAPI(
    title="DONNA Brain Orchestrator",
    description="Central LLM Gateway, Gemini Live Duplex Streamer, and Service Router",
    version="2.0.0",
)

...

@app.on_event("startup")
async def on_startup():
    brain._loop = asyncio.get_running_loop()
    asyncio.create_task(brain.run_gemini_session())
```
**Стало:**
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    brain._loop = asyncio.get_running_loop()
    asyncio.create_task(brain.run_gemini_session())
    yield

app = FastAPI(
    title="DONNA Brain Orchestrator",
    description="Central LLM Gateway, Gemini Live Duplex Streamer, and Service Router",
    version="2.0.0",
    lifespan=lifespan,
)
```

#### B. Безопасная обработка аудио-чанков и вызовов инструментов
**Было:**
```python
if not raw_audio and response.server_content and response.server_content.model_turn:
    for part in response.server_content.model_turn.parts:
        if part.inline_data and part.inline_data.data:
            raw_audio = part.inline_data.data
            break

...

tool_call = response.tool_call
if tool_call:
    fn_responses = []
    for fc in tool_call.function_calls:
        fr = await self.dispatch_tool_call(fc)
        fn_responses.append(fr)
```
**Стало:**
```python
if not raw_audio and response.server_content and response.server_content.model_turn:
    if response.server_content.model_turn.parts:
        for part in response.server_content.model_turn.parts:
            if part.inline_data and part.inline_data.data:
                raw_audio = part.inline_data.data
                break

...

tool_call = response.tool_call
if tool_call and tool_call.function_calls:
    fn_responses = []
    for fc in tool_call.function_calls:
        fr = await self.dispatch_tool_call(fc)
        fn_responses.append(fr)
```

---

### Файл 2: `services/brain_orchestrator/client_bridge.py`

#### Типизация параметров по умолчанию `None`
**Было:**
```python
async def manage_cortex_tasks(self, action: str = "list", task: str = None, task_id: int = None, status: str = None, priority: str = "normal", due_date: str = None, project: str = None) -> str:
...
async def web_search(self, query: str, mode: str = "search", items: list = None, aspect: str = None) -> str:
...
async def youtube_video(self, action: str = "play", query: str = None, url: str = None, save: bool = False) -> str:
...
async def computer_settings(self, action: str, value: Any = None, app_name: str = None) -> str:
```
**Стало:**
```python
async def manage_cortex_tasks(self, action: str = "list", task: Optional[str] = None, task_id: Optional[int] = None, status: Optional[str] = None, priority: str = "normal", due_date: Optional[str] = None, project: Optional[str] = None) -> str:
...
async def web_search(self, query: str, mode: str = "search", items: Optional[list] = None, aspect: Optional[str] = None) -> str:
...
async def youtube_video(self, action: str = "play", query: Optional[str] = None, url: Optional[str] = None, save: bool = False) -> str:
...
async def computer_settings(self, action: str, value: Any = None, app_name: Optional[str] = None) -> str:
```

---

### Файл 3: `actions/web_search.py`

#### A. Безопасное чтение parts из ответа Gemini
**Было:**
```python
if response.candidates and len(response.candidates) > 0:
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text
```
**Стало:**
```python
if response.candidates and len(response.candidates) > 0:
    first_cand = response.candidates[0]
    if first_cand.content and first_cand.content.parts:
        for part in first_cand.content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text
```

#### B. Безопасная обработка `href` BeautifulSoup
**Было:**
```python
url_link = link_el.get("href", "")
if "duckduckgo.com/l/?uddg=" in url_link:
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url_link).query)
```
**Стало:**
```python
href_val = link_el.get("href", "")
url_link = str(href_val) if href_val else ""
if "duckduckgo.com/l/?uddg=" in url_link:
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url_link).query)
```

#### C. Упорядоченный fallback для библиотеки DuckDuckGo
**Было:**
```python
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
```
**Стало:**
```python
try:
    from duckduckgo_search import DDGS
except ImportError:
    try:
        from ddgs import DDGS  # type: ignore
    except ImportError:
        DDGS = None

if DDGS is None:
    return []
```

---

### Файл 4: `ui.py`

#### A. Объединение обработчиков `resizeEvent` в `MainWindow`
**Было (два несвязанных метода, второй затирал первый):**
```python
# Строка 1464:
def resizeEvent(self, e):
    super().resizeEvent(e)
    if hasattr(self, "_scanlines") and self._scanlines:
        self._scanlines.setGeometry(self.rect())
        self._scanlines.raise_()

...

# Строка 2309:
def resizeEvent(self, e):
    super().resizeEvent(e)
    cw = self.centralWidget()
    if self._remote_overlay and self._remote_overlay.isVisible():
        ...
```
**Стало (единый объединённый метод):**
```python
def resizeEvent(self, a0):
    super().resizeEvent(a0)
    if hasattr(self, "_scanlines") and self._scanlines:
        self._scanlines.setGeometry(self.rect())
        self._scanlines.raise_()
    cw = self.centralWidget()
    if cw:
        if hasattr(self, "_remote_overlay") and self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        if hasattr(self, "_overlay") and self._overlay and self._overlay.isVisible():
            ow, oh = SetupOverlay._OW, SetupOverlay._OH
            self._overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        if hasattr(self, "_customize_overlay") and self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
```

#### B. Корректные сигнатуры Drag & Drop
**Было:**
```python
def dragEnterEvent(self, event: QDragEnterEvent):
    if event.mimeData().hasUrls():
        event.acceptProposedAction()

def dropEvent(self, event: QDropEvent):
    urls = event.mimeData().urls()
    ...
```
**Стало:**
```python
def dragEnterEvent(self, a0: QDragEnterEvent | None):
    if a0 is None:
        return
    md = a0.mimeData()
    if md and md.hasUrls():
        a0.acceptProposedAction()

def dropEvent(self, a0: QDropEvent | None):
    if a0 is None:
        return
    md = a0.mimeData()
    if md and md.hasUrls():
        urls = md.urls()
        ...
```

#### C. Безопасное позиционирование окна на экране
**Было:**
```python
screen = QApplication.primaryScreen().availableGeometry()
self.move((screen.width() - 1180) // 2, (screen.height() - 740) // 2)
```
**Стало:**
```python
screen = QApplication.primaryScreen()
if screen:
    geom = screen.availableGeometry()
    self.move((geom.width() - 1180) // 2, (geom.height() - 740) // 2)
```

---

## 3. Дополнение от 16 сентября 2026 г. — работы, предшествовавшие screen capture

> **Про статус ниже:** раздел 3.1 (Sentinel) подтверждён вживую — дашборд поднят, все 6 сервисов видны как UP, реальные каскадные ошибки корректно захвачены и сгруппированы (проверено по скриншотам живого запуска). Разделы 3.2 и 3.3 — это точные Было/Стало по коду, который реально стоял в архиве проекта на момент ревизии, и техническое задание, переданное Antigravity для исправления; сам факт применения фикса в этом чате отдельно не перепроверялся повторной выгрузкой архива — стоит сверить при следующей синхронизации.

### Файл 5 (новый сервис): `services/sentinel_service/` — D.O.N.N.A. SENTINEL

Добавлен седьмой микросервис — централизованный сборщик и веб-дашборд ошибок для всех остальных шести сервисов, с хранением в SQLite и группировкой каскадных сбоев в инциденты.

**Новые файлы:**
- `services/sentinel_service/__init__.py`, `app.py` — FastAPI-сервис на порту **8006**: `GET /health`, `POST /v1/errors`, `POST /v1/errors/batch`, `GET /v1/errors`, `GET /v1/incidents`, `GET /v1/incidents/{id}`, `GET /v1/trace/{correlation_id}`, `GET /v1/stats`, `DELETE /v1/errors`, `WS /ws/errors`, `GET /` (дашборд).
- `services/sentinel_service/store.py` — слой хранения на `sqlite3` (`memory/sentinel.db`, `PRAGMA journal_mode=WAL`), таблицы `errors` и `service_status`, дедупликация одинаковых ошибок через `fingerprint` (sha1 от нормализованного сообщения), группировка каскадных сбоев в `incident_id` по 30-секундному окну.
- `services/sentinel_service/dashboard.html` — самодостаточный одностраничный дашборд (без CDN/сборки): статус шести сервисов, лента инцидентов с подсветкой первопричины, живое обновление по WebSocket.
- `shared/models/sentinel.py` — pydantic-модели `ErrorSeverity`, `ErrorReport`, `ErrorRecord`, `ServiceStatusEvent`, `IncidentSummary`.
- `shared/error_reporter.py` — клиентская библиотека, подключаемая ко всем шести существующим сервисам: неблокирующая фоновая очередь, fallback-файл `logs/sentinel_fallback.jsonl` при недоступности Sentinel, перехват необработанных исключений (`sys.excepthook`, `threading.excepthook`, `loop.set_exception_handler`), маскирование ключей/токенов перед записью.

**Изменения существующих файлов:**

`shared/config.py`
**Было:**
```python
CHANNEL_GATEWAY_HOST = os.getenv("DONNA_CHANNEL_HOST", "127.0.0.1")
CHANNEL_GATEWAY_PORT = int(os.getenv("DONNA_CHANNEL_PORT", "8000"))

# Service URLs
BRAIN_SERVICE_URL = f"http://{BRAIN_HOST}:{BRAIN_PORT}"
```
**Стало:**
```python
CHANNEL_GATEWAY_HOST = os.getenv("DONNA_CHANNEL_HOST", "127.0.0.1")
CHANNEL_GATEWAY_PORT = int(os.getenv("DONNA_CHANNEL_PORT", "8000"))

SENTINEL_HOST = os.getenv("DONNA_SENTINEL_HOST", "127.0.0.1")
SENTINEL_PORT = int(os.getenv("DONNA_SENTINEL_PORT", "8006"))
SENTINEL_SERVICE_URL = f"http://{SENTINEL_HOST}:{SENTINEL_PORT}"
SENTINEL_ENABLED = os.getenv("DONNA_SENTINEL_ENABLED", "1") == "1"

# Service URLs
BRAIN_SERVICE_URL = f"http://{BRAIN_HOST}:{BRAIN_PORT}"
```

Во всех шести `services/<name>/app.py` (пример — `brain_orchestrator`), сразу после создания `app`:
**Было:**
```python
app = FastAPI(
    title="DONNA Brain Orchestrator",
    description="Central LLM Gateway, Gemini Live Duplex Streamer, and Service Router",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    ...
)
```
**Стало:**
```python
app = FastAPI(
    title="DONNA Brain Orchestrator",
    description="Central LLM Gateway, Gemini Live Duplex Streamer, and Service Router",
    version="2.0.0",
    lifespan=lifespan,
)
from shared.error_reporter import install_sentinel
install_sentinel(app, "brain_orchestrator")

app.add_middleware(
    CORSMiddleware,
    ...
)
```

`run.ps1` — добавлен target `sentinel`, добавлен в `all` (первым, до остальных сервисов), добавлен порт 8006 в хэштаблицу `health`:
**Было:**
```powershell
switch ($target) {
    "cortex"     { python -m uvicorn services.cortex_memory_service.app:app --port 8002 }
    ...
    "all" {
        Start-Job -Name "cortex" ...
```
**Стало:**
```powershell
switch ($target) {
    "sentinel"   { python -m uvicorn services.sentinel_service.app:app --port 8006 }
    "cortex"     { python -m uvicorn services.cortex_memory_service.app:app --port 8002 }
    ...
    "all" {
        Start-Job -Name "sentinel"  { ... uvicorn services.sentinel_service.app:app --port 8006 }
        Start-Job -Name "cortex" ...
```
и в `health`:
```powershell
$ports = @{sentinel=8006; cortex=8002; brain=8001; research=8003; channel=8000; hostagent=8004; audio=8005}
```

`run_microservices.py` — SENTINEL добавлен первым элементом списка `SERVICES` (порт 8006, стартует раньше остальных, чтобы ловить их ошибки старта), в `_stream_output` добавлен скрейпер stdout дочерних процессов на ключевые слова (`Traceback`, `ERROR`, `CRITICAL`, `Exception`, `Failed`) как дополнительная страховочная сеть для того, что не проходит через `error_reporter`.

`.gitignore` — добавлено:
```
memory/sentinel.db
memory/sentinel.db-wal
memory/sentinel.db-shm
logs/
```

**Подтверждено вживую:** дашборд на `http://localhost:8006` показывает все 6 сервисов как UP; реальный каскадный сбой (`brain_connection: Cannot connect to host 127.0.0.1:8001`) был схлопнут в одну запись с тегами пяти затронутых сервисов; отдельно пойман `gemini_session: timed out during opening handshake`.

---

### Файл 6: `actions/open_app.py` и `services/windows_host_agent/app.py` — ложный успех запуска приложений

**Найденный баг (воспроизведён вживую):** голосовая команда открыть браузер привела к тому, что `open_app()` вернул `"Opened browser."`, `POST /v1/os/launch-app` отдал `200 OK`, а на экране при этом всплыл нативный диалог Windows **"Windows cannot find 'browser'"**. Причина — `_launch_windows()` считает успехом сам факт, что `subprocess.Popen('start "" "{app_name}"', shell=True)` не бросил исключение, хотя `start` почти никогда не бросает исключение из Python, даже когда сам не может найти приложение.

**Было (`actions/open_app.py`):**
```python
def _launch_windows(app_name: str) -> bool:
    """Non-blocking, dynamic Windows application launcher."""
    try:
        subprocess.Popen(f'start "" "{app_name}"', shell=True)
        return True
    except Exception:
        pass

    if shutil.which(app_name) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(app_name, shell=True)
            return True
        except Exception:
            pass

    return False
```

**Техническое задание, переданное Antigravity (статус применения не переподтверждён в этом чате):**
- Резолвинг обобщённых категорий ("browser"/"браузер", "почта"/"email", "проводник") через реестр Windows (`winreg`, `UrlAssociations\...\UserChoice`) вместо слепого `start`.
- Различение «подтверждённого» запуска (реально резолвленный путь + `os.startfile`/`Popen([path])`, которые бросают исключение при провале) и «неподтверждённого» (старый fallback через shell) — раньше оба варианта считались одинаковым успехом.
- Для неподтверждённого пути — новый модуль `actions/dialog_watchdog.py`, опрашивающий открытые окна через `pywin32` (`win32gui`) на предмет появления стандартного диалога-ошибки (класс `#32770`) в течение ~2 секунд после попытки запуска; при обнаружении — текст диалога уходит в Sentinel как `ERROR` с source `open_app_dialog_detect`, и запрос считается проваленным, а не успешным.
- `services/windows_host_agent/app.py`, эндпоинт `POST /v1/os/launch-app` — раньше всегда возвращал `success=True` независимо от результата `open_app()`:

**Было:**
```python
@app.post("/v1/os/launch-app", response_model=GenericResponse)
def api_launch_app(req: AppLaunchRequest):
    try:
        params = {"app_name": req.app_name}
        res_text = open_app(parameters=params)
        return GenericResponse(success=True, message=res_text or f"Launched {req.app_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
**Задано как исправление:**
```python
@app.post("/v1/os/launch-app", response_model=GenericResponse)
def api_launch_app(req: AppLaunchRequest):
    try:
        params = {"app_name": req.app_name}
        res_text = open_app(parameters=params)
        failed = res_text.startswith("Failed to open") or res_text.startswith("Could not confirm")
        return GenericResponse(success=not failed, message=res_text or f"Launched {req.app_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Полное ТЗ (с резолвингом категорий, dialog watchdog, требованиями к качеству и сценарием проверки) передано Antigravity отдельным файлом `openapp_fix_prompt.md`.

---

### Файл 7: `services/brain_orchestrator/app.py` — падение `computer_control` при любом вызове

**Найденный баг (обнаружен через реальную ошибку в Sentinel):** любой вызов инструмента `computer_control` падал с `TypeError: MicroserviceBridge.computer_control() got multiple values for argument 'action'`, потому что `action` передавался и позиционно, и повторно через `**args`.

**Было (`dispatch_tool_call`, ветка `computer_control`):**
```python
elif name == "computer_control":
    result = await bridge.computer_control(args.get("action", "click"), **args)
```
**Стало:**
```python
elif name == "computer_control":
    action = args.get("action", "click")
    result = await bridge.computer_control(action, **{k: v for k, v in args.items() if k != "action"})
```

Этот же фикс включён первым пунктом в техническое задание на screen capture (`screen_vision_prompt.md`), чтобы не потерялся при следующем прогоне Antigravity.
