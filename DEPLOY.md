# Оборудыш: запуск Mini App в Telegram и деплой

## Очистка заявок и команд медиа-выезда — 08.10.2026

Заказчик выбрал удаление ВСЕХ заявок, истории и команд выезда. Это не сброс пользователей: обычные заявки/626, каталог выезда, расписание, настройки рентала и канал сохраняются. Рабочий сервер недоступен ассистенту по SSH с текущего компьютера, поэтому выполнить на сервере:

```bash
cd /srv/oborudka &&
git pull --ff-only origin main &&
systemctl stop oborudka &&
(
    trap 'systemctl start oborudka' EXIT
    bot/venv/bin/python bot/clear_media_trip_history.py --teams clear --apply
)
```

Команда сначала делает полную SQLite-копию в `bot/backup/media-trip-before-clear-*.db` и проверяет её, затем в одной транзакции очищает только таблицы заявок/истории/очереди доставки/команд/участников выезда. При выданном оборудовании остановится с объяснением: сначала отметить возврат в рентале. Сервис запускается снова даже при ошибке очистки. Если получение кода не удалось, последующие действия не запускаются. Использовать только настроенный чистый серверный Git checkout; не применять hard reset или clean при конфликте.

Проверка количества без удаления: `bot/venv/bin/python bot/clear_media_trip_history.py --teams clear`. Для сохранения действующих команд существует вариант `--teams keep --apply`; он удалит заявки и старые удалённые команды, освобождая их номера. После успешной очистки переоткрыть Mini App и создать команды заново. Резервную копию не публиковать. `reset.sh`/`reset.ps1` не запускать. .env и зависимости не меняются.

## Подробный отчёт `/membersync` — 08.10.2026

Обновление меняет только `bot/main.py` среди runtime-файлов. После резервной копии получить GitHub main в существующем `/srv/oborudka` и перезапустить `oborudka` по инструкции ниже. .env, зависимости и схема БД не меняются; фронтенд обновлять для этого исправления не требуется.

После обновления `/membersync` и `/membersync apply` показывают старые и новые значения каждого изменённого поля, включая отделы при прежней роли. Если изменения уже были применены раньше, текущая сверка не восстанавливает прежние значения: она показывает только оставшиеся различия между базой и свежим листом.

## Отмена, выезд и обновление ролей — 08.10.2026

Runtime-файлы: `bot/main.py`, `bot/media_trip.py`, `prototype/index.html`, `prototype/media-trip.js`. Сохранить актуальные `prototype/catalog.js` и `prototype/style.css`. Зависимости и `.env` менять не нужно; миграции выполняются при запуске. Рабочую базу не удалять и `reset.sh`/`reset.ps1` не запускать.

Для настроенного серверного checkout `/srv/oborudka`: проверить чистый `git status`, остановить `oborudka`, сделать полную копию папки вне проекта по инструкции ниже, выполнить `git pull --ff-only origin main`, запустить существующий `oborudka.service` и проверить свежие логи. При ошибке остановиться; не использовать hard reset или clean. Если первое применение кода ещё не завершено, сначала использовать соответствующий раздел ниже.

После выкладки:

1. Проверить отмену с причиной пользователем и обычным админом. Выданное оборудование не отменяется — нужен возврат.
2. Оба старших (1896340090 и 5027289530) должны ранее запустить бота и не блокировать его. Проверить доставку предложения отклонить заявку в их ЛС и переход к карточке. Неудачная доставка одному не повторяет успешно доставленное другому. Активные просроченные опросы с прежней канальной отметкой тоже получат ЛС.
3. Проверить рентал в настройках выезда: существующий состав сохранён; если он был пуст, назначены эти два ID. Добавить участников через команду/куратора. Участник видит кнопку «Медиа выезд», посторонний — нет; прежние тестировщики без команды/рентала не имеют доступа.
4. Проверить ID отдельного канала выезда и права бота на отправку. Пустое поле использует основной `ADMIN_CHAT_ID`. Создать заявку и проверить канал; существующие активные заявки без сообщения будут восстановлены. Очередь недоставленного отображается у рентала, попытки продолжаются с задержкой. При отсутствии обоих каналов создание заявки отклоняется с объяснением.

### Обновление пользователей вместо сброса

Обновить существующий закрытый лист «люди» с колонками `ФИО`, `ТГ`, `Отделы Media BMSTU`, `Роль Media BMSTU`, `Организации`. Service Account должен иметь чтение; используются существующие `MEMBERS_SHEET_ID`, `MEMBERS_SHEET_TAB`, ключ аккаунта. Лист начислений для сверки не используется.

В личке бота старший отправляет `/membersync`, просматривает отчёт, затем `/membersync apply`. Обновляются роли (в том числе понижения), ФИО, отделы и организации ранее зарегистрированных людей. Не найденные и неоднозначные совпадения не изменяются; их ID указаны в отчёте для ручной проверки. Заблокированные пропускаются; статусы верификации, права администраторов, заявки, баллы и команды сохраняются. Команда всегда читает свежий лист, при ошибке чтения ничего не применяет.

Новые люди запускают бота и регистрируются: данные подставляются из свежего листа по Telegram username или ФИО. По одному username заранее создать пользователя Telegram нельзя — приложению нужен его ID при первом открытии. Рабочая база не сбрасывается. Перед массовым применением сохранить резервную копию.

## Исправление `BUTTON_TYPE_INVALID` — 04.10.2026

В уведомлении канала о заявке без куратора заменена запрещённая для канала `web_app`-кнопка на URL-кнопку с `startapp=request_<id>_admin`. Переход к карточке уже поддерживается фронтендом. Runtime-изменение: только `bot/main.py`; зависимости, `.env` и схема БД прежние. Проверено 77 Python-тестами и локальной проверкой маршрута startapp.

Для серверного checkout, завершившего первое применение кода ниже, проверить чистый `git status --short --branch`, остановить `oborudka`, сделать полную копию по приведённым ниже командам, выполнить `git pull --ff-only origin main`, затем запустить сервис. При ошибке остановиться и сохранить вывод; не применять hard reset или clean. Проверить:

```bash
systemctl --no-pager --full status oborudka
journalctl -u oborudka --since "5 minutes ago" --no-pager
git rev-parse --short HEAD
```

Старые записи `BUTTON_TYPE_INVALID` в журнале останутся: оценивать свежие строки после перезапуска. Недоставленные эскалации будут повторены планировщиком, если заявки остаются согласованными без куратора и опрос завершён. Проверить сообщение и кнопку в Telegram. Фактический запуск сервера ещё не подтверждён.

## Новые версии через GitHub с Mac — 04.10.2026

Разработка продолжается в `/Users/aleksejdavydov/Projects/Оборудыш`, выпуск — в `misterfrukt3/Oborudsh`, ветка `main`. Разработчик сам делает проверки, commit и push; порядок — [GITHUB_MAC.md](GITHUB_MAC.md).

Это отдельный процесс Оборудыша. Используются только его репозиторий, `/srv/oborudka`, `oborudka.service` и SQLite; настройки и скрипты ТехСценария сюда не переносятся.

Git-метаданные существующей `/srv/oborudka` уже подключены к `origin/main`; первое применение кода ещё нужно завершить по разделу ниже. Для настроенного чистого серверного checkout последующие версии получать через `git pull --ff-only origin main`. `.env`, SQLite, справочники и пользовательские данные сохраняются на сервере.

## Завершить первое обновление — проверенный сервер 04.10.2026

Проверено по выводу владельца: каталог, `main.py`, зависимости, тексты и CSS совпадают с GitHub после исключения Windows-переносов строк. Реальные отличия — правка удаления команд (`bot/media_trip.py`, `prototype/media-trip.js`, версия скрипта в `prototype/index.html`). Сервис запускает `/srv/oborudka/bot/venv/bin/python main.py` из `/srv/oborudka/bot`.

Команды ниже предназначены для уже завершённых `init/fetch/reset --mixed` и разобранного сравнения. Выполнять на сервере по шагам; при ошибке следующую команду не запускать. В SSH владелец работает как `root`.

```bash
cd /srv/oborudka
systemctl stop oborudka
```

Полная копия включает старый код, `.env`, SQLite и sidecar-файлы, вложения, существующее Python-окружение и Git-метаданные. Она сохраняется вне рабочей папки:

```bash
backup_dir="/srv/oborudka-backups/$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$backup_dir"
tar -czf "$backup_dir/oborudka.tar.gz" -C /srv oborudka
chmod 600 "$backup_dir/oborudka.tar.gz"
tar -tzf "$backup_dir/oborudka.tar.gz" >/dev/null
echo "Копия: $backup_dir/oborudka.tar.gz"
```

Установить уже полученную и проверенную версию, на которую указывает текущий `HEAD`. Эта команда обновляет только отслеживаемые кодовые файлы; `.env`, рабочая база, окружение и серверные файлы вне Git остаются на месте:

```bash
git checkout HEAD -- .
git status --short --branch
```

Ожидается только строка ветки без изменённых файлов. В этом выпуске зависимости и переменные окружения не менялись: `pip install`, редактирование `.env`, ручное удаление/пересоздание базы не требуются.

```bash
systemctl start oborudka
```

```bash
systemctl --no-pager --full status oborudka
journalctl -u oborudka -n 50 --no-pager
git rev-parse --short HEAD
```

Дождаться `active (running)`, проверить отсутствие traceback, затем переоткрыть Mini App и проверить «Панель рентала → Команды → Удалить команду». Миграция добавления признака удаления выполнится при запуске. Отчёт Git не заменяет эту проверку приложения.

Для дальнейших выпусков: перейти в `/srv/oborudka`, проверить чистый `git status`, остановить сервис, сделать такую же полную копию, выполнить `git pull --ff-only origin main`, при изменении requirements обновить только существующий `bot/venv`, затем запустить сервис и проверить его состояние/логи и Mini App. При ошибке обновления прежний сервис можно запустить через `systemctl start oborudka`; не стирать отличия командой hard reset.

## Первое подключение существующей `/srv/oborudka` к GitHub

Этот этап добавляет Git-метаданные и сравнивает серверные файлы с опубликованным кодом. Рабочие файлы, настройки и база не меняются; останавливать бота пока не нужно. Репозиторий `misterfrukt3/Oborudsh` публичный, для получения кода GitHub-токен не требуется.

Команды выполнить на сервере, по шагам. При ошибке следующую команду не запускать.

```bash
cd /srv/oborudka
```

```bash
git init
git symbolic-ref HEAD refs/heads/main
```

На сервере установлен Git без поддержки `git init -b`; отдельная команда `symbolic-ref` задаёт `main` и совместима с этой версией.

```bash
git remote add origin https://github.com/misterfrukt3/Oborudsh.git
```

```bash
git fetch origin
```

Добавить исключения локальных данных в служебный файл Git, сохранив существующий `.gitignore`:

```bash
git show origin/main:.gitignore >> .git/info/exclude
```

Привязать историю и индекс к `main`, сохранив все рабочие файлы:

```bash
git reset --mixed origin/main
git branch --set-upstream-to=origin/main main
git config pull.ff only
```

`--mixed` здесь используется один раз для первоначального подключения: он меняет историю и индекс, сохраняя содержимое рабочей папки. `--hard` не использовать. После этого hash показывает основу сравнения, а не фактически установленную версию приложения.

```bash
git status --short --branch
git diff --stat
```

Передать разработчику вывод этих двух команд. Он покажет отличия текущей серверной версии, включая каталог и изменения, сделанные только на сервере. До их разбора не выполнять `git restore`, `git checkout -- .` или обновление с перезаписью файлов. Первое получение кодовой версии завершается отдельно: сохранить особые серверные правки, остановить бота, сделать полную копию папки (с `.env`, SQLite и sidecar-файлами) вне `/srv/oborudka`, обновить только согласованные кодовые файлы, проверить и запустить сервис. Папку не переносить и повторно не клонировать.

После первого согласования рабочая кодовая копия должна быть чистой, и дальнейшие версии устанавливаются стандартным `git pull --ff-only origin main`, с сохранением базы и настроек по инструкции ниже.

## Обновление 04.10.2026 — удаление команд медиа-выезда

- Заменить `bot/media_trip.py`, `prototype/media-trip.js` и `prototype/index.html`.
- Перезапустить существующий сервис `oborudka`: миграция добавит признак удалённой команды автоматически. Новых переменных `.env` нет; рабочую БД сохранять.
- Сохранить актуальные `prototype/catalog.js`, `prototype/style.css` и остальные файлы фронта.
- В Telegram проверить удаление команды без заявок, освобождение участников и отключение старого кода. При активной заявке удаление должно отказать; после отмены/возврата — пройти с сохранением истории рентала.

## Что добавляет релиз 16.07.2026

- Автоматическая миграция создаёт паспорта `equipment_units` и поля `issued_by`/`returned_by`; базу сбрасывать не нужно.
- Перенести также `bot/texts.py`, `prototype/texts.js` и всю папку `prototype/fonts/`.
- Caddy должен пропускать SSE без буферизации и использовать `encode zstd gzip`.
- После первого запуска проверить паспорт экземпляра, недельный календарь и `/api/events`.
- Google Sheets сначала оставить выключенным (`GOOGLE_SHEETS_ENABLED=0`), затем включить и выполнить `/scoresync`.


## Главное: как обновить уже работающего Оборудыша на VPS

Ниже — порядок для текущей схемы: один каталог `/srv/oborudka`, один сервис `oborudka.service`, одна база `bot/oborudka.db` и один боевой бот.

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
cd /srv/oborudka
stamp=$(date +%Y%m%d-%H%M%S)
sudo mkdir -p /srv/oborudka-backups/$stamp
sudo cp bot/oborudka.db /srv/oborudka-backups/$stamp/oborudka.db
sudo cp bot/main.py bot/requirements.txt /srv/oborudka-backups/$stamp/
sudo cp -a prototype /srv/oborudka-backups/$stamp/prototype
echo "Резервная копия: /srv/oborudka-backups/$stamp"
```

Не удаляйте `bot/oborudka.db`: в ней находятся пользователи, заявки, переписки и очередь начислений.

### 3. Перенести новые файлы

Если проект на VPS подключён к Git и изменения уже опубликованы:

```bash
cd /srv/oborudka
git pull --ff-only origin main
```

Если файлы загружаются вручную через WinSCP/SFTP, замените их по тем же путям внутри `/srv/oborudka`. Папку `prototype/fonts/` переносите целиком.

После копирования проверьте наличие основных файлов:

```bash
cd /srv/oborudka
ls -l bot/main.py bot/requirements.txt prototype/index.html prototype/style.css
ls -l prototype/fonts/
```

### 4. Обновить отдельное Python-окружение Оборудыша

Команда ниже обновляет только окружение Оборудыша. Python и библиотеки остальных ботов она не меняет.

```bash
cd /srv/oborudka
bot/venv/bin/python -m pip install --upgrade pip
bot/venv/bin/pip install -r bot/requirements.txt
bot/venv/bin/python --version
```

Нужен Python 3.10 или новее. Если `bot/venv` ещё не существует, сначала создайте его отдельным Python 3.10+:

```bash
cd /srv/oborudka
python3.10 -m venv bot/venv
bot/venv/bin/pip install -r bot/requirements.txt
```

Системный `/usr/bin/python3` не заменять.

### 5. Дописать новые настройки в серверный `.env`

Откройте существующий файл:

```bash
sudo nano /srv/oborudka/bot/.env
```

Добавьте отсутствующие строки:

```dotenv
ENABLE_PRODUCTION_ROLE=0

GOOGLE_SHEETS_ENABLED=0
GOOGLE_SHEET_ID=
GOOGLE_SERVICE_ACCOUNT_JSON_B64=
GOOGLE_SHEET_EVENTS_TAB=Начисления
GOOGLE_SHEET_SUMMARY_TAB=Админы
INVENTORY_SOURCE_SHEET_ID=
INVENTORY_SOURCE_SHEET_TAB=Инвентарь
GOOGLE_SHEET_REQUESTS_TAB=Заявки
GOOGLE_SHEET_626_TAB=626

SCORE_DAILY_ADMIN=0.1
SCORE_REQUEST=0.01
SCORE_626=0.05
```

Для инвентаризации дайте тому же Service Account доступ **читателя** к отдельной исходной таблице и **редактора** к таблице `GOOGLE_SHEET_ID`. В `INVENTORY_SOURCE_SHEET_ID` укажите ID исходной таблицы, а в `INVENTORY_SOURCE_SHEET_TAB` — лист, где каждая строка соответствует одному экземпляру. Обязательные заголовки: `Категория` и `Название`; поддерживаются также `Инвентарный номер`, `Рентал`, `Источник`. Итоговые листы `Инвентарка — ДАТА` и `Итоги рентал — ДАТА` создаются автоматически в `GOOGLE_SHEET_ID`.

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
   Она же создаёт листы `Заявки` и `626` и переносит туда все завершённые, отклонённые и отменённые записи.
8. `/digest` отправляет оформленную статистику в канал.

### Если бот не запустился: быстрый откат

Посмотрите имя последней резервной папки:

```bash
ls -lt /srv/oborudka-backups
```

Затем подставьте её имя вместо `ИМЯ_КОПИИ`:

```bash
sudo systemctl stop oborudka
cd /srv/oborudka
sudo cp /srv/oborudka-backups/ИМЯ_КОПИИ/oborudka.db bot/oborudka.db
sudo cp /srv/oborudka-backups/ИМЯ_КОПИИ/main.py bot/main.py
sudo cp /srv/oborudka-backups/ИМЯ_КОПИИ/requirements.txt bot/requirements.txt
sudo mv prototype "prototype.failed-$(date +%Y%m%d-%H%M%S)"
sudo cp -a /srv/oborudka-backups/ИМЯ_КОПИИ/prototype ./prototype
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
# файлы проекта → /srv/oborudka (git clone или scp папок bot/ и prototype/)
cd /srv/oborudka/bot
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
WorkingDirectory=/srv/oborudka/bot
ExecStart=/srv/oborudka/bot/venv/bin/python main.py
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

Заменить файлы в `/srv/oborudka/prototype/` (index.html, catalog.js, img/) — рестарт не нужен, статика читается с диска на каждый запрос.

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

Use one directory `/srv/oborudka`, one systemd unit `oborudka.service`, port `8737`, one bot token, one database and one Google Sheet.

### Isolated Python 3.10+

Do not upgrade or replace the server's system Python. Install a side-by-side interpreter and create a venv used only by Oborudka:

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv
cd /srv/oborudka
python3.10 -m venv bot/venv
bot/venv/bin/python -m pip install --upgrade pip
bot/venv/bin/pip install -r bot/requirements.txt
```

The service must keep `ExecStart=/srv/oborudka/bot/venv/bin/python main.py`. Other bots and `/usr/bin/python3` are untouched.

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
cd /srv/oborudka
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


### Закрытый лист «люди»

В `bot/.env` заполнить:

```env
MEMBERS_SHEET_ID=1caWlBJbzYHt0-SK744UD9rU7VS28cNAJY7jxoXosqCs
MEMBERS_SHEET_TAB=люди
GOOGLE_SERVICE_ACCOUNT_JSON_B64=
```

Service Account должен иметь доступ «Читатель». Локально вместо Base64 можно
указать `GOOGLE_SERVICE_ACCOUNT_FILE`, но на сервере ключ хранится только в
`bot/.env`. При регистрации одна точная строка ФИО заполняет организации,
отделы и роль автоматически; отсутствие или дубль отправляются на ручную
проверку.

### Одноразовая миграционная рассылка

1. Положить старую базу как `bot/equipment_bot.sqlite3`.
2. Задать `LEGACY_MIGRATION_PASSWORD` в `bot/.env`.
3. Перезапустить бот.
4. Сначала выполнить `/migrateold_preview`: бот пришлёт количество и TXT со всеми адресатами, ничего не меняя.
5. Затем написать `/migrateold` и отправить пароль отдельным сообщением.

Старая таблица `users` используется только как список адресатов. В новую базу ничего
не импортируется. `/migrateold_preview` безопасно показывает список, а `/migrateold`
делает рассылку напрямую по старой SQLite.


Таблица баллов текущего релиза:
`1a6F6lnQbiAQEKka-0oU2c8Kmy9Mvq6i1QvQwhRnVRHU`.
Service Account имеет права редактора. После заполнения `GOOGLE_SHEET_ID` и
`GOOGLE_SHEETS_ENABLED=1` проверить `/scorestatus`, затем `/scoresync`.


## Обновление 07.09.2026

Исправлены повторная выдача невозвращённых экземпляров, расчёт одновременной занятости, точное время выбора номеров и сохранение исходных названий. Сдача оборудования и 626 подтверждается после доставки фото; при ошибке фотографии остаются в форме для повтора.

Добавлены восстановление черновика, частичное добавление избранного, подсказки следующего действия и читаемые карточки. Владелец может отменить 626 только до начала; после начала — сдача с фото или отмена старшим с причиной. Куратор 626 может освободить бронь для нового куратора, старший тоже может инициировать смену.

Заявка без куратора через 36 часов отправляется в личные сообщения всех администраторов с датой/временем выдачи, полным составом, сроком и кнопками ответа. На ответ даётся 6 часов. После этого не ответившие считаются проигнорировавшими, их поздние ответы не назначают куратора, а в канал приходит предложение отклонить заявку с упоминанием старших. Команда `/offerstatus` показывает старшим количество отказов, игнорирований, ожидающих ответов и недоставленных сообщений. Старший может отклонить заявку до выдачи с обязательной причиной.

Исправлено 08.09.2026: завершение опроса выполняется отдельной проверкой и больше не зависит от времени создания заявки. В уведомлении и `/offerstatus` показываются имена отказавшихся и проигнорировавших. При возвращении заявки в очередь прежний опрос сбрасывается.

Команда `/offerstatus` снова отвечает независимо от доступности канала. Ошибка отправки одного предложения об отклонении не останавливает остальные проверки; при ошибке HTML бот повторяет сообщение обычным текстом.

Для выкладки заменить `bot/main.py`, `prototype/index.html`, `prototype/style.css` и актуальный `prototype/catalog.js`. Новых переменных `.env` нет; используются существующие `ADMIN_IDS`, `SENIOR_ADMIN_IDS`, `ADMIN_CHAT_ID` и добавленные командой `/addadmin` админы. Сделать обычный бэкап рабочей БД и перезапустить единственный сервис: новые таблицы доставки/ответов создаются автоматически. Рабочую БД не удалять.

После выкладки проверить в Telegram фото оборудования и 626 (в том числе ошибку и повтор), смену куратора, личные приглашения и ответы администраторов, упоминание старших в канале. Проверки разработки используют временную БД и имитацию Telegram; реальная доставка ими не подтверждается.
# Обновление «Медиа выезд» — 02.10.2026

В существующем сервисе заменить `bot/main.py`, добавить `bot/media_trip.py`, обновить `prototype/index.html`, `prototype/style.css`, добавить `prototype/media-trip.js`. Перенести актуальный `prototype/catalog.js` вместе с фронтом. Перезапустить существующий сервис; миграции создают таблицы в рабочей SQLite автоматически. БД сохранять. Новых переменных `.env` и Python-зависимостей нет.

После выкладки открыть **Медиа выезд → Настройки выезда**: указать отдельный канал (его ID), место выдачи и сотрудников рентала (личные Telegram ID или @username уже известных боту пользователей). Добавить бота администратором канала с правом публикации. Сохранить флаг «Только тестировщики» на время проверки. В тесте 6 уникальных ID из списка заказчика имеют доступ к участнику и панели рентала. После проверки назначить реальных сотрудников и снять ограничение через интерфейс.

В панели рентала заполнить каталог, расписание по Москве, номера команд и ID кураторов. Кураторы могут заранее добавить участников по ID/username либо выдать код вступления на месте. Все участники должны открыть бота и нажать Start, чтобы получать личные сообщения.

Проверить в Telegram: сообщение о новой заявке в отдельном канале, готовность всем участникам команды с местом и составом, напоминание за 30 минут до начала, за 15 минут до конца, сообщение о невозврате, полный возврат. Планировщик режима проверяет сроки каждые 30 секунд. Не отправлять тестовые сообщения в основной канал оборудования.

## Управление обычными заявками — 02.10.2026

Заменить `bot/main.py`, `prototype/index.html`, `prototype/style.css`, добавить `prototype/admin-requests.js`. Сохранить добавленные файлы медиа-выезда из предыдущего раздела, перенести актуальный `prototype/catalog.js`. Перезапустить существующий сервис. Новых переменных `.env` и зависимостей нет. Таблица просьб изменить время создаётся автоматически; рабочую БД сохранять.

Проверить в Telegram просьбу изменить время и переход из уведомления к оборудованию/626, сохранение новых дат и повторное согласование. Проверить последовательность «согласовать → назначить куратора → выдать», выдачу и приём чужой заявки старшим, раздел «Все заявки» и оборудование в очереди/на руках. Завершённые заявки доступны для просмотра; редактирование ограничено временем до выдачи оборудования / начала брони 626.
