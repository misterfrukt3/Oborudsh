# Оборудыш: запуск Mini App в Telegram и деплой

## Что добавляет релиз 16.07.2026

- Автоматическая миграция создаёт паспорта `equipment_units` и поля `issued_by`/`returned_by`; базу сбрасывать не нужно.
- Перенести также `bot/texts.py`, `prototype/texts.js` и всю папку `prototype/fonts/`.
- Caddy должен пропускать SSE без буферизации и использовать `encode zstd gzip`.
- После первого запуска проверить паспорт экземпляра, недельный календарь и `/api/events`.
- Google Sheets сначала оставить выключенным (`GOOGLE_SHEETS_ENABLED=0`), затем включить и выполнить `/scoresync`.


## Главное: как обновить уже работающего Оборудыша на VPS

Ниже — порядок для текущей схемы: один каталог `/opt/oborudka`, один сервис `oborudka.service`, одна база `bot/oborudka.db` и один боевой бот.

### Что подготовить на компьютере

Для этого обновления на сервер нужно перенести:

- `bot/main.py`;
- `bot/requirements.txt`;
- `prototype/index.html`;
- `prototype/style.css`;
- всю папку `prototype/fonts/`;
- `prototype/catalog.js`, если серверная копия отличается от локальной.

Настоящий `bot/.env` и локальную `bot/oborudka.db` на сервер не копировать. На VPS остаются его собственные `.env` и база.

### 1. Подключиться к VPS и остановить бота

```bash
ssh ИМЯ_ПОЛЬЗОВАТЕЛЯ@IP_СЕРВЕРА
sudo systemctl stop oborudka
```

Проверьте, что сервис действительно остановлен:

```bash
sudo systemctl status oborudka
```

Нормальное состояние перед обновлением — `inactive (dead)`.

### 2. Обязательно сохранить текущую версию и базу

```bash
cd /opt/oborudka
stamp=$(date +%Y%m%d-%H%M%S)
sudo mkdir -p /opt/oborudka-backups/$stamp
sudo cp bot/oborudka.db /opt/oborudka-backups/$stamp/oborudka.db
sudo cp bot/main.py bot/requirements.txt /opt/oborudka-backups/$stamp/
sudo cp -a prototype /opt/oborudka-backups/$stamp/prototype
echo "Резервная копия: /opt/oborudka-backups/$stamp"
```

Не удаляйте `bot/oborudka.db`: в ней находятся пользователи, заявки, переписки и очередь начислений.

### 3. Перенести новые файлы

Если проект на VPS подключён к Git и изменения уже опубликованы:

```bash
cd /opt/oborudka
git pull
```

Если файлы загружаются вручную через WinSCP/SFTP, замените их по тем же путям внутри `/opt/oborudka`. Папку `prototype/fonts/` переносите целиком.

После копирования проверьте наличие основных файлов:

```bash
cd /opt/oborudka
ls -l bot/main.py bot/requirements.txt prototype/index.html prototype/style.css
ls -l prototype/fonts/
```

### 4. Обновить отдельное Python-окружение Оборудыша

Команда ниже обновляет только окружение Оборудыша. Python и библиотеки остальных ботов она не меняет.

```bash
cd /opt/oborudka
bot/venv/bin/python -m pip install --upgrade pip
bot/venv/bin/pip install -r bot/requirements.txt
bot/venv/bin/python --version
```

Нужен Python 3.10 или новее. Если `bot/venv` ещё не существует, сначала создайте его отдельным Python 3.10+:

```bash
cd /opt/oborudka
python3.10 -m venv bot/venv
bot/venv/bin/pip install -r bot/requirements.txt
```

Системный `/usr/bin/python3` не заменять.

### 5. Дописать новые настройки в серверный `.env`

Откройте существующий файл:

```bash
sudo nano /opt/oborudka/bot/.env
```

Добавьте отсутствующие строки:

```dotenv
ENABLE_PRODUCTION_ROLE=0

GOOGLE_SHEETS_ENABLED=0
GOOGLE_SHEET_ID=
GOOGLE_SERVICE_ACCOUNT_JSON_B64=
GOOGLE_SHEET_EVENTS_TAB=Начисления
GOOGLE_SHEET_SUMMARY_TAB=Админы

SCORE_DAILY_ADMIN=0.1
SCORE_REQUEST=0.01
SCORE_626=0.05
```

Сначала оставьте `GOOGLE_SHEETS_ENABLED=0`. Бот запустится штатно, а начисления будут сохраняться в локальной очереди. После настройки таблицы заполните Google-реквизиты, поставьте `GOOGLE_SHEETS_ENABLED=1` и перезапустите сервис.

`DEV_USER_ID` на VPS не задавать. `ENABLE_PRODUCTION_ROLE=0` оставляет production скрытым; для будущего возврата роли поставьте `1` и перезапустите бота.

### 6. Запустить обновлённого бота

```bash
sudo systemctl start oborudka
sudo systemctl status oborudka
```

Если статус `active (running)`, посмотрите последние логи:

```bash
sudo journalctl -u oborudka -n 100 --no-pager
```

В логах не должно быть traceback, ошибок импорта или сообщений о неверном `.env`.

### 7. Что проверить после обновления

1. Открывается Mini App и не висит на загрузке.
2. В регистрации нет роли production.
3. Пользователь видит каталог и может создать заявку.
4. Администратор может взять, согласовать, выдать и принять заявку.
5. Работает бронь и закрытие 626.
6. Старшему отвечает `/scorestatus`.
7. После включения Google команда `/scoresync` отправляет накопленные начисления.
8. `/digest` отправляет оформленную статистику в канал.

### Если бот не запустился: быстрый откат

Посмотрите имя последней резервной папки:

```bash
ls -lt /opt/oborudka-backups
```

Затем подставьте её имя вместо `ИМЯ_КОПИИ`:

```bash
sudo systemctl stop oborudka
cd /opt/oborudka
sudo cp /opt/oborudka-backups/ИМЯ_КОПИИ/oborudka.db bot/oborudka.db
sudo cp /opt/oborudka-backups/ИМЯ_КОПИИ/main.py bot/main.py
sudo cp /opt/oborudka-backups/ИМЯ_КОПИИ/requirements.txt bot/requirements.txt
sudo mv prototype "prototype.failed-$(date +%Y%m%d-%H%M%S)"
sudo cp -a /opt/oborudka-backups/ИМЯ_КОПИИ/prototype ./prototype
bot/venv/bin/pip install -r bot/requirements.txt
sudo systemctl start oborudka
sudo systemctl status oborudka
```

После изменения `main.py`, `.env` или зависимостей сервис нужно перезапускать. Если менялись только `prototype/index.html`, `style.css`, `catalog.js`, картинки или шрифты, перезапуск обычно не нужен.

## Как Mini App подключается к Telegram (коротко)

Mini App — обычный сайт по **HTTPS**, который Telegram открывает внутри чата. Подключение состоит из трёх вещей:

1. **Бот** — создаётся у [@BotFather](https://t.me/BotFather) командой `/newbot`. Он выдаёт токен.
2. **HTTPS-адрес приложения** — Telegram не открывает `http://localhost`, нужен либо туннель (для разработки), либо домен на сервере.
3. **Точка входа** — как пользователь открывает приложение:
   - **кнопка меню чата** (слева от поля ввода) — наш бот ставит её сам при старте (`set_chat_menu_button`); вручную это делается в BotFather: `/mybots` → бот → *Bot Settings* → *Menu Button* → указать URL;
   - **inline-кнопка в сообщении** — бот шлёт её в ответ на `/start`.

Авторизация: Telegram сам передаёт приложению `initData` (ID, ник, аватар, подпись) — логины и пароли не нужны. Сервер проверяет подпись `initData` перед каждым API-запросом.

> ⚠️ **Токены.** Боевой токен из `main.py`/`bot_fixed.py` скомпрометирован — отозвать через BotFather (`/mybots` → бот → *API Token* → *Revoke*). Для тестов — отдельный тестовый бот. Токен живёт только в `bot/.env`, который не попадает в git.

---

## Вариант А — локально на Windows (для тестов, начать с этого)

### 1. Установить Python и cloudflared (один раз)

```powershell
winget install Python.Python.3.12
winget install Cloudflare.cloudflared
```

После установки закрыть и открыть терминал заново (чтобы обновился PATH).

### 2. Поставить зависимости (один раз)

```powershell
cd "D:\Media BMSTU\Оборудыш\bot"
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

### 3. Настроить .env (один раз)

```powershell
copy .env.example .env
notepad .env
```

Вписать:
- `BOT_TOKEN` — токен тестового бота;
- `WEBAPP_URL` — на следующем шаге (туннель);
- `ADMIN_IDS` / `SENIOR_ADMIN_IDS` — Telegram ID через запятую. Свой ID: написать боту `/chatid` в личку (или @userinfobot). **Без этого панели админа в приложении никому не видны**;
- `ADMIN_CHAT_ID` — группа, куда падают карточки заявок: создать группу, добавить бота, написать в ней `/chatid@имябота`, вписать число (с минусом).
- `MB_SHEET_URL` (необязательно) — автосверка Media BMSTU при регистрации. В Google-таблице участников: лист «список ребят» → Файл → «Публикация в интернете» → выбрать лист, формат **CSV** → скопировать ссылку сюда. Не заполнено — сверка выключена (участники Media BMSTU верифицируются автоматически). Не найденных в таблице бот отправляет старшим на ручную проверку.
- `ORG_MEMBERS_FILE` (необязательно) — автосверка организаций (СО/ССФ) по локальному файлу. Сделать так: `pip install openpyxl`, затем `python bot/make_members.py "список.xlsx"` — получится `bot/org_members.csv`. По умолчанию бот читает его же; если файла нет — организации проверяет старший вручную. Проверка гоняется и при смене ФИО в профиле.

### 4. Запустить туннель (при каждом сеансе тестов)

В отдельном окне терминала:

```powershell
cloudflared tunnel --url http://localhost:8737
```

В выводе появится адрес вида `https://something-random.trycloudflare.com` — это и есть HTTPS-адрес приложения.

> Адрес **меняется при каждом запуске** туннеля — после перезапуска вписать новый в `.env` и перезапустить бота. (Постоянный адрес — это вариант Б с сервером, либо named tunnel Cloudflare со своим доменом.)

### 5. Вписать URL и запустить бота

В `bot/.env`: `WEBAPP_URL=https://something-random.trycloudflare.com`, затем:

```powershell
cd "D:\Media BMSTU\Оборудыш\bot"
.\venv\Scripts\python main.py
```

В логе: `Статика: http://localhost:8737` и `Mini App URL: …`.

### 6. Проверить в Telegram

Открыть тестового бота → `/start` → кнопка «📦 Открыть Оборудыш» (или кнопка меню «Оборудыш»). Приложение откроется на весь экран без телефонной рамки.

**Чек-лист на телефоне:**
- [ ] тема подхватилась из Telegram (тёмная/светлая), переключение темы Telegram меняет приложение на лету
- [ ] системная кнопка «Назад» Telegram ходит по шагам мастера и экранам
- [ ] имя, @ник и аватарка подтянулись из Telegram на главном экране
- [ ] регистрация проходится **один раз** — при следующем открытии сразу главный экран
- [ ] заявка на оборудование → карточка прилетела в группу админов; статусы меняются — карточка обновляется
- [ ] «Служебное» на главном видно только тем, кто вписан в `ADMIN_IDS`/`SENIOR_ADMIN_IDS`
- [ ] действия админа (куратор/согласовано/выдано/возврат) шлют уведомления заявителю от бота
- [ ] сообщения в переписке заявки доходят второй стороне уведомлением
- [ ] после добавления `prototype/catalog.js` и `prototype/img/` — реальный каталог и фото (файлы просто положить в папку, перезапуск не нужен)

**Обновление уже задеплоенной версии:** заменить `prototype/index.html`, `prototype/style.css`, `prototype/catalog.js` и `bot/main.py`; при изменении `main.py` перезапустить сервис. Новые переменные сверять с `bot/.env.example`. Зависимости необходимо обновить командой `bot/venv/bin/pip install -r bot/requirements.txt`. База создаётся сама (`bot/oborudka.db`); удалить её = сбросить всех пользователей и заявки.

---

## Вариант Б — VPS (постоянный адрес, для команды)

Предполагается Ubuntu 22.04+ и домен, направленный A-записью на IP сервера (например `oborudka.example.ru`).

### 1. Перенести файлы и поставить зависимости

```bash
sudo apt update && sudo apt install -y python3-venv git
# файлы проекта → /opt/oborudka (git clone или scp папок bot/ и prototype/)
cd /opt/oborudka/bot
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env
# BOT_TOKEN=токен, WEBAPP_URL=https://oborudka.example.ru, PORT=8737
```

### 2. Автозапуск через systemd

`/etc/systemd/system/oborudka.service`:

```ini
[Unit]
Description=Oborudka bot + Mini App static
After=network.target

[Service]
WorkingDirectory=/opt/oborudka/bot
ExecStart=/opt/oborudka/bot/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now oborudka
sudo systemctl status oborudka   # проверить, что запустился
journalctl -u oborudka -f        # логи
```

### 3. HTTPS через Caddy (сам получает и продлевает сертификат)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
oborudka.example.ru {
    reverse_proxy localhost:8737
}
```

```bash
sudo systemctl reload caddy
```

Готово: `WEBAPP_URL=https://oborudka.example.ru` в `.env`, `sudo systemctl restart oborudka`. Адрес постоянный, кнопку меню бот обновит сам при старте.

### Обновление прототипа на сервере

Заменить файлы в `/opt/oborudka/prototype/` (index.html, catalog.js, img/) — рестарт не нужен, статика читается с диска на каждый запрос.

---

## Частые проблемы

| Симптом | Причина |
|---|---|
| Кнопка есть, но «страница недоступна» | Туннель упал / URL сменился — перезапустить туннель, обновить `.env`, перезапустить бота |
| `BOT_TOKEN не задан` при старте | Нет `bot/.env` или пустой токен |
| `WEBAPP_URL должен быть https` | В `.env` вписан `http://` или localhost — Telegram такое не откроет |
| Приложение открылось, но фото/каталога нет | Нет файлов `prototype/catalog.js` и `prototype/img/` — прототип работает на демо-данных |
| `Unauthorized` в логе бота | Неверный/отозванный токен |
| Тост «Демо-режим: бэкенд недоступен» в Telegram | Крутится старый `main.py` без API — обновить файл и перезапустить |
| Нет «Служебного» на главном | Ваш ID не вписан в `ADMIN_IDS`/`SENIOR_ADMIN_IDS` (после правки .env — перезапуск) |
| Карточки не падают в группу | `ADMIN_CHAT_ID` пуст/неверен, либо бота нет в группе |

---

## Чистый старт перед прод-релизом (сброс базы)

Когда переходишь с тестового бота на боевой — нужно стартовать с **пустой базой**, чтобы ни у кого не осталось
тестовых заявок, броней и аккаунтов. Для этого есть готовые скрипты (они делают бэкап, потом сносят базу).

> ⚠️ **Это стирает ВСЁ**: все заявки, брони 626, переписку и пользователей. Делается один раз при переходе на прод.
> Скрипт сначала копирует текущие `oborudka.db` и `uploads/` в `bot/backup/<дата-время>/`, потом удаляет оригиналы.

**Windows:**
```powershell
cd bot
powershell -ExecutionPolicy Bypass -File reset.ps1
```

**VPS (systemd):**
```bash
cd bot
bash reset.sh oborudka   # oborudka — имя вашего systemd-сервиса (по умолчанию)
```

Порядок внутри: стоп бота → бэкап → снос `oborudka.db` + `uploads/` → старт. При старте схема создаётся с нуля
(`init_db`/`_migrate`). Автосброса по флагу в `.env` намеренно нет — только ручной запуск, чтобы не снести прод случайно.

---

## Ошибка 413 при отправке фото (Nginx)

Если бот стоит за **Nginx** и при сдаче с фотографиями вылезает `413 Request Entity Too Large` — это лимит тела запроса в Nginx (по умолчанию всего **1 МБ**). Фото в base64 больше не пролезают.

Фикс — в конфиге сайта (`/etc/nginx/sites-available/…` или в нужном `server {}`/`location /api/ {}`) добавить:

```nginx
client_max_body_size 32M;
```

затем проверить и перечитать конфиг:

```bash
sudo nginx -t && sudo nginx -s reload
```

Дополнительно приложение само сжимает фото сильнее (до 1024px, качество 0.65), так что после правки Nginx проблема уходит.

---

## Final single-service release procedure

Use one directory `/opt/oborudka`, one systemd unit `oborudka.service`, port `8737`, one bot token, one database and one Google Sheet.

### Isolated Python 3.10+

Do not upgrade or replace the server's system Python. Install a side-by-side interpreter and create a venv used only by Oborudka:

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv
cd /opt/oborudka
python3.10 -m venv bot/venv
bot/venv/bin/python -m pip install --upgrade pip
bot/venv/bin/pip install -r bot/requirements.txt
```

The service must keep `ExecStart=/opt/oborudka/bot/venv/bin/python main.py`. Other bots and `/usr/bin/python3` are untouched.

### Google Sheets

1. In Google Cloud enable Google Sheets API, create a service account and download its JSON key.
2. Create the spreadsheet and share it with the service-account e-mail as Editor.
3. Copy the spreadsheet ID from its URL.
4. Encode the JSON as one Base64 line and put it only in `bot/.env`:

```bash
base64 -w 0 service-account.json
```

PowerShell equivalent:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("service-account.json"))
```

Fill `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON_B64`, leave the two tab names at their defaults, then set `GOOGLE_SHEETS_ENABLED=1`. Never commit the JSON or real `.env`.

### Caddy compression

```caddy
oborudka.example.ru {
    encode zstd gzip
    reverse_proxy localhost:8737
}
```

Validate and reload: `sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`.

### Safe update and rollback

Always stop and back up before replacing the backend:

```bash
sudo systemctl stop oborudka
cd /opt/oborudka
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p backup/releases/$stamp
cp bot/oborudka.db backup/releases/$stamp/oborudka.db
cp -a bot/main.py bot/requirements.txt prototype backup/releases/$stamp/
# copy the new release files here
bot/venv/bin/pip install -r bot/requirements.txt
sudo systemctl start oborudka
sudo systemctl status oborudka
```

Rollback: stop the service, restore `main.py`, `requirements.txt`, `prototype/` and `oborudka.db` from the selected release backup, reinstall requirements, then start the service.

A `main.py`, dependency or `.env` change requires `sudo systemctl restart oborudka`. Static-only changes do not require a restart. After release check `/scorestatus`, then `/scoresync`, and verify the two sheet tabs.
