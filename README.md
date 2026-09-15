# AI-Cam Bot — Telegram-бот поиска свободных кабинетов

Бот на `aiogram v3`: ведёт пользователя по FSM-диалогу поиска, отправляет
запрос в Java-сервер и показывает результат. Решение о доступности кабинета
принимают Java и C++ — Telegram-часть отвечает только за UX, валидацию ввода
и форматирование ответа.

Java-сервер живёт в отдельном репозитории: [AI-Cam](https://github.com/qwerwettest/AI-Cam).

## Стек

| | |
|---|---|
| Язык | Python 3.11+ (проверено на 3.14) |
| Telegram | aiogram 3.x, asyncio |
| HTTP-клиент | httpx (таймауты, ретраи, backoff) |
| Конфигурация | pydantic-settings |
| Хранилище | JSON-файл |

## Требования

- Python 3.11 или новее
- Telegram Bot Token от [@BotFather](https://t.me/BotFather)
- Запущенный Java-сервер (AI-Cam) — без него работает только `/start` и `/help`

## Запуск локально

```bash
git clone https://github.com/qwerwettest/AI-Cam-Bot.git && cd AI-Cam-Bot
```

Создайте виртуальное окружение:

```bash
python3 -m venv .venv
```

> На Debian/Ubuntu команда может упасть с `ensurepip is not available` —
> тогда сначала поставьте пакет venv:
> `sudo apt install python3-venv` (или `python3.14-venv` под вашу версию).

Активируйте и поставьте зависимости:

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

На Windows PowerShell активация другая:

```powershell
.\.venv\Scripts\Activate.ps1
```

Заполните конфиг:

```bash
cp .env.example .env
```

Минимально нужно указать `TELEGRAM_BOT_TOKEN` и `JAVA_BASE_URL`.

Запустите:

```bash
python main.py
```

### Docker

```bash
docker build -t ai-cam-bot . && docker run --env-file .env ai-cam-bot
```

## Конфигурация

Все переменные — в [.env.example](.env.example).

| Переменная | Обязательна | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | да | токен бота |
| `JAVA_BASE_URL` | да | адрес Java-сервера, например `http://localhost:3333` |
| `JAVA_API_PATHS` | нет | пути эндпоинтов, по умолчанию `{"bridge":"/api/bridge"}` |
| `JAVA_AUTH_SCHEME` | нет | `none` (по умолчанию), `api_key`, `bearer`, `basic` |
| `JAVA_AUTH_SECRET` | нет | секрет для выбранной схемы |
| `LOCATIONS_LIST` | нет | JSON-список локаций для меню |
| `SEARCH_FILTERS` | нет | варианты длительности и частых времён |
| `ADMIN_TELEGRAM_IDS` | нет | ID админов: `111,222` или `[111,222]` |
| `REQUEST_TIMEOUT_SECONDS` | нет | таймаут запроса к Java, по умолчанию 8 |
| `MAX_RETRIES` | нет | число попыток, по умолчанию 3 |
| `STORAGE_PATH` | нет | файл состояния пользователей |
| `LOG_PATH` / `LOG_LEVEL` | нет | файл и уровень логов |

`id` локаций в `LOCATIONS_LIST` должны совпадать с ключами маппинга
`LOCATION_TO_CORPUS` в Java (`BotBridgeService`): сейчас это `main`, `corp_a`, `corp_b`.

## Команды

| Команда | Описание |
|---|---|
| `/start` | приветствие и быстрый старт |
| `/help` | список команд и примеры |
| `/find` | поиск: локация → этаж → дата → время → длительность → фильтры |
| `/setdefault` | сохранить локацию по умолчанию |
| `/cancel` | отменить текущий сценарий `/find` |
| `/status` | health-check Java API (только админы) |
| `/logs [N]` | последние N строк логов (только админы) |

Кнопки под результатом: `🔄 Обновить` повторяет последний запрос,
`ℹ️ <кабинет>` показывает детали.

## Обмен с Java

Один эндпоинт — `bridge`.

`GET /api/bridge` — health-check, используется командой `/status`:

```json
{
  "status": "ok",
  "service": "schedule-server",
  "cppServer": "configured",
  "pendingCppRequests": 0
}
```

`POST /api/bridge` — поиск кабинетов. Бот отправляет:

```json
{
  "location_id": "main",
  "floor": 2,
  "start_at": "2026-02-17T14:30:00",
  "duration_minutes": 60,
  "requested_by": {
    "telegram_user_id": 123456789
  },
  "filters": {
    "min_capacity": 20,
    "need_projector": true
  }
}
```

Ожидаемый ответ:

```json
{
  "free_rooms": [
    {
      "id": "A-204",
      "name": "A-204",
      "location_id": "main",
      "floor": 2,
      "capacity": 25,
      "schedule_free": true,
      "camera_free": true,
      "camera_status": "online",
      "access_code": "KEY-204"
    }
  ],
  "alternatives": [],
  "reason": ""
}
```

Если данных по камере нет или камера недоступна, бот показывает статус камеры
отдельно и не скрывает результат по расписанию.

## Проверка связки с Java

Убедитесь, что Java-сервер отвечает:

```bash
curl http://localhost:3333/api/bridge
```

Затем отправьте боту `/status` от имени пользователя из `ADMIN_TELEGRAM_IDS`.
При недоступном Java бот вернёт ошибку и запишет детали в `logs/bot.log`.

## Структура

```text
.
├── app
│   ├── bot.py            # сборка Dispatcher, middleware, запуск polling
│   ├── config.py         # Settings на pydantic-settings
│   ├── models.py         # FindRoomQuery -> payload для Java
│   ├── handlers          # common, find (FSM), admin
│   ├── keyboards         # inline-меню
│   ├── services          # java_client (httpx), formatter (HTML-ответы)
│   ├── storage           # user_storage — JSON-файл
│   └── utils             # logging, validation
├── .env.example
├── Dockerfile
├── main.py
└── requirements.txt
```

## Логирование

Structured JSON в stdout и в `logs/bot.log`. Отдельные события для ошибок Java:
`java_api_error`, `java_request_retry_network`, `java_request_retry_status`,
`java_unavailable_after_retries`.

## systemd (опционально)

```ini
[Unit]
Description=AI-Cam Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ai-cam-bot
EnvironmentFile=/opt/ai-cam-bot/.env
ExecStart=/opt/ai-cam-bot/.venv/bin/python /opt/ai-cam-bot/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
