# 🏛️ D.O.N.N.A. / J.A.R.V.I.S. — Tactical Architecture & Developer Guide

> **Спецификация распределённой микросервисной архитектуры, модели памяти Cortex 3072D, Tool RAG роутера и протокола кибербезопасности Human-in-the-Loop.**

---

## 1. Обзор архитектуры (Grid Microservices Architecture)

Проект D.O.N.N.A. построен по принципу **высоконадёжной распределённой микросервисной архитектуры**.  
Система разделена на 5 логических уровней и выстроена по 4-колоночной функциональной матрице:

```
=========================================================================================================
TIER 1: CLIENT SURFACES & SENSORY INGESTION
  [ Сэр (Голос/Клавиатура) ]   [ Tactical React HUD ]   [ Ambient Sensor (IDE) ]   [ Telegram Bot ]
               │                          │                          │                     │
               ▼                          ▼                          ▼                     ▼
=========================================================================================================
TIER 2: EDGE GATEWAYS & CYBERSECURITY GUARDRAILS (Human-in-the-Loop)
  [ audio_stream (:8005) ]     [ web_dashboard (:8000) ] [ Cyber-Defense Barrier ] [ channel_gw (:8000) ]
               │                          │                          │                     │
               ▼                          ▼                          ▼                     ▼
=========================================================================================================
TIER 3: CENTRAL INTELLIGENCE & COGNITIVE CORE
  [ brain_orchestrator (:8001) ] ── [ Model Pool (gemini-2.0-flash) ] ── [ Dynamic Tool RAG ] ── [ Prompt ]
                                                  │
                                                  ▼
  ═══════════════════════ HIGH-SPEED INTERNAL INTER-SERVICE BUS (Bearer Token) ══════════════════════════
                                                  │
               ┌──────────────────┬───────────────┴──────────────┬──────────────────┐
               ▼                  ▼                              ▼                  ▼
=========================================================================================================
TIER 4: DISTRIBUTED WORKER FLEET & KNOWLEDGE ENGINES
  [ Cortex Memory (:8002) ]   [ Autonomous Agent (:8007) ]   [ Research Agent (:8003) ]  [ Win Host (:8004) ]
  • SQLite 3 WAL Mode         • Multi-Step ReAct Loop         • Grounded Web Search      • Win32 / Playwright
  • 3072D Vector Embeddings   • Code Fixes & Sandbox          • Word (.docx) & PDF       • Windows Reminders
               │                          │                              │                  │
               ▼                          ▼                              ▼                  ▼
=========================================================================================================
TIER 5: HOST OS, HARDWARE & ENVIRONMENT
  [ Persistent Storage ]      [ Windows 11 Enterprise ]      [ External Networks & Cloud ] [ Sentinel (:8006) ]
  • memory/cortex.db          • Win32 API / PowerShell       • Google GenAI Studio API    • Watchdog & Sentry
  • config/api_keys.json      • CPU/RAM/GPU Telemetry        • Telegram Cloud Servers     • Process Supervisor
=========================================================================================================
```

*Полная визуальная интерактивная диаграмма сохранена локально в формате Draw.io: `architecture_donna.drawio`.*

---

## 2. Спецификация 8 микросервисов (`:8000`–`:8007`)

Единая точка запуска и мониторинга — **`run_microservices.py`**. Процессы запускаются независимо через `uv run python -m <module>`:

| Порт | Сервис | Модуль | Описание и архитектурная ответственность |
| :--- | :--- | :--- | :--- |
| **8006** | **Sentinel Service** | `services.sentinel_service.app` | **Телеметрия и отказоустойчивость.** Запускается первым. Принимает батчи ошибок со всех сервисов по токену, дедуплицирует логи, сохраняет сбои в SQLite WAL (`memory/sentinel.db`) и отправляет критические алерты в Sentry. |
| **8002** | **Cortex Memory Service** | `services.cortex_memory_service.app` | **Семантическая память и база знаний.** 3072-мерные эмбеддинги (`models/gemini-embedding-2`), детерминированный SHA-256 fallback, управление задачами и фактами о проектах. БД: **SQLite 3 WAL Mode** с защитой от блокировок при параллельном доступе. |
| **8003** | **Research Agent Service** | `services.research_agent_service.app` | **Интеллектуальный поиск и синтез документов.** Глубокий ресёрч с фильтрацией галлюцинаций, агрегатор поисковых запросов, компиляция Word (.docx), PDF и схем Mermaid.js. |
| **8004** | **Windows Host Agent** | `services.windows_host_agent.app` | **Аппаратная автоматизация ОС Windows.** Резолвер приложений (.lnk, реестр, PATH), клики/скролл/ввод текста, браузерный контроллер Playwright, планировщик Windows Task Scheduler (`reminder`), аппаратные метрики `psutil`. |
| **8000** | **Channel Gateway Service** | `services.channel_gateway_service.app` | **Внешние каналы связи.** Сервер статики React Web HUD (`/hud`), WebSocket Hub клиентских подключений, Telegram Bot Bridge, OTP-авторизация и Cron-планировщик. |
| **8001** | **Brain Orchestrator** | `services.brain_orchestrator.app` | **Ядро интеллекта.** Полнодуплексный WebSocket с Google Gemini Live, конфигурация голоса (Ru-RU / Kore Voice), агрегатор контекста (Prompt + Ambient + Cortex), диспетчер 17 инструментов. |
| **8005** | **Audio Stream Service** *(опц.)* | `services.audio_stream_service.app` | **Аудио-драйвер.** SoundDevice захват микрофона (16 кГц PCM), оффлайн-VAD (детектор голоса), потоковое воспроизведение речи (24 кГц). |
| **8007** | **Autonomous Agent Service** | `services.autonomous_agent.app` | **Автономный ReAct-агент.** Многошаговый инженерный цикл (Thought ➔ Action ➔ Observation) на базе `gemini-2.0-flash`. Анализ кода, генерация диффов, безопасное исполнение в сэндбоксе. |

---

## 3. Когнитивное ядро (`core/`)

Внутри процесса `brain_orchestrator` (`:8001`) интегрированы 4 фундаментальных механизма:

### 3.1. Резистентный пул моделей (`core/model_pool.py`)
* **Приоритет на `gemini-2.0-flash`**: Быстрая модель с высокими квотами бесплатного тарифа (1500 RPD / 15 RPM).
* **Multi-Key Failover**: Поддержка пула резервных ключей (`gemini_backup_keys` в `config/api_keys.json`).
* **Auto-Cooldown**: Автоматическое охлаждение ключа на 60 секунд при получении ошибки 429 (Quota Exceeded) или 503 (Overloaded) и бесшовное переключение на следующий ключ.

### 3.2. Динамический Tool RAG роутер (`core/openclaw_engine.py`)
* Проблема: Вставка всех 51 навыка OpenClaw в контекст Gemini Live приводит к переполнению контекста, задержкам и галлюцинациям.
* Решение: In-Memory индекс и стемминг намерений на лету. В каждый конкретный запрос подмешиваются только 3–5 целевых навыков.
* Нативные генераторы: Прямой рендеринг Mermaid.js диаграмм в SVG/HTML и запуск в браузере.

### 3.3. Сенсор рабочей среды (`core/ambient_context.py`)
* Win32-трекинг: Отслеживание активного окна пользователя (`GetForegroundWindow`) и имени процесса (VS Code, Windows Terminal, Browser).
* Безопасный сниппет буфера обмена (<2000 символов) без утечки чувствительных паролей.
* Авто-инъекция: При обращении голосом или текстом Донна уже знает, над каким файлом или ошибкой компилятора работает Сэр.

### 3.4. Протокол безопасности (`core/prompt.txt`)
* Универсальное русскоязычное обращение: строго **«Сэр»**.
* Четкие сигнатуры инструментов: `open_app(app_name)`, `browser_control(action, url)`, `computer_settings(setting_type)`.
* Принцип Human-in-the-Loop: Деструктивные команды блокируются до получения подтверждения.

---

## 4. Векторная память Cortex 3072D (`memory/cortex_engine.py`)

Долговременная память полностью переведена на современный векторный стек:
1. **Модель эмбеддингов**: Google GenAI API `models/gemini-embedding-2`.
   * Возвращает 3072-мерный нормализованный вектор (L2-norm = 1.0).
   * Обеспечивает точный семантический поиск по концепциям на русском и английском языках.
2. **Оффлайн Fallback**: При недоступности сети или ошибках квот используется детерминированный SHA-256 проекционный вектор, что исключает сбои и падения сервиса памяти.
3. **SQLite WAL Mode**: База `memory/cortex.db` работает в режиме Write-Ahead Logging. Читающие микросервисы никогда не блокируют пишущие транзакции.
4. **Автомиграция**: При первом старте данные из устаревшего `long_term.json` автоматически конвертируются в реляционные и векторные таблицы.

---

## 5. Реестр 17 инструментов Gemini Live

Диспетчер `client_bridge.py` маршрутизирует вызовы модели в соответствующие микросервисы:

| № | Инструмент | Вызываемый микросервис | Назначение |
| :--- | :--- | :--- | :--- |
| 1 | `screen_process` | Windows Host (:8004) | Анализ экрана или камеры в реальном времени. |
| 2 | `open_app` | Windows Host (:8004) | Безопасный запуск любого приложения или файла через Win32 API. |
| 3 | `web_search` | Research Agent (:8003) | Быстрый поиск фактов и информации в сети. |
| 4 | `deep_research_report` | Research Agent (:8003) | Глубокий ресёрч и генерация форматированного Word (.docx) или PDF. |
| 5 | `agent_task` | Autonomous Agent (:8007) | Передача задачи на автономное решение, написание кода и отладку. |
| 6 | `autonomous_task` | Autonomous Agent (:8007) | Официальный алиас для `agent_task`. |
| 7 | `recall_memory` | Cortex Memory (:8002) | Семантический поиск по векторной базе памяти. |
| 8 | `save_knowledge` | Cortex Memory (:8002) | Сохранение фактов, заметок и предпочтений Сэра. |
| 9 | `manage_cortex_tasks` | Cortex Memory (:8002) | Управление задачами (создание, листинг, завершение). |
| 10 | `log_journal` | Cortex Memory (:8002) | Добавление заметок в хронологический журнал событий. |
| 11 | `computer_control` | Windows Host (:8004) | Ввод текста (включая русский Unicode), горячие клавиши, клики мыши. |
| 12 | `computer_settings` | Windows Host (:8004) | Регулировка громкости, яркости, сетевых адаптеров, закрытие окон. |
| 13 | `system_status` | Windows Host (:8004) | Снятие телеметрии процессора, оперативной памяти, GPU и дисков. |
| 14 | `browser_control` | Windows Host (:8004) | Управление вкладками Chrome, Edge, Firefox через Playwright. |
| 15 | `reminder` | Windows Host (:8004) | Создание системных напоминаний через Планировщик Windows. |
| 16 | `youtube_video` | Research Agent (:8003) | Поиск, воспроизведение и анализ стенограмм видеороликов YouTube. |
| 17 | `openclaw_skill` | Brain Core (:8001) | Динамический запуск любого из 51 специализированного навыка OpenClaw. |

---

## 6. Кибербезопасность и защита периметра

1. **Межсервисный токен (`X-Donna-Internal-Token`)**:
   - При старте `run_microservices.py` генерирует 256-битный токен. Все HTTP REST вызовы между микросервисами проверяются middleware `verify_internal_token`. Неавторизованные внешние запросы отклоняются с кодом `403 Forbidden`.
2. **CORS и веб-безопасность**:
   - Запрещен `*`. Доступ открыт только для локального шлюза (`:8000`) и интерфейсов разработки (`:3000`, `:5173`).
3. **Безопасность загрузок**:
   - Все загружаемые через дашборд исполняемые файлы (`.exe`, `.bat`, `.ps1`, `.vbs`) суффиксируются `.download`.
4. **Защита спаривания Telegram**:
   - Спаривание требует ввода одноразового 6-значного OTP-кода (`/pair <OTP>`), отображаемого на локальном экране.
5. **Anti-Prompt-Injection**:
   - Внешние ненадёжные данные оборачиваются в изолированные теги `<UNTRUSTED EXTERNAL DATA>`.
   - Запрещены любые попытки перезаписи системных файлов или очистки дисков.

---

## 7. Разработка, запуск и верификация

Все команды выполняются через пакетный менеджер **`uv`**:

```powershell
# Установка зависимостей в изолированный .venv:
uv sync

# Запуск всей системы (все 8 микросервисов):
uv run python run_microservices.py

# Запуск со смоук-тестом импортов всех сервисов:
uv run python scripts/smoke_test.py

# Запуск архитектурных тестов pytest:
uv run pytest tests/test_jarvis_core.py -v
```
