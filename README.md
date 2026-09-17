# D.O.N.N.A. — Desktop Operative Neural Network Assistant

[![Architecture: Microservices](https://img.shields.io/badge/Architecture-Pure%20Microservices-blue.svg)](ARCHITECTURE.md)
[![Python: 3.12 | 3.14](https://img.shields.io/badge/Python-3.12%20%7C%203.14-green.svg)](https://python.org)
[![Security: Hardened](https://img.shields.io/badge/Security-Hardened%20.gitignore-brightgreen.svg)](#security)
[![Observability: Sentry & Sentinel](https://img.shields.io/badge/Monitoring-Sentinel%20%2B%20Sentry-orange.svg)](#monitoring)

D.O.N.N.A. — это передовой персональный голосовой ИИ-ассистент оперативного класса с распределённой микросервисной архитектурой, двусторонним голосовым интерфейсом реального времени (Gemini Live WebSocket), векторной памятью (Cortex), управлением рабочим столом Windows и автономными исследовательскими агентами.

---

## 🚀 Быстрый старт

### 1. Установка
```bash
git clone https://github.com/omars3c/DONNA.git
cd DONNA
pip install -r requirements.txt
```

### 2. Настройка ключей
```bash
copy config\api_keys.example.json config\api_keys.json
```
Откройте `config/api_keys.json` и вставьте ваш ключ `gemini_api_key`.

### 3. Запуск системы
```bash
# Запуск единого микросервисного оркестратора:
python run_microservices.py

# С тактическим визуальным интерфейсом (PyQt6 Tactical HUD):
python run_microservices.py --with-ui

# Headless / Серверный режим:
python run_microservices.py --no-ui
```

---

## 🏗️ Архитектура системы

Проект работает на **чистых микросервисах**:
* **Sentinel Service (`:8006`)** — Централизованный сбор телеметрии, дедупликация ошибок и интеграция с Sentry.
* **Cortex Memory Service (`:8002`)** — Семантическая векторная память, долгосрочные заметки и база знаний SQLite.
* **Research Agent Service (`:8003`)** — Автономный ресёрч (`gemini-3.6-flash` + DuckDuckGo), Playwright скрейпинг, анализ YouTube.
* **Windows Host Agent (`:8004`)** — Автоматизация ОС: запуск приложений, эмуляция клавиатуры/мыши, снятие скриншотов, метрики ПК.
* **Channel Gateway Service (`:8000`)** — Мобильный веб-дашборд, Telegram-мост, генерация QR-кода, планировщик Cron.
* **Brain Orchestrator (`:8001`)** — Ядро интеллекта: полнодуплексная аудио-сессия с Google Gemini Live, вызов инструментов.
* **Audio Stream Service (`:8005`)** — Фоновый сервис захвата микрофона и воспроизведения речи.
* **Autonomous Agent Service (`:8007`)** — Фоновый автономный агент (ReAct Loop) для решения сложных многошаговых задач (исследования, автоматизация ОС, работа с файлами).

Подробное руководство по архитектуре доступно в [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 🔒 Безопасность

* Репозиторий защищён конфигурацией `.gitignore`: реальные API-ключи, токены, сессионные базы данных и логи **никогда не попадают в систему контроля версий**.
* Для настройки используется безопасный шаблон `config/api_keys.example.json`.

---

## 🧪 Тестирование
```bash
# Запуск полного сквозного набора тестов (24 теста):
python scratch/test_microservices_e2e.py
```
