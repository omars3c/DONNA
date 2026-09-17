# 🏛️ D.O.N.N.A. — Architecture & Developer Guide

> **Руководство для разработчиков по структуре проекта, микросервисам и протоколам взаимодействия.**

---

## 1. Обзор архитектуры (Pure Microservices)

Проект полностью переведён с монолитной структуры (`main.py`) на **чистую распределённую архитектуру микросервисов**.
Единой точкой запуска всей системы является оркестратор **`run_microservices.py`**.

Все сервисы запускаются как изолированные независимые процессы, взаимодействуют по **HTTP REST** и **WebSocket**, а также автоматически рапортуют о сбоях в локальный сервис мониторинга **Sentinel** и удалённый **Sentry**.

```
                           ┌─────────────────────────────────────┐
                           │      run_microservices.py           │
                           │   (Process Supervisor / Runner)     │
                           └──────────────────┬──────────────────┘
                                              │
         ┌───────────────────┬────────────────┼──────────────────┬───────────────────┐
         ▼                   ▼                ▼                  ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌───────────┐ ┌─────────────────────┐ ┌─────────────────┐
│ Sentinel (:8006)│ │ Cortex  (:8002) │ │ Research  │ │ Win Host  (:8004)   │ │ Gateway (:8000) │
│ Error Tracker & │ │ Memory, Vector  │ │  (:8003)  │ │ OS Control, Apps,   │ │ Web Dashboard,  │
│ Telemetry Store │ │ RAG & SQLite    │ │ Scraping  │ │ System Metrics      │ │ Telegram Bridge │
└─────────────────┘ └─────────────────┘ └───────────┘ └─────────────────────┘ └─────────────────┘
                                              ▲
                                              │ REST Inter-Service Bridge
                                              ▼
                                    ┌───────────────────┐
                                    │ Brain Orchestrator│
                                    │     (:8001)       │
                                    │ Gemini Live Duplex│
                                    │ State & Dialog    │
                                    └─────────┬─────────┘
                                              │
                                              ▼ (Local PCM WebSocket)
                                    ┌───────────────────┐
                                    │ Audio Stream      │
                                    │ Service (:8005)   │
                                    │ Mic / Speaker I/O │
                                    └───────────────────┘
```

---

## 2. Спецификация микросервисов

| Порт | Сервис | Модуль запуска | Назначение и функции |
| :--- | :--- | :--- | :--- |
| **8006** | **Sentinel Service** | `services.sentinel_service.app` | **Центр телеметрии и ошибок.** Запускается первым. Собирает стектрейсы со всех сервисов, дедуплицирует логи, сохраняет в SQLite (`memory/sentinel.db`) и проксирует в Sentry. |
| **8002** | **Cortex Memory Service** | `services.cortex_memory_service.app` | **Долговременная память и RAG.** Семантический векторный поиск заметок, фактов о пользователе, хранение ежедневного журнала (`memory/cortex.db`). |
| **8003** | **Research Agent Service** | `services.research_agent_service.app` | **Интеллектуальный веб-ресёрч.** Автономный поиск через `gemini-3.6-flash` с отказоустойчивым фолбэком на DuckDuckGo и Wikipedia. Анализ YouTube, сбор новостей. |
| **8004** | **Windows Host Agent** | `services.windows_host_agent.app` | **Аппаратный агент ОС.** Управление окнами, клики мыши, клавиатура (`pyautogui`), запуск приложений, системные метрики (CPU/RAM/GPU), скриншоты экрана. |
| **8000** | **Channel Gateway Service** | `services.channel_gateway_service.app` | **Внешние каналы связи.** Мобильный Remote Web Dashboard, генерация QR-кода сопряжения, Telegram Bot Bridge, RSS-монитор и фоновые триггеры. |
| **8001** | **Brain Orchestrator** | `services.brain_orchestrator.app` | **Ядро интеллекта.** Двусторонний потоковый сокет с **Gemini Live**, диспетчеризация вызовов инструментов (`TOOL_DECLARATIONS`), координация состояния (STANDBY, LISTENING, THINKING, SPEAKING). |
| **8005** | **Audio Stream Service** *(опц.)* | `services.audio_stream_service.app` | **Аудио-драйвер.** Захват микрофона (16 кГц PCM), детектор тишины/речи, воспроизведение ответов модели через динамики. |
| **8007** | **Autonomous Agent Service** | `services.autonomous_agent.app` | **Автономный агент (ReAct Loop).** Реализация автономного исполнителя по паттерну Hermes Agent. Цикл Thought → Action → Observation для многошаговых задач (инструменты ОС, ресёрч, работа с файловой системой, запуск команд). |

---

## 3. Быстрый старт для разработчика

### Шаг 1. Настройка окружения
```bash
# Установка зависимостей
pip install -r requirements.txt
```

### Шаг 2. Конфигурация API ключей
Скопируйте шаблон конфигурации и укажите ваш ключ Google Gemini:
```bash
copy config\api_keys.example.json config\api_keys.json
```
В `config/api_keys.json` укажите:
- `gemini_api_key` — API ключ из [Google AI Studio](https://aistudio.google.com/).
- `sentry_dsn` *(опционально)* — DSN проекта Sentry.

### Шаг 3. Запуск
```bash
# Стандартный запуск всех микросервисов:
python run_microservices.py

# Запуск с графическим тактическим интерфейсом (PyQt6 HUD):
python run_microservices.py --with-ui

# Серверный режим без захвата микрофона (для тестов / CI):
python run_microservices.py --no-audio

# Полностью headless-режим:
python run_microservices.py --no-ui --no-audio
```

---

## 4. Протоколы и соглашения кодовой базы

### Безопасность и Git
- **Никогда не коммитьте `config/api_keys.json`!** Файл надёжно изолирован в `.gitignore`.
- Все приватные ключи, сертификаты, дампы памяти, локальные базы данных (`*.db`, `*.sqlite`), а также временные файлы и логи исключены из репозитория.

### Вызов инструментов (Tool Calling)
Все внешние действия модели вызываются через `services/brain_orchestrator/client_bridge.py`:
- `bridge.open_app(app_name)`
- `bridge.computer_control(*args, **kwargs)`
- `bridge.web_search(query, mode)`
- `bridge.agent_task(task)`
- `bridge.capture_screenshot()`
- `bridge.recall_memory(query, category)`

### Обработка ошибок и Sentry
Каждый микросервис при старте подключает Sentinel:
```python
from shared.error_reporter import install_sentinel
install_sentinel(app, "имя_сервиса")
```
- Все вызовы `sys.stdout` и `sys.stderr` защищены прокси `_SafeStreamProxy`, предотвращающим падение тасок на Windows при обрывах пайпов (`OSError: [Errno 22]`).
- Ошибки исчерпания квот третьих сторон (`429 RESOURCE_EXHAUSTED`) автоматически гасятся и переводят поиск на резервный источник (DuckDuckGo), не загрязняя дашборд Sentry.

---

## 5. Тестирование

Для проверки стабильности системы разработаны автоматические тесты:
```bash
# Сквозной интеграционный тест всех 8 микросервисов (24 проверки):
python scratch/test_microservices_e2e.py

# Тест исправлений Sentry и аргументов инструментов:
python scratch/test_quota_and_computer_control.py
```
