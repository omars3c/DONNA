# D.O.N.N.A. — Desktop Operative Neural Network Assistant

[![Architecture: Microservices](https://img.shields.io/badge/Architecture-8%20Pure%20Microservices-blue.svg)](ARCHITECTURE.md)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-green.svg)](https://python.org)
[![Package Manager: uv](https://img.shields.io/badge/Package%20Manager-uv%20(Fast%20%26%20Locked)-blueviolet.svg)](https://github.com/astral-sh/uv)
[![Security: Human--in--the--Loop](https://img.shields.io/badge/Security-Human--in--the--Loop%20(Сэр)-red.svg)](#-кибербезопасность-и-протокол-human-in-the-loop)
[![Memory: Cortex 3072D](https://img.shields.io/badge/Memory-Cortex%203072D%20WAL-cyan.svg)](#-архитектура-микросервисов-80008007)
[![Observability: Sentinel & Sentry](https://img.shields.io/badge/Monitoring-Sentinel%20%2B%20Sentry-orange.svg)](#-мониторинг-и-наблюдаемость)
[![Tools: 17 Rigorous](https://img.shields.io/badge/Tools-17%20Strict%20Contracts-purple.svg)](#-реестр-17-инструментов-gemini-live)

D.O.N.N.A. — это тактический персональный голосовой ИИ-ассистент оперативного класса (уровня J.A.R.V.I.S.) с распределённой микросервисной архитектурой, полнодуплексным голосовым интерфейсом реального времени (**Gemini Live WebSocket**), 3072-мерной векторной памятью (**Cortex SQLite WAL**), нативным управлением Windows 11, автономным ReAct-агентом решения инженерных задач и двойным тактическим интерфейсом (PyQt6 Desktop + React 19 Web HUD).

---

## 🚀 Быстрый старт (с использованием `uv`)

Проект стандартизирован на пакетном менеджере **`uv`**. Вам больше не нужно вручную активировать виртуальное окружение: `uv` автоматически создает и синхронизирует изолированное окружение `.venv` на лету.

### 1. Клонирование и установка зависимостей
```powershell
git clone https://github.com/omars3c/DONNA.git
cd DONNA

# Установка uv (если еще не установлен на машине):
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Мгновенная синхронизация 100% зависимостей по uv.lock:
uv sync
```

*(Для традиционного запуска через `pip` также сохранен `requirements.txt`: `python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt`).*

### 2. Настройка конфигурации и API ключей
```powershell
copy config\api_keys.example.json config\api_keys.json
```
Откройте `config/api_keys.json` и укажите ваш ключ `gemini_api_key` из [Google AI Studio](https://aistudio.google.com/).  
*(Опционально: добавьте резервные ключи в `gemini_backup_keys` для автоматической ротации пула моделей при превышении лимитов 429/503).*

### 3. Запуск системы
```powershell
# Стандартный запуск всех 8 микросервисов:
uv run python run_microservices.py

# С нативным тактическим оверлеем (PyQt6 Desktop HUD):
uv run python run_microservices.py --with-ui

# Headless / Серверный режим (без микрофона и динамиков):
uv run python run_microservices.py --no-audio

# Фоновый режим (без UI и без аудио):
uv run python run_microservices.py --no-ui --no-audio
```

---

## 🖥️ Пользовательские интерфейсы (HUD)

1. **React Tactical Web HUD**:
   - Современный киберпанк-интерфейс на React 19, Vite и Tailwind CSS.
   - Доступен по адресу: **`http://127.0.0.1:8000/hud`** (на основном мониторе или планшете в локальной сети).
   - Прямой WebSocket-мост к шине событий, интерактивный ввод текста и терминал логов.
2. **PyQt6 Desktop Tactical HUD**:
   - Нативный полупрозрачный голографический оверлей на рабочем столе Windows с анимацией радара, звукового спектра и мониторингом железа.
   - Запуск: `uv run python run_microservices.py --with-ui`.
3. **Mobile Remote Dashboard & Telegram Bot**:
   - Мобильный пульт управления на порту `8000` с авторизацией по QR-коду и OTP-сопряжением (`/pair <OTP>`).

---

## 🏗️ Архитектура микросервисов (`:8000`–`:8007`)

Система состоит из 8 независимых изолированных микросервисов под управлением супервизора `run_microservices.py`:

| Порт | Микросервис | Модуль запуска | Ключевая роль |
| :--- | :--- | :--- | :--- |
| **8006** | **Sentinel Service** | `services.sentinel_service.app` | **Сторож и телеметрия.** Стартует первым. Дедупликация логов, Sentry reporter, хранение крэшей в SQLite WAL. |
| **8002** | **Cortex Memory Service** | `services.cortex_memory_service.app` | **Долговременная память.** 3072D векторные эмбеддинги (`models/gemini-embedding-2`) + оффлайн SHA-256 fallback. База SQLite WAL. |
| **8003** | **Research Agent Service** | `services.research_agent_service.app` | **Глубокий ресёрч.** Поиск с верификацией фактов, генерация документов Word (.docx), PDF и схем Mermaid. |
| **8004** | **Windows Host Agent** | `services.windows_host_agent.app` | **Управление хостом Windows.** Резолвер приложений (.lnk, Registry, PATH), Playwright, Планировщик задач, метрики psutil. |
| **8000** | **Channel Gateway Service** | `services.channel_gateway_service.app` | **Входной шлюз.** Хостинг React Web HUD (`/hud`), Telegram Bot Gateway, OTP-авторизация, Cron-планировщик. |
| **8001** | **Brain Orchestrator** | `services.brain_orchestrator.app` | **Когнитивное ядро.** Полнодуплексный Gemini Live WebSocket, LiveConnectConfig (Ru-RU / Kore Voice), агрегатор контекста. |
| **8005** | **Audio Stream Service** | `services.audio_stream_service.app` | **Аудио-драйвер.** SoundDevice 16 кГц PCM микрофон, 24 кГц вывод речи, VAD (детектор активности голоса). |
| **8007** | **Autonomous Agent Service** | `services.autonomous_agent.app` | **ReAct Инженерный агент.** Автономное решение задач, написание кода, генерация диффов, безопасный терминальный сэндбокс. |

Подробное описание архитектуры, схема взаимодействия и протоколы описаны в [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 🛡️ Кибербезопасность и протокол Human-in-the-Loop

D.O.N.N.A. разработана с прицелом на строгую кибербезопасность:
* **Обращение «Сэр»**: Единственный легитимный источник команд и авторизации.
* **Принцип разделения привилегий**:
  * *Чтение, аудит, поиск уязвимостей, подготовка диффов* — выполняются проактивно и автономно.
  * *Исполнение shell-команд, запись файлов, модификация кода, правка реестра ОС* — **строго заблокированы до прямого подтверждения Сэра**.
* **Anti-Prompt-Injection**: Все внешние данные (парсинг веб-страниц, ответы поисковиков, содержимое файлов) изолируются в контейнерах `<UNTRUSTED EXTERNAL DATA>` и не могут переопределить системный протокол.
* **Межсервисный токен (`X-Donna-Internal-Token`)**: Все внутренние REST-запросы между микросервисами проверяются криптографическим токеном.
* **Белый список CORS**: Полный запрет `*` в пользу доверенных локальных портов.
* **Защита спаривания Telegram**: Авторизация по одноразовому 6-значному OTP-коду.

---

## 🛠️ Реестр 17 инструментов Gemini Live

Ядро оркестрации оперирует строго типизированным реестром из 17 инструментов (без дубликатов):
1. `screen_process` — Захват экрана и анализ видеопотока.
2. `open_app` — Безопасный запуск программ через нативный Win32 App Resolver.
3. `web_search` — Быстрый поиск фактов и информации.
4. `deep_research_report` — Генерация глубоких аналитических отчетов Word/PDF.
5. `agent_task` — Передача многошаговой задачи автономному ReAct-агенту.
6. `autonomous_task` — Алиас для инженерного агента.
7. `recall_memory` — Поиск по 3072D векторной семантической памяти Cortex.
8. `save_knowledge` — Сохранение фактов и заметок в базу знаний.
9. `manage_cortex_tasks` — Управление жизненным циклом задач.
10. `log_journal` — Запись в хронологический дневник событий.
11. `computer_control` — Точное управление клавиатурой, кликами и скроллом.
12. `computer_settings` — Управление звуком, яркостью, сетью и окнами.
13. `system_status` — Аппаратный мониторинг CPU/RAM/GPU (psutil).
14. `browser_control` — Управление вкладками и DOM браузеров.
15. `reminder` — Долговечные напоминания через Планировщик Windows.
16. `youtube_video` — Поиск и извлечение субтитров YouTube.
17. `openclaw_skill` — Динамический вызов любого из 51 навыка OpenClaw через Tool RAG.

---

## 🧪 Тестирование и диагностика

Все тесты запускаются изолированно через `uv run`:

```powershell
# 1. Смоук-тест импортов всех 12 микросервисов и модулей:
uv run python scripts/smoke_test.py

# 2. Полный тестовый пакет архитектурных контрактов (8/8 тестов):
uv run pytest tests/test_jarvis_core.py -v
```
