# Оборудыш: запуск Mini App в Telegram и деплой

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

**Обновление уже задеплоенной версии:** заменить `prototype/index.html`, `prototype/style.css`, `prototype/catalog.js` и `bot/main.py`; при изменении `main.py` перезапустить сервис. Новые переменные сверять с `bot/.env.example`. Новых зависимостей нет. База создаётся сама (`bot/oborudka.db`); удалить её = сбросить всех пользователей и заявки.

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
