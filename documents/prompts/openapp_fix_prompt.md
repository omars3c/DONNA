# ЗАДАЧА: исправить ложные успехи open_app + научить Sentinel ловить тихие GUI-сбои

## Контекст (проверено вживую, не выдумывай по-другому)

Живой прогон показал:

```
[Brain] Dispatching Tool Call: open_app({'app_name': 'browser'})
[WIN_HOST] [open_app] Launching: 'browser' -> 'browser' (Windows)
[WIN_HOST] INFO: POST /v1/os/launch-app HTTP/1.1" 200 OK
[Brain] Tool Result: Opened browser.
```

При этом на экране всплыл нативный Windows-диалог **"Windows cannot find 'browser'. Make sure you typed the name correctly, and then try again."** — то есть по факту ничего не открылось, но вся цепочка (open_app → windows_host_agent → brain) отчиталась об успехе.

Корневые причины (все три нужно исправить, они независимые):

1. `services/windows_host_agent/app.py`, эндпоинт `POST /v1/os/launch-app` — **всегда** возвращает `GenericResponse(success=True, ...)` независимо от того, что реально вернул `open_app()`.
2. `actions/open_app.py`, функция `_launch_windows()` — считает `subprocess.Popen(f'start "" "{app_name}"', shell=True)` успехом, если `Popen` не бросил исключение. Но `start` — это встроенная команда cmd.exe, она почти никогда не бросает исключение из Python, даже когда сама не может найти приложение — вместо этого она показывает GUI `MessageBox` и остаётся висеть до закрытия диалога пользователем.
3. `_normalize()` в том же файле делает только транслитерацию RU→latin (например «хром» → «hrom»), но не переводит **смысловые категории** вроде "browser" / "браузер" в конкретное приложение. Для конкретных названий программ (Chrome, Telegram, Notepad) `start` обычно резолвит через Windows App Paths / PATH и работает. Для общих категорий — нет.

Так как в проекте уже есть `sentinel_service` (порт 8006) с клиентской библиотекой `shared/error_reporter.py` (функции `init_reporter`, `report`, `report_exception`, `install_sentinel`) — используй её, не изобретай параллельный механизм логирования.

---

## Часть 1 — actions/open_app.py: перестать врать об успехе

### 1.1. Резолвинг обобщённых категорий (browser, email, файловый менеджер)

Добавь функцию `_resolve_generic_category(name: str) -> str | None`, которая по **нормализованному в нижний регистр** имени (проверяй и исходное, и транслитерированное — "browser", "браузер"/"brauzer" должны совпасть) резолвит несколько самых частых обобщённых запросов через реестр Windows, а не через статичный список программ:

- `"browser"` / `"браузер"` → прочитать дефолтный браузер из реестра:
  `HKEY_CURRENT_USER\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice`, ключ `ProgId`, затем достать команду запуска из `HKEY_CLASSES_ROOT\{ProgId}\shell\open\command` (модулем `winreg`). Верни путь к exe, извлечённый из command-строки.
- `"почта"` / `"email"` / `"mail"` → аналогично, но через `UrlAssociations\mailto\UserChoice`.
- `"проводник"` / `"file manager"` / `"explorer"` → просто `"explorer.exe"` (это системная константа, не эвристика, её можно захардкодить).

Если резолвинг не удался (ключа нет, ProgId не резолвится) — верни `None`, дальше идёт обычный путь как раньше. Это не должно ломать резолвинг конкретных названий приложений типа "Chrome" или "Telegram" — только обобщённые категории.

### 1.2. Различать «подтверждённый» и «неподтверждённый» запуск

Сейчас `_launch_windows` возвращает `bool`. Замени на возврат структуры (namedtuple/dataclass) `LaunchResult(ok: bool, confirmed: bool, detail: str)`:

- **confirmed=True** — путь к исполняемому файлу был реально резолвлен (через `_resolve_generic_category`, через `shutil.which`, через прямое существование пути) и запущен через `subprocess.Popen([path, ...])` или `os.startfile(path)` — оба этих вызова **бросают** `FileNotFoundError`/`OSError`, если файла нет, так что если исключения не было — запуск реально произошёл.
- **confirmed=False** — использован fallback через `start "" "{app_name}"` вслепую, без резолвинга пути. Это не значит «не открылось», это значит «не можем утверждать, что открылось».

Порядок попыток в `_launch_windows`, от самого надёжного к самому слабому:
1. `_resolve_generic_category(app_name)` → если получили путь, `os.startfile(path)` → `confirmed=True` при успехе.
2. `shutil.which(app_name)` или `shutil.which(app_name.split(".")[0])` → если нашли, `subprocess.Popen([binary])` → `confirmed=True`.
3. Текущий fallback `start "" "{app_name}"` → `confirmed=False` при отсутствии исключения (это остаётся как последний резерв для длинных путей и вещей, которые резолвит только shell).

### 1.3. Изменить сообщение и что уходит в Sentinel

В `open_app()`:
- confirmed успех → как сейчас, `f"Opened {app_name}."`.
- **confirmed=False** (сработал только шаг 3) → верни `f"Started a launch attempt for {app_name}, but could not confirm it opened."` **и** вызови `report(severity="WARNING", source="open_app", message=f"Unconfirmed launch: {app_name}", context={"app_name": app_name, "normalized": normalized})` из `shared.error_reporter` — чтобы это было видно в Sentinel как WARNING, а не проваливалось молча.
- Полный провал (ничего не сработало) — как сейчас, но тоже `report(severity="ERROR", ...)`.

### 1.4. Часть 2 подключается сюда же (см. ниже)

Когда сработал именно шаг 3 (`confirmed=False`), запусти проверку на всплывший диалог-ошибку — см. раздел «Часть 2». Если диалог обнаружен в течение окна ожидания — апгрейдни это из WARNING в **ERROR** с текстом самого диалога в `message`, и поменяй финальный текст ответа на `f"Failed to open {app_name}: {dialog_text}"`.

---

## Часть 2 — windows_host_agent: детектор тихих GUI-диалогов

GUI `MessageBox` не пишет в stdout/stderr и не бросает исключений в Python — единственный способ его увидеть программно — опросить открытые окна ОС через `pywin32` (`win32gui`, `win32process`). Он уже тянется в проект транзитивно через `pywinauto` (см. `requirements.txt`), так что новую тяжёлую зависимость добавлять не нужно — но явно добавь `pywin32; sys_platform == "win32"` в `requirements.txt`, если его там нет напрямую (транзитивная зависимость может однажды перестать её тянуть).

### 2.1. Новый модуль `actions/dialog_watchdog.py`

```python
def watch_for_dialog(timeout_sec: float = 2.0, poll_interval: float = 0.2) -> str | None:
    """
    Опрашивает список top-level окон в течение timeout_sec.
    Ищет новое окно с классом "#32770" (стандартный Windows MessageBox)
    и непустым заголовком/текстом, появившееся ПОСЛЕ вызова этой функции
    (сравнивай снимок HWND "до" и "после", а не просто наличие — такие окна
    иногда уже висят от предыдущих запусков).
    Возвращает текст диалога (заголовок + текст первого статического
    control'а внутри), либо None, если ничего не появилось за timeout_sec.
    Не поднимает исключений наружу — оборачивай в try/except и возвращай None
    при любой ошибке win32-вызовов (например, если pywin32 недоступен —
    это не должно ронять open_app).
    """
```

Реализация через `win32gui.EnumWindows` + `win32gui.GetClassName` + `win32gui.GetWindowText`, для текста внутри диалога — `win32gui.EnumChildWindows` по найденному HWND и `GetWindowText` первого child с классом `"Static"`.

**Опционально** (не обязательно, но полезно, чтобы диалоги не копились и не блокировали будущие попытки): если диалог найден и мы уверены, что это именно наш — закрыть его через `win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)`. Сделай это управляемым флагом `auto_dismiss: bool = True` в `watch_for_dialog`, чтобы можно было выключить одной строкой, если начнёт закрывать что-то не то.

### 2.2. Встраивание в open_app

В `open_app()`, сразу после fallback-варианта из шага 3 (`confirmed=False`, то есть после `subprocess.Popen('start "" ...', shell=True)`):

```python
dialog_text = watch_for_dialog(timeout_sec=2.0)
if dialog_text:
    report(severity="ERROR", source="open_app_dialog_detect", message=dialog_text,
           context={"app_name": app_name, "normalized": normalized})
    return f"Failed to open {app_name}: {dialog_text}"
```

Это добавит **~2 секунды задержки** только на неподтверждённый путь запуска (шаги 1 и 2 её не получают, они и так подтверждены). Если это неприемлемо по отзывчивости голосового ассистента — сократи `timeout_sec` до 1.0–1.2 и явно скажи об этом в отчёте, не изменяй тихо.

### 2.3. Обобщи детектор на другие OS-действия windows_host_agent

Диалоги «не могу найти файл / нет доступа / приложение не отвечает» — не уникальная проблема `open_app`. Проверь, есть ли похожий риск в `actions/computer_control.py` и `actions/computer_settings.py` (там, где тоже запускаются внешние процессы или системные диалоги настроек) — если да, подключи туда `watch_for_dialog` по той же схеме. Если таких мест нет — явно напиши в отчёте, что проверил и не нашёл, а не пропускай молча.

---

## Часть 3 — services/windows_host_agent/app.py: перестать хардкодить success=True

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

Проверь текстовые префиксы на точное соответствие тому, что реально возвращает обновлённый `open_app()` после твоих правок в Части 1 — не копируй эту строку слепо, если поменяешь формулировки сообщений.

---

## Требования к качеству

1. **Ничего не должно ломать существующие успешные запуски.** Конкретные названия приложений (Chrome, Telegram, Notepad, VS Code), которые сейчас открываются нормально через `start`, обязаны продолжать открываться так же — не проверяй их через реестр UrlAssociations, эта логика только для обобщённых категорий из 1.1.
2. **watch_for_dialog не должен ронять open_app**, если `pywin32` не установлен или недоступен (например, на машине без Windows GUI-сессии, Session 0 isolation — та же проблема, что уже известна для screenshot). Оборачивай импорт `win32gui`/`win32con` в try/except на уровне модуля, и если недоступен — `watch_for_dialog` сразу возвращает `None`, без ошибки.
3. **Не спамь Sentinel.** Один вызов `open_app` = максимум один `report()`. Не логируй промежуточные шаги резолвинга.
4. **Не ломай существующий формат `ErrorReport`** из `shared/models/sentinel.py` — используй `report()` из `shared/error_reporter.py` как есть, не создавай новый способ отправки ошибок в обход него.
5. Русские сообщения в `dialog_text` должны доходить до Sentinel без кракозябр (кодировка UTF-8 на всех уровнках — уже реализовано в sentinel_service, просто не сломай на этом конце).

---

## Как проверить, что готово

1. Голосом или через `Invoke-RestMethod -Method Post http://localhost:8004/v1/os/launch-app -Body '{"app_name":"browser"}' -ContentType "application/json"` → должен открыться реальный дефолтный браузер (не диалог с ошибкой), ответ `success=true`, `message` начинается с `"Opened"`.
2. То же самое с `app_name="некоторая-заведомо-несуществующая-чепуха-12345"` → должен появиться и корректно закрыться (или остаться, если auto_dismiss=False) Windows-диалог, `success=false`, `message` содержит текст реального диалога, и в Sentinel (`http://localhost:8006`) появляется ERROR с source `open_app_dialog_detect`.
3. Открыть конкретное установленное приложение (например "Telegram" или "Chrome") → продолжает работать как раньше, без двухсекундной задержки (проходит по шагу 1 или 2, не 3).
4. Проверить, что `.\run.ps1 health` и `.\run.ps1 all` по-прежнему поднимают все 7 сервисов без изменений в поведении остальных.
5. Явно перечисли в отчёте: какие названия приложений ты тестировал живьём и какой путь резолвинга (1/2/3) сработал для каждого.

Работай в отдельной ветке (например `fix/open-app-false-success`), не в `feature/sentinel-service` и не в `main`. В конце — краткий отчёт: что изменено, что проверено вживую, что не удалось проверить и почему.
