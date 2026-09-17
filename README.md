# D.O.N.N.A. — Desktop Operative Neural Network Assistant

[![Architecture: Microservices](https://img.shields.io/badge/Architecture-8%20Pure%20Microservices-blue.svg)](architecture.md)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-green.svg)](https://python.org)
[![Security: Hardened](https://img.shields.io/badge/Security-Hardened%20Tokens%20%26%20CORS-brightgreen.svg)](#security)
[![Observability: Sentry & Sentinel](https://img.shields.io/badge/Monitoring-Sentinel%20%2B%20Sentry-orange.svg)](#monitoring)
[![Tools: 17 Registered](https://img.shields.io/badge/Tools-17%20Gemini%20Live%20Tools-purple.svg)](#tools)

D.O.N.N.A. — это передовой персональный голосовой ИИ-ассистент оперативного класса с распределённой микросервисной архитектурой, двусторонним голосовым интерфейсом реального времени (**Gemini Live WebSocket**), векторной долговременной памятью (**Cortex SQLite WAL**), нативным управлением Windows, автономным ReAct-агентом решения инженерных задач и двойным тактическим интерфейсом (PyQt6 Desktop + React 19 Web HUD).

---

## 🚀 Быстрый старт

### 1. Установка зависимостей
```bash
git clone https://github.com/omars3c/DONNA.git
cd DONNA
python setup.py
```

### 2. Настройка ключей
```bash
copy config\api_keys.example.json config\api_keys.json
```
Откройте `config/api_keys.json` и укажите ваш `gemini_api_key` из [Google AI Studio](https://aistudio.google.com/).

### 3. Запуск системы
```bash
# Запуск единого микросервисного оркестратора:
python run_microservices.py

# С нативным тактическим оверлеем (PyQt6 Desktop HUD):
python run_microservices.py --with-ui

# Headless / Серверный режим (без захвата аудио):
python run_microservices.py --no-ui --no-audio
```

---

## 🖥️ Пользовательские интерфейсы (HUD)

1. **PyQt6 Desktop Tactical HUD**:
   - Нативный голографический оверлей на рабочем столе Windows с анимацией радара, аудио-спектра и виджетом статуса системы.
   - Запуск: `python run_microservices.py --with-ui`.
2. **React Tactical Web HUD**:
   - Современный браузерный интерфейс (React 19, Vite, Tailwind CSS).
   - Доступен по адресу: **`http://127.0.0.1:8000/hud`** (на основном мониторе, планшете или втором экране в локальной сети).
   - Подключается напрямую к потоку событий `ws://127.0.0.1:8001/ws/hud` и поддерживает интерактивный ввод команд.
3. **Mobile Remote Dashboard**:
   - Мобильный веб-пульт управления на порту `8000` с авторизацией по QR-коду и безопасной передачей команд на хост.

---

## 🏗️ Архитектура микросервисов

Система функционирует как 8 изолированных микросервисов под управлением `run_microservices.py`:
* **Sentinel Service (`:8006`)** — Централизованный сбор телеметрии, дедупликация ошибок и интеграция с Sentry.
* **Cortex Memory Service (`:8002`)** — Семантическая векторная память, долгосрочные заметки и база знаний **SQLite WAL**.
* **Research Agent Service (`:8003`)** — Автономный ресёрч, создание отчётов Word (.docx) и PDF, анализ YouTube.
* **Windows Host Agent (`:8004`)** — Автоматизация ОС: запуск приложений, эмуляция клавиатуры/мыши, снятие скриншотов, метрики ПК, планировщик задач Windows (`reminder`), управление браузерами (`browser_control`).
* **Channel Gateway Service (`:8000`)** — Мобильный веб-дашборд, React Tactical HUD (`/hud`), Telegram-мост, генерация QR-кода, планировщик Cron.
* **Brain Orchestrator (`:8001`)** — Ядро интеллекта: полнодуплексная аудио-сессия с Google Gemini Live, диспетчер 17 инструментов.
* **Audio Stream Service (`:8005`)** — Фоновый сервис захвата микрофона (Vosk wake word) и воспроизведения речи (24 кГц).
* **Autonomous Agent Service (`:8007`)** — Автономный инженерный ReAct-агент для многошагового решения задач, выполнения кода и терминальных команд.

Подробная архитектурная спецификация приведена в [architecture.md](architecture.md).

---

## 🔒 Безопасность

* **Межсервисные токены**: Все внутренние HTTP-вызовы защищены токеном `X-Donna-Internal-Token`, генерируемым супервизором на каждый запуск.
* **Строгий CORS**: Полный отказ от `*` в пользу белого списка доверенных локальных источников.
* **Безопасность запуска**: Устранена возможность RCE в `open_app` (нативный `os.startfile` без шелл-инъекций).
* **Защита спаривания Telegram**: Требуется ввод одноразового 6-значного OTP-кода (`/pair <OTP>`).
* **Файловая безопасность**: Исполняемые файлы (`.exe`, `.bat`, `.ps1`) защитно суффиксируются `.download`.

---

## 🧪 Тестирование
```bash
# Тесты безопасности и контрактов:
python scratch/test_security_and_contracts.py

# Тесты реестра 17 инструментов:
python scratch/test_phase4_tools.py

# Тесты отказоустойчивости и защиты БД:
python scratch/test_phase2_guards.py

# Сквозной тест всех микросервисов (24 проверки):
python scratch/test_microservices_e2e.py
```
