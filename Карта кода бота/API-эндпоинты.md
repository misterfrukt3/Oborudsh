---
title: API-эндпоинты
часть: Бэкенд
tags:
  - оборудыш
  - api
---

# 🌐 API-эндпоинты

Все `/api/...` ([строки 687–1334](../bot/main.py)). Каждый обёрнут `@auth` ([[Авторизация]]), почти каждый возвращает [[boot_payload — сборка ответа]].

## Общий скелет эндпоинта

```python
@auth
async def api_что_то(request, body, uid):
    # 1. достать данные из body
    # 2. проверить права (is_admin / is_senior) и валидность
    # 3. UPDATE/INSERT в БД
    # 4. _push_hist + notify + send_or_update_card
    # 5. return web.json_response(boot_payload(uid))
```

`jerr(msg, status)` — вернуть ошибку фронту. `_push_hist(table, rid, status, note)` — дописать строку в историю заявки.

## Список эндпоинтов

| Эндпоинт | Строка | Кто может | Что |
|---|---|---|---|
| `api_me` | [687](../bot/main.py) | все | вернуть boot (поллинг 12с) |
| `api_register` | [692](../bot/main.py) | все | регистрация + автосверка |
| `api_req_create` | [741](../bot/main.py) | верифиц. | создать заявку |
| `api_req_update` | [768](../bot/main.py) | владелец | правка до согласования |
| `api_req_action` | [818](../bot/main.py) | зависит | **все действия по заявке** |
| `api_availability` | [801](../bot/main.py) | все | занятость на даты |
| `api_626_create` | [937](../bot/main.py) | верифиц. | бронь студии |
| `api_626_action` | [961](../bot/main.py) | зависит | действия по 626 |
| `api_chat` | [1026](../bot/main.py) | участники | переписка |
| `api_read` | [1064](../bot/main.py) | все | отметить прочитанным |
| `api_verify` | [1077](../bot/main.py) | старший | ok/no/block/unblock |
| `api_appeal` | [1124](../bot/main.py) | все | обращение в команду |
| `api_user_role` | [1152](../bot/main.py) | старший | сменить роль |
| `api_user_delete` | [1169](../bot/main.py) | старший | удалить юзера |
| `api_category_block` | [1184](../bot/main.py) | старший | блок категории |
| `api_equip_add/del/remove/restore` | [1201+](../bot/main.py) | старший | правка каталога |
| `api_favset_add/del` | [1263+](../bot/main.py) | владелец | избранные наборы |
| `api_export` | [1287](../bot/main.py) | старший | CSV-выгрузка |
| `api_broadcast` | [1353](../bot/main.py) | старший | рассылка |
| `api_stats` | [1370](../bot/main.py) | старший | статистика |

## Главный: `api_req_action` ([строка 818](../bot/main.py))

Одна функция — все действия по заявке через `body["action"]`. Разбор по веткам:

| action | Кто | Эффект |
|---|---|---|
| `cancel` | владелец | → canceled (до согласования) |
| `userret` | владелец | → ret, фото куратору + в канал |
| `curator` | админ | взять заявку, → curator |
| `uncurator` | куратор | снять себя, до выдачи → снова в очередь |
| `approved` | админ | → approved |
| `rejected` | админ | → rejected (с причиной) |
| `issue` | админ | выдать: номера экземпляров, правка состава, → issued |
| `return` | админ/старший | принять возврат → closed **или** эскалация старшим |

> [!important] Проблемный возврат (эскалация)
> `return` + комментарий от **не-старшего** → `escalated=1`, заявка уходит старшим, куратор больше не принимает. Сообщение падает в `messages` с `role='admin'`. Сам старший эскалировать не может (см. [[Поток заявки]]).

> [!tip] Правишь логику заявок → почти всегда сюда
> Каждая ветка следует скелету: проверка прав → UPDATE → `_push_hist` → `notify` → в конце всегда `send_or_update_card` + `boot_payload`.

## Как добавить новый эндпоинт

1. Написать `@auth async def api_new(request, body, uid): ...`.
2. Зарегистрировать в `main()`: `app.router.add_post("/api/new", api_new)` ([[Конфиг и запуск]]).
3. На фронте вызвать через `api('/new', {...})`.

Связано: [[Поток заявки]], [[Уведомления и карточки]].
