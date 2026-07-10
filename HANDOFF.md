# HANDOFF — «Оборудыш» (передача следующей нейронке)

Основной контекст проекта — в `CLAUDE.md` (читать целиком). История правок для заказчика — `CHANGELOG.md`.
Правим два файла: `prototype/index.html` (фронт) и `bot/main.py` (бэк); скрипт `bot/make_members.py`;
методички в `D:\obsidian\Media BMSTU\Оборудыш\`.

## ✅ Сессия 04.07.2026 (5) — выходные/подписи чата/причины отказа/методичка (проверено)

Бэк e2e в DEV — новые ветки проверены (uncurator@issued, chat-role sanitize с чужой заявкой, late_note, 626-reject-reason,
senior-no-reescalate). Фронт — preview, без ошибок.

- **Чат (`messages.role`):** `api_chat` принимает `asRole` (санитизация по правам, владелец→user); `_chat_for` отдаёт
  `label` (Пользователь/Куратор/Админ/Старший) и `senior` (красный только если role==senior). Фронт: `chatMsg(m,invert)`,
  send-функции шлют `asRole`. Красный — только из панели старшего.
- **Причина отказа:** `rejReqModal`→`adminAct(id,'rejected',reason)`; `rej626Modal`→`dec626(id,'rejected',reason)`;
  бэк `api_req_action rejected` и `api_626_action rejected` пишут причину в историю/уведомление.
- **Uncurator до закрытия (#7):** разрешён при curator/approved/issued/ret; при выданной — статус сохраняется, чистится
  только куратор (другой примет возврат). Кнопка в `adminReq`.
- **Старший не ре-эскалирует (#6):** `return`+comment эскалирует только `if not is_senior(uid)`; иначе просто закрывает.
- **Выходные (#2):** `dateBlock` (вс — получение и возврат жёстко) + `dateSoftWarn` (сб≥18 — мягко); ready-гейт только по
  `dateBlock`. Бэк `late_note(r)` → пометка в `req_card_text` и `shape_req.lateNote` (показ админам в `adminReq`).
- **Методичка (#3):** `SCREENS.manual` (Важное/Подробно), ссылка на экране `rules` перед регистрацией. Регламент в
  `SCREENS.rules` переписан под текущее поведение.
- **Роль production (#15):** во всех списках + `ALLOWED_ROLES`; `canAct` считает production активистом; «Твоя роль».
- **Категории — встроенный календарь (#9):** `catBlockSheet`→`drawCatBlock` рисует `calHtml` (тип-date убран).
- **Непрочитанные у админов/старших (#10):** бейджи на входах «Служебное» (noCur+unread / verifQueue+проблемные+626-new).
- **Зум (#8):** viewport `user-scalable=no` + `touch-action` + JS-глушилки. Иконка «Стабилизаторы» перерисована.
- **413 (#12 добито):** корень — Nginx `client_max_body_size` (дефолт 1 МБ); в DEPLOY.md раздел (`32M`); фото 1024px/0.65.
- **CLAUDE.md** переписан под актуальное состояние (код доступа убран, фото без диска, 4 роли, таблицы/эндпоинты, выходные).

## ✅ Сессия 04.07.2026 (4) — эскалация/непрочитанные/роли/доки (проверено)

Бэк e2e в DEV — **13/13 PASS**. Фронт — preview, без ошибок.

- **Схема:** `requests.escalated`, `users.block_until`, таблица `reads(user_id,kind,ref,seen)` (+`_migrate`).
- **Эскалация возвратов (#11):** `api_req_action` ветка `return` — с комментом куратора: `status=ret, escalated=1`,
  коммент как сообщение в чат, уведомление старшим/в канал; куратор больше не принимает (`if r.escalated and not is_senior`).
  Старший принимает `return` без коммента (снимает escalated, close). Фронт: `SCREENS.problemReturns` + пункт seniorHub;
  в `adminReq` эскалированный возврат для не-старшего → «Передано старшим», у старшего — «Принять возврат» и чат.
- **Красные сообщения старших:** `_chat_for` отдаёт `senior`; фронт класс `.msg.senior` (все чат-экраны).
- **Снять кураторство (#3):** action `uncurator` (curator/approved → new, в канал); кнопка в `adminReq`.
- **Завершено куратором (#10):** `return` без сдачи (prev `issued`) → уведомление «завершена вашим куратором».
- **Непрочитанные (#13):** `shape_req/626.unread`, `_seen/_unread`, `POST /api/read`; фронт `unreadBadge`+`markRead`
  (вызов в `after` детальных экранов), бейджи на карточках.
- **Чат старшего (#12 роутинг):** `api_chat` — старший уведомляет и владельца, и куратора.
- **Роли (#15):** `production` во всех списках + `ALLOWED_ROLES`; `canAct` считает production как активиста;
  «Желаемая роль» → «Твоя роль».
- **Верификация:** отказ с причиной (модалка `rejectModal`, хранится в `block_reason`, юзер видит и может подать заново —
  `SCREENS.rejected` + маршрут в `bootApp`); блок со сроком: `days`/term → `block_until`, авто-снятие в `boot_payload`
  и `run_checks`; `banModal` с «1 день» и ручным вводом дней.
- **Категории (#9):** `catBlockSheet` только дата (`type=date` → ISO); авто-удаление истёкших в `run_checks` (`_date_passed`).
- **Статистика (#1/#2):** `adminStats.curated`; `api_export` kind `admins`; фронт колонка «курир.» + кнопка «Админы».
- **Удаление оборудки (#5):** отдельный `SCREENS.removeEquip` + пункт seniorHub «Убрать оборудование».
- **Зум (#8):** viewport `user-scalable=no`, `touch-action:manipulation`, JS-глушилки жестов.
- **413 (#12):** корень — Nginx `client_max_body_size` (дефолт 1 МБ). В DEPLOY.md добавлен раздел (`32M`);
  фронт `shrinkPhoto` 1024px/0.65 + гард по размеру.
- **Доки:** переписаны `Методичка пользователя.md` (Важное/Подробно) и `reglament_oborudysh.md` под текущее поведение.

## ✅ Сессия 04.07.2026 (3) — сводки/наборы/выгрузка + правки (проверено)

Бэк e2e в DEV — **13/13 PASS** (org-сверка+смена имени, favset, export без диска, equip remove/restore, stale-флаг,
недельный бэкап, adminStats). Фронт — preview, без ошибок (код-доступа убран, наборы, повтор, очереди админа).

- **Планировщик (`run_checks`):** напоминания в `ADMIN_CHAT_ID` о зависших (заявка `new`/`curator`/626 `new` >6 ч,
  троттлы `nocur`/`noappr` в `notif`); ежедневная сводка `daily_digest()` в 22:00 (гейт `meta.digest_date`);
  недельный `weekly_backup()` в `bot/backup/auto/` (храним 3, гейт `meta.backup_date`). Таблица `meta(k,v)` + хелперы
  `_meta_get/_meta_set`.
- **`api_stats`:** добавлен `adminStats` (выдал/принял/отклонил на админа); экран `SCREENS.stats` рисует таблицу.
- **Повтор/наборы:** `repeatReq(id)` + кнопка; таблица `fav_sets`, `boot.favSets`, `api_favset_add/del`,
  фронт `saveFavSet/doSaveFav/openFavSets/applyFavSet/delFavSet` + кнопки в шаге каталога.
- **Экспорт CSV:** `api_export {kind}` (senior) — CSV в памяти (`io`+`csv`, BOM) → `bot.send_document(BufferedInputFile…)`,
  без диска; фронт `exportCsv(kind)` на экране статистики.
- **Доступ по коду убран (D2):** вырезаны `secretTap/pwModal/_taps`; `itemLocked`: `глава`→только `isSeniorNow()`,
  `акт`→`canAct`. `pwOk/pwUsed`/секретные жесты удалены; заблокированная категория просто показывается недоступной.
- **Админ-заявки (D3):** убран фильтр `!r.me` из очередей (админ видит и курирует свои); в «Историю» добавлены
  626-кураторства (`hist626`).
- **Старший — переписки (D4):** `SCREENS.reqChats` (список заявок → `adminReq`, чат read-only без кураторства);
  пункт в seniorHub.
- **Верификация в канал (D5):** `api_register` при `pending` шлёт в `ADMIN_CHAT_ID` (фолбэк — старшим).
- **Удаление любой оборудки (D6):** таблица `removed_items`; `load_catalog` вычитает из `TOTALS`;
  `boot.removedItems`; `rebuildCatalog` фильтрует; `api_equip_remove/restore`; фронт — поиск «скрыть» + список «вернуть».
- **Блок из профиля (D7):** в `openUserCard` кнопка блок/разблок (`banModal(u.id)` / `unblockUser`).
- **Рассылка без лимита (D1):** снят `maxlength` у `#bc-text`.
- **Сверка организаций:** `ORG_MEMBERS_FILE` (файл от `make_members.py`) → `org_members()/org_ok()`; `api_register`
  проверяет MB по URL, организации по файлу, и **перепроверяет при смене имени** (`name_changed`).
- Скрипт `bot/make_members.py`: `.xlsx` → `bot/org_members.csv` (нужен `pip install openpyxl`).

**Новая переменная .env:** `ORG_MEMBERS_FILE` — путь к CSV со списком организаций (по умолчанию `bot/org_members.csv`,
генерит `make_members.py`). Пусто/нет файла — организации верифицируются старшим вручную (как раньше).

## ✅ Сессия 04.07.2026 (2) — бэклог 3/4/6 (проверено)

Бэк e2e в DEV — **10/10 PASS** (MB-сверка по CSV, equip add/del + TOTALS, cat block/unblock, user unblock).
Фронт — preview, без ошибок; SRV-ветки через фейковый `applyBoot` (extraItems/catBlocks, rebuildCatalog).

- **Автосверка MB (п.4):** `.env` `MB_SHEET_URL` (опубликованный CSV листа «список ребят»). `mb_members()` (кэш 10 мин,
  нормализация `_norm_name`: lower/ё→е/пробелы; повторы схлопывает), `mb_ok(name)`. В `api_register` MB → ok только
  если ФИО в таблице, иначе `pending` (старший верифицирует). URL пуст → авто-ok как раньше. Сеть недоступна → pending.
- **Экраны старшего (п.3):** каталог теперь `let CATALOG` + неизменяемая `CATALOG_BASE`; `rebuildCatalog(extraItems,
  catBlocks)` в `applyBoot` (идемпотентно). Бэк: таблицы `extra_items`, `cat_blocks`; `load_catalog()` домерживает
  extra в `TOTALS`; `boot_payload` отдаёт `extraItems`+`catBlocks` (и `reason` в users). Эндпоинты `category/block`,
  `equip/add`, `equip/del`; в `api_verify` — действие `unblock`. Фронт: `SCREENS.blacklist/catBlocks/addEquip`
  (+`unblockUser`,`catBlock/catBlockSheet`,`saveEquip/delEquip/startAddEquip`), пункты seniorHub подключены.
- **Календарь через год (п.6):** `MONTHS` теперь `[{y,m}]`, `CAL_YEAR` убран; `initCalSRV` с переносом года;
  `calHtml`/`wizNavMonth`/`s626NavMonth`/`startEditReq` работают с `{y,m}`; год в отображении — из ISO-даты.
- Снято по просьбе заказчика из бэклога: ручная проверка в Telegram, картинки каталога, отзыв токена.
  Пункт «WebSocket» — объяснён, не делаем.

**Новая переменная .env:** `MB_SHEET_URL` — ссылка «Публикация в веб → CSV» на лист «список ребят» Google-таблицы
участников Media BMSTU. Не задана — сверка выключена (MB верифицируется автоматически, как до этого). Столбцы CSV
неважны: бот берёт любую ячейку строки, похожую на ФИО (≥2 слов).

## ✅ Сессия 04.07.2026 (1) — правки после теста в Telegram (проверено)

Бэк e2e в DEV — **11/11 PASS** (плюс прошлые 21/21). Фронт — preview `preview_eval`, без ошибок в консоли.

- **Каталог, кавычки в названиях:** helper `escJs()` экранирует `short` во всех onclick (`renderItem`, `openCart`,
  `issueAddSheet`, `drawIssue`). Чинит «последняя позиция не добавляется» (последний товар содержит `"`).
- **Двойные нажатия:** глобальный флаг `_busy` в `srvDo` и в прямых сабмитах (`submitWizard`/`doReturn`/`doHandover626`/
  `submit626`/`sendAppeal`/`sendBroadcast`) — повтор игнорится, пока запрос в полёте.
- **Прыжки в выдаче:** `drawIssue` сохраняет `scrollTop` шита и текст `#issue-comm` при перерисовке.
- **Полный каталог в выдаче:** `issueAddSheet` — срез 30→120 (+подсказка).
- **626-чат админа:** `studioDetail` считает `iCur` (не владелец + куратор/админ), зеркалит реплики, меняет лейбл/тост;
  `send626Chat(id, asAdmin)`.
- **ФИО 3 слова:** `regValid()` (фронт) + `api_register` (бэк).
- **Фото в обращении/рассылке:** галереи `photosGrid("appeal"/"bc")`, состояние `appealText/appealAnon/bcText`,
  аноним чистит и прячет фото; бэк `api_appeal`/`api_broadcast` принимают `photos`.
- **Фото не хранятся на сервере:** `save_photos`/`photos_of`/`send_photos`(FSInputFile) заменены на `_decode_photos`
  + `_send_blobs`/`send_photos_b64` (`BufferedInputFile`). `userret` и 626 `handover` шлют фото сразу куратору + в канал.
- **Кап фото 5:** фронт `PHOTO_MAX=5`, бэк срез `[:5]`; `client_max_size` 24→32 МБ (лечит HTTP 413).
- **Панель админа:** свои заявки исключены из очередей (`!r.me`), убрана секция «Мои заявки (как пользователь)»,
  добавлена вкладка «История» (обработанные куратором, терминальные статусы).

## ⏳ Что осталось сделать по боту (актуальный бэклог)
1. **Реальная проверка в Telegram заказчиком** (локально бот не поднять без прод-токена): media-group фото в канал/лс,
   обращения и рассылка с фото, 626-чат из-под админа, история куратора.
2. **Картинки каталога:** заказчик кладёт `prototype/img/<short>.avif` (см. `prompt-catalog-table.md`).
3. **Экраны старшего — заглушки-toast:** «добавить оборудование в рентал», «блокировка категорий», «чёрный список».
4. **Автосверка MB** с Google-таблицей участников при регистрации (сейчас MB — авто-ok без сверки).
5. **Миграция данных** из sqlite старого бота (`bot_fixed.py`).
6. **Календарь через границу года** (сейчас месяцы обрезаются декабрём — без перехода на январь).
7. **WebSocket/SSE** вместо поллинга 12 с (если заказчику мало «живости»).
8. Мелочи: закрытие 626 без куратора (сейчас фото handover без куратора уходят только в канал — норм); отзыв
   старого скомпрометированного токена бота.

## ✅ Сделано и проверено ранее (сессия 03.07.2026)

Бэкенд протестирован e2e в DEV-режиме — **21/21 PASS** + отдельно проверено happy-path удаление юзера.
Фронт прогнан в preview (демо) через `preview_eval` — без ошибок в консоли; SRV-ветки проверены фейковым `applyBoot`.

### Фронт (prototype/index.html)
- **Лишние ре-рендеры / мелькание** убраны: `.screen-inner` больше не проигрывает анимацию `appear` при
  перерисовке того же экрана (класс `nofade` в `render()`); поллинг `startPolling()` сравнивает сигнатуру
  данных (`_lastSig`) и рендерит только при реальных изменениях.
- **Чат чистит поле**: `sendChat`/`send626Chat`/`sendAdminChat` захватывают текст и зануляют input до `render()`.
- **maxlength** на всех полях ввода (ФИО 80, событие/цель/орг 100, комменты/обращение 500, чат 1000, код 16, причина бана 200 и т.д.).
- **Корзина**: `chQty` клампит по `freeOf(it)` — нельзя набрать больше свободного (работает и в каталоге, и в шите корзины).
- **Фото сдачи** (оборудование и 626): динамическая галерея `photosGrid`/`addPhotos`/`rmPhoto` — можно выбрать
  сразу несколько (`multiple`), удалять по ✕, минимум 1, максимум 10; добавлено поле комментария (`ret-comm`, `ho-comm`).
- **626 «Завершить бронь»**: `close626(id)` → `626/action {action:"closed"}` (кнопка у куратора/старшего при статусе `ret`).
- **Обращения**: `sendAppeal()` → `POST /api/appeal {text, anon}` (кнопка в шите «Задать вопрос»).
- **Мои заявки в панели админа**: секция в `adminHub` (`requests.filter(r=>r.me)`).
- **Роли — всё сразу**: выбор желаемой роли чипами при регистрации (`reg.role` → payload `role`);
  переключение своих ролей — существующее «Служебное»/«‹ Режим пользователя»; смена роли юзеру старшим и
  **удаление** — мини-профиль `openUserCard(i)` → `setUserRole` / `delUser` (`/api/user/role`, `/api/user/delete`).
- **Незавершёнка подключена**: `submitWizard` шлёт `d1,d2,t1,t2` и уходит в `request/update` при `wiz.editId`;
  `startEditReq(id)` собирает `wiz` из заявки (кнопка «✏️ Редактировать»); `wizToCatalog()` тянет `availability`;
  `freeOf`/`loadOf` берут занятость из SRV; `BUSY626` из boot; график студии на SRV — ближайшие 7 дней;
  рассылка (`openBroadcast`/`sendBroadcast`) и статистика (`openStats` + `SCREENS.stats`) подключены к API;
  календарь на SRV считает год/месяцы от реальной даты (`initCalSRV`, `CAL_YEAR`, `let MONTHS`).
- **AVIF**: каталожные картинки — `img/<short>.avif` (функция `thumb`).

### Бэк (bot/main.py) — компилируется (`py_compile` OK)
- `send_photos` → **media group** (все фото одним сообщением, подпись/коммент на первом; 1 фото — обычный send_photo).
  `save_photos` лимит поднят до 10. Коммент прокинут в подпись для `userret` и 626 `handover`.
- `api_626_action`: новое действие **`closed`** (`ret→closed`, только admin/curator); коммент в `handover`/`closed`.
- **`POST /api/appeal`** — обращение в `ADMIN_CHAT_ID` (фолбэк — старшим в личку).
- **`POST /api/user/role`** и **`POST /api/user/delete`** (senior-only; старшего удалить нельзя).
- `boot_payload`: в `verifQueue` добавлена запрошенная `role`, в `users` — `id` и `verified`.
- `api_register` принимает желаемую `role` (валидация против списка).
- Клампы длины на бэке (register/chat/appeal/req create+update/626 goal/ban reason).
- Новые роуты зарегистрированы в `main()`.

## ⏳ Осталось / бэклог (по приоритету)
1. **Проверить в реальном Telegram** (заказчик кликает сам): media-group отправка фото, обращения в канал,
   мини-профиль юзера, редактирование заявки, календарь по реальной дате. Локально бот не поднять (нет прод-токена).
2. Артефакт-задача заказчика: сгенерировать таблицу «файл→оборудка» по `prompt-catalog-table.md`, положить
   картинки в `prototype/img/*.avif`.
3. Бэклог из CLAUDE.md: автосверка MB с Google-таблицей; экраны старшего (рентал/блокировка категорий/ЧС — сейчас
   заглушки-toast); миграция из старого sqlite; календарь через границу года (сейчас без перехода через декабрь);
   WebSocket/SSE вместо поллинга.

## Как запускать/тестировать
- Python: `C:\Users\misterfrukt\AppData\Local\Programs\Python\Python314\python.exe` (в PATH битый стаб — звать полным путём). Цель — **Python 3.8** на VPS, без 3.9+ синтаксиса.
- DEV-бэк: `DEV_USER_ID=111 ADMIN_IDS=111 SENIOR_ADMIN_IDS=111 PORT=8739 ADMIN_CHAT_ID=0 python main.py` (бот не стартует, любой запрос = uid 111).
- e2e-образец лежал в скретчпаде (register → create → availability → over-limit → update → 626 полный цикл с close → appeal → user role/delete guard → broadcast → stats → dev/tick). После тестов удалять `bot/oborudka.db` и `bot/uploads/`.
- Фронт: preview-сервер `prototype` (:8737), демо на моках; SRV симулировать `applyBoot({...})`.

## Деплой
- Заменить `prototype/index.html` (статика — без рестарта), `bot/main.py` (нужен рестарт). `prototype/catalog.js`
  и `prototype/img/*.avif` — по мере обновления заказчиком. Новых .env-переменных нет.
- **Чистый старт перед прод-релизом** (стереть все тестовые заявки/юзеров): `bot/reset.ps1` (Windows) или
  `bot/reset.sh` (VPS) — стоп → бэкап в `bot/backup/<дата>/` → снос `oborudka.db`+`uploads/` → старт. См. DEPLOY.md.
