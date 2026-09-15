# Архитектурный план: Переход D.O.N.N.A. на микросервисную архитектуру

Перевод системы **D.O.N.N.A. (Stark OS)** из текущего монолитного приложения в микросервисную архитектуру с сохранением всего богатого функционала (голосовой диалог в реальном времени, память Cortex, управление Windows, веб-исследования, Telegram-мост и тактический HUD).

---

## 1. Анализ текущего состояния и ограничения

Текущая кодовая база представляет собой монолитное приложение Python:
- **[main.py](file:///c:/Users/Minerva/Downloads/projects/DONNA/main.py)** совмещает в себе: захват и вывод аудио (`sounddevice`), локальное распознавание Vosk, сессию Gemini Live WebSocket, выполнение 26+ инструментов, мониторинг системы, RSS-мониторинг, Telegram-бота, планировщик Cron и запуск мобильного веб-сервера.
- **[ui.py](file:///c:/Users/Minerva/Downloads/projects/DONNA/ui.py)**: GUI на PyQt6, жестко связанный с памятью главного процесса через прямые вызовы методов.
- **[memory/cortex_engine.py](file:///c:/Users/Minerva/Downloads/projects/DONNA/memory/cortex_engine.py)**: локальная SQLite БД и векторный поиск в том же процессе.

### Ключевое физическое ограничение Windows
Микросервисы традиционно упаковываются в Docker-контейнеры. Однако:
1. **Управление ОС** (`pyautogui`, `win32gui`, `ctypes`, скриншоты экрана, эмуляция кликов, запуск локальных `.exe` программ) **не может** работать внутри изолированного Linux-контейнера Docker — ему требуется активная сессия рабочего стола Windows.
2. **Микрофон и динамики** (`sounddevice`, PyAudio) требуют прямого доступа к звуковой карте хоста.

**Решение**: Гибридная микросервисная архитектура:
* **Host Daemons (локальные микросервисы на Windows)**: Сервисы работы со звуком и низкоуровневого контроля операционной системы.
* **Containerized Services (Docker / независимые процессы)**: Бизнес-логика, векторная память, оркестратор ИИ, автономный браузерный агент, Telegram и шлюзы интеграций.

---

## 2. Предлагаемая микросервисная декомпозиция

```
                                ┌──────────────────────────────────────┐
                                │      Tactical HUD (PyQt6 / React)    │
                                └──────────────────┬───────────────────┘
                                                   │ WebSocket / REST
                                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                               SERVICE 1: BRAIN ORCHESTRATOR                                      │
│                           (FastAPI Gateway + Gemini Live Stream)                                 │
│                                  Port: 8001 (Docker / Process)                                   │
└────────────┬─────────────────────────┬──────────────────────────┬────────────────────────────┬───┘
             │ gRPC / REST             │ REST                     │ REST                       │ WebSocket
             ▼                         ▼                          ▼                            ▼
┌─────────────────────────┐ ┌──────────────────────┐ ┌─────────────────────────┐ ┌─────────────────────────┐
│       SERVICE 2         │ │      SERVICE 3       │ │       SERVICE 4         │ │       SERVICE 5         │
│     CORTEX MEMORY       │ │   RESEARCH AGENT     │ │   CHANNEL GATEWAY       │ │     AUDIO STREAM        │
│ • SQLite + 3072D Embed  │ │ • Chromium Playwright│ │ • Telegram Bot Polling  │ │ • Mic capture (16kHz)   │
│ • Semantic Search       │ │ • DuckDuckGo Search  │ │ • Mobile Web Dashboard  │ │ • Vosk Wake Word Engine │
│ • Tasks & Journal       │ │ • Docx/PDF Generator │ │ • RSS News Monitor      │ │ • Voice Barge-In        │
│ • Port: 8002            │ │ • Port: 8003         │ │ • Cron Scheduler        │ │ • Speaker Output (24kHz)│
│ (Docker / Process)      │ │ (Docker / Process)   │ │ • Port: 8000 (Docker)   │ │ • Port: 8005 (Win Host) │
└─────────────────────────┘ └──────────────────────┘ └─────────────────────────┘ └─────────────────────────┘
                                                                                               │
                                                                   ┌───────────────────────────┴───────────┐
                                                                   │               SERVICE 6               │
                                                                   │           WINDOWS HOST AGENT          │
                                                                   │ • Native Mouse & Keyboard Control     │
                                                                   │ • Win32 App Launcher & Window Control │
                                                                   │ • Screen & Webcam Capture             │
                                                                   │ • Hardware Telemetry (CPU/GPU/RAM)    │
                                                                   │ • Port: 8004 (Windows Host Daemon)    │
                                                                   └───────────────────────────────────────┘
```

### Спецификация микросервисов:

1. **`brain-orchestrator` (Порт: 8001)**:
   - **Стек**: FastAPI + WebSocket + `google-genai`.
   - **Ответственность**: Центральный шлюз, поддержание Live-сессии с Gemini 2.5, хранение кратковременного контекста диалога, маршрутизация Function Calling (Tool Calls) в соответствующие сервисы по HTTP/REST.

2. **`cortex-memory-service` (Порт: 8002)**:
   - **Стек**: FastAPI, SQLite3, Gemini Embedding / N-gram fallback.
   - **API**:
     - `POST /v1/memory/recall` — семантический поиск по 3072D-эмбеддингам.
     - `POST /v1/memory/save` — сохранение фактов и заметок.
     - `GET /v1/tasks`, `POST /v1/tasks` — управление задачами.
     - `POST /v1/journal` — запись в дневник.

3. **`research-agent-service` (Порт: 8003)**:
   - **Стек**: FastAPI, Playwright (Chromium), `python-docx`, DuckDuckGo.
   - **API**:
     - `POST /v1/research/search` — быстрый и глубокий веб-поиск.
     - `POST /v1/research/task` — сбор данных по URL и синтез Word `.docx` / `.pdf`.
     - `GET /v1/media/youtube` — получение транскриптов и аналитика видео.

4. **`windows-host-agent` (Порт: 8004)** *(Обязательно Windows Host)*:
   - **Стек**: FastAPI (localhost only), `pyautogui`, `pywinauto`, `mss`, `cv2`, `psutil`, NVML.
   - **API**:
     - `POST /v1/os/execute-action` — клики, ввод текста на русском (через буфер обмена), горячие клавиши.
     - `POST /v1/os/launch-app` — запуск локальных программ Windows с умными алиасами.
     - `POST /v1/os/settings` — громкость, яркость, управление окнами, завершение процессов.
     - `GET /v1/os/screenshot` — захват экрана для компьютерного зрения.
     - `GET /v1/os/telemetry` — мониторинг CPU %, RAM %, GPU %, температура.

5. **`audio-stream-service` (Порт: 8005)** *(Windows Host)*:
   - **Стек**: `sounddevice`, `vosk`, `miniaudio`, WebSocket-клиент.
   - **Ответственность**:
     - Постоянный захват звука с микрофона (16 кГц PCM).
     - Локальный оффлайн-движок Vosk (Wake Word «Донна», Barge-In «Стоп»).
     - Стриминг аудио-чанков в `brain-orchestrator` через WebSocket.
     - Приём входящего аудио 24 кГц от `brain-orchestrator` и вывод в динамики.

6. **`channel-gateway-service` (Порт: 8000)**:
   - **Стек**: FastAPI, Uvicorn, WebSockets, `python-telegram-bot`, `feedparser`.
   - **Ответственность**:
     - Мобильный Web Dashboard (порт 8000) с QR-авторизацией.
     - Фоновый RSS-мониторинг тем и новостей.
     - Telegram Bridge (приём команд и уведомления).
     - Cron Daemon (периодические напоминания и чекины).

7. **`tactical-hud-client`**:
   - Автономный клиент интерфейса (PyQt6 или React), который больше не содержит логику Gemini/Audio, а подключается к `brain-orchestrator` и `windows-host-agent` по WebSocket для получения телеметрии и состояний (`STANDBY`, `LISTENING`, `THINKING`, `SPEAKING`).

---

## 3. Пользовательские решения и открытые вопросы

> [!IMPORTANT]
> **Архитектурный выбор транспорта**:
> 1. **FastAPI (REST + WebSockets)**: Максимально прозрачно, просто для отладки, идеально стыкуется со Swagger UI и браузерными клиентами.
> 2. **gRPC + Protobuf**: Выше производительность сериализации для бинарных потоков, но требует генерации proto-файлов и сложнее в обслуживании.
> *(Рекомендуется: FastAPI (REST + WebSockets) для всех сервисов)*.

> [!WARNING]
> **Способ развёртывания**:
> Часть микросервисов (`cortex-memory`, `research-agent`, `channel-gateway`, `brain-orchestrator`) можно запускать через **Docker Compose**, но сервисы `windows-host-agent`, `audio-stream-service` и `tactical-hud-client` должны запускаться на хосте Windows.
> Мы предоставим единый скрипт оркестрации запуска `run_microservices.py` / `docker-compose.yml`, который поднимает все компоненты одной командой.

---

## 4. План реализации по этапам

### Этап 1: Общие контракты и модели (Pydantic DTO)
* Создание пакета `shared/` с едиными моделями данных:
  - `shared/models/memory.py` (MemoryNode, TaskItem, SearchQuery)
  - `shared/models/os_control.py` (OSActionRequest, SystemMetrics)
  - `shared/models/research.py` (ResearchTaskRequest, SearchResponse)
  - `shared/models/events.py` (AudioChunk, HUDStateEvent)

### Этап 2: Выделение `cortex-memory-service`
* Создание `services/cortex_memory/`:
  - Перенос `memory/cortex_engine.py` в микросервис с FastAPI эндпоинтами.
  - Тестирование независимой работы базы данных и семантического поиска через Swagger UI.

### Этап 3: Выделение `research-agent-service`
* Создание `services/research_agent/`:
  - Перенос `actions/agent_task.py`, `actions/web_search.py`, `actions/youtube_video.py`.
  - Упаковка браузерного агента Playwright в изолированный микросервис.

### Этап 4: Выделение `windows-host-agent`
* Создание `services/windows_host_agent/`:
  - Перенос `computer_control.py`, `computer_settings.py`, `open_app.py`, `screen_processor.py`, `system_monitor.py`.
  - Реализация REST API для управления Windows.

### Этап 5: Выделение `channel-gateway-service`
* Создание `services/channel_gateway/`:
  - Перенос мобильного дашборда `dashboard/server.py`, `telegram_bridge.py`, `background_monitor.py`, `cron_engine.py`.

### Этап 6: Выделение `audio-stream-service`
* Создание `services/audio_stream/`:
  - Перенос `core/wakeword.py`, аудио-буферов `sounddevice`, SFX-плеера.
  - Реализация WebSocket-клиента для двустороннего стриминга аудио в Брэйн.

### Этап 7: Рефакторинг `brain-orchestrator` (Core Gateway)
* Создание `services/brain_orchestrator/`:
  - Упрощение `main.py`: удаление прямого кода железа, замена прямых вызовов `actions/` на HTTP/WebSocket RPC к соответствующим микросервисам.
  - Конфигурация Function Calling в Gemini для маршрутизации по URL микросервисов.

### Этап 8: Обновление Tactical HUD и оркестрация запуска
* Создание `docker-compose.yml` для контейнеризуемых сервисов.
* Создание `run_microservices.py` для параллельного запуска всех сервисов с логами и контролем жизненного цикла.
* Обновление `ui.py` для работы через WebSocket события.

---

## 5. План верификации

### Автоматические тесты:
1. **Health-check каждого сервиса**:
   - `GET http://localhost:8001/health` (Brain Orchestrator)
   - `GET http://localhost:8002/health` (Cortex Memory)
   - `GET http://localhost:8003/health` (Research Agent)
   - `GET http://localhost:8004/health` (Windows Host Agent)
   - `GET http://localhost:8000/health` (Channel Gateway)
2. **Интеграционные тесты RPC**:
   - Проверка сохранения и поиска в Cortex через REST API.
   - Проверка выполнения веб-поиска и генерации тестового `.docx`.
   - Проверка сбора телеметрии с Windows Host Agent.

### Ручная валидация:
1. Запуск всей системы через `python run_microservices.py`.
2. Голосовая активация по слову «Донна» и проверка сквозного диалога.
3. Проверка команды «Донна, открой калькулятор» (Brain -> Windows Host Agent).
4. Проверка команды прерывания «Донна, стоп» (Audio Stream Service -> Brain).
5. Проверка подключения мобильного пульта через QR-код.
