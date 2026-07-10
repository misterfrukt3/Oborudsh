---
title: Гайд — стилизация бота в Telegram
часть: Гайд
tags:
  - оборудыш
  - гайд
  - брендинг
  - промты
aliases:
  - Оформление бота
  - BotFather стиль
---

# 🎨 Гайд — крутая стилизация бота в Telegram

Как «упаковать» бота в самом Telegram: имя, описание, команды, аватарка, картинка-превью. Всё делается в **@BotFather** (текст/картинки) — код трогать не надо. Ниже готовые промты для нейронки: отдельно **текст** и отдельно **аватар/картинка**.

> [!info] Что вообще настраивается в @BotFather
> - **Name** — имя бота (до 64 симв.).
> - **About** — короткая строка в профиле (до 120 симв.).
> - **Description** — текст на экране до `/start` (до 512 симв.).
> - **Description Picture** — картинка/видео над описанием (до `/start`).
> - **Botpic** — аватарка бота (квадрат, ≥512×512).
> - **Commands** — список команд с описаниями.
> - **Menu Button** — кнопка-меню (уже ведёт в Mini App «Оборудыш»).

---

## 🧩 Бренд-контекст (давать нейронке в любой промт)

```
Бот: «Оборудыш» — Telegram Mini App для бронирования съёмочного оборудования и студии 626
медиацентра 626 Media BMSTU (МГТУ им. Баумана). Аудитория — студенты-медийщики, актив студсоветов.
Название — игра слов: «оборудование» + фольклорный «оборотыш/подменыш» (милый проныра, что «подменяет» технику).
Тон: дружелюбный, по-студенчески живой, но по делу; без канцелярита и без перебора эмодзи.
Фирменный стиль: чёрный фон, один кислотно-зелёный акцент #43ed4e, шрифт Montserrat,
тонкие line-art иконки (камера/объектив/свет), эстетика сайта mediabmstu.ru — тёмная, техно, минимализм.
Функции: заявка на технику по датам, каталог, студия 626, кураторы, статусы заявок, фото сдачи.
Почти всё живёт внутри Mini App; в чат бот шлёт только уведомления.
```

---

## ✍️ Промт 1 — тексты (name / about / description / команды)

```
<вставь бренд-контекст выше>

Задача: напиши тексты для оформления Telegram-бота в @BotFather. Дай 3 варианта на каждый пункт,
уложись строго в лимиты символов. Ничего не выдумывай про функции сверх контекста.

1) NAME (≤64): имя бота. Основа — «Оборудыш», можно с хвостом («Оборудыш · 626 Media»).
2) ABOUT (≤120): одна ёмкая строка-слоган для профиля. Живо, с характером.
3) DESCRIPTION (≤512): текст на экране до /start. Структура: крючок-строка → что умеет (2–4 буллета)
   → мягкий призыв нажать «Открыть». Буллеты — с line-art-настроением (🎥/💡/🎙 максимум пары штук).
4) COMMANDS: описания для команд бота (по 1 короткой строке, ≤50 симв., с маленькой буквы, без точки):
   - start — что делает
   (если предложишь новые команды типа help/app — дай и их описания, но пометь «опционально»).
5) Бонус: 3 варианта приветствия для ответа на /start (2–3 строки), в тон бренда.

Формат вывода: по пунктам, каждый вариант с подписью «Вариант A/B/C» и счётчиком символов в скобках.
```

> [!tip] Текущие команды бота
> Сейчас в коде только `/start` и `/chatid` (служебная, её в публичный список не добавляй). Всё остальное — в Mini App. См. [[Фронтенд — карта]].

---

## 🖼️ Промт 2 — аватарка бота (Botpic)

Для Midjourney / DALL·E / Gemini / Flux и т.п. Квадрат, читается в маленьком кружке.

```
A minimalist app-icon style avatar for a student film-equipment booking bot called "Оборудыш".
Square 1:1, centered, works as a small circular Telegram avatar.
Subject: a single bold line-art camera (or camera + lens) icon, thin even strokes, slightly playful,
hinting at a friendly little "gremlin/changeling" mascot without being cartoonish.
Color: pure black background (#000000), one acid-green accent (#43ed4e) for the icon and a subtle glow.
Style: modern tech minimalism, flat, high contrast, clean negative space, no text, no gradients clutter,
crisp at small sizes. Vibe of mediabmstu.ru — dark, techy, confident.
Avoid: photorealism, busy detail, multiple colors, drop-shadow realism, watermarks, letters.
Output: high-res, centered, safe margins so nothing is cut by a circular crop.
```

> [!note] Варианты аватара
> Попроси нейронку 4 версии: (1) камера, (2) камера+объектив, (3) абстрактный маскот-«оборудыш» из линий, (4) монограмма «О» в стиле объектива. Выбери ту, что читается в кружке 40×40.

---

## 🎞️ Промт 3 — картинка-превью под описание (Description Picture)

Горизонтальная, показывается над текстом до `/start`.

```
A horizontal hero banner (about 16:9) for the "Оборудыш" film-gear booking bot.
Pure black background (#000000) with one acid-green accent (#43ed4e).
Composition: a tidy flat-lay / line-art arrangement of film gear silhouettes — camera, lens,
LED light, microphone, tripod — drawn as thin consistent line-art in green on black,
loosely arranged with lots of negative space. Optional faint "626" studio motif.
Mood: dark, techy, student-media, minimal, premium. Montserrat-like clean feel.
No text baked in (or leave clean space top-left for a title). No clutter, no realism, no gradients mess.
Crisp vector-like look, high resolution.
```

---

## ✅ Порядок настройки в @BotFather

1. `/setname` → Name.
2. `/setabouttext` → About (≤120).
3. `/setdescription` → Description (≤512).
4. `/setuserpic` → загрузить Botpic (аватар).
5. `/setdescriptionpic` → загрузить Description Picture (превью до /start).
6. `/setcommands` → список команд (по строке `команда - описание`).
7. Проверить Menu Button (`/mybots` → Bot Settings → Menu Button) — ведёт на Mini App «Оборудыш».

> [!warning] Тема самого Mini App — уже в коде
> Цвета внутри приложения (чёрный фон, зелёный акцент, шапка) задаёт фронт через `TG.setHeaderColor/setBackgroundColor` и токены — см. [[Фронтенд — стили и токены]]. @BotFather на внешний вид Mini App не влияет, только на обёртку бота в чате.

Связано: [[Фронтенд — карта]], [[Гайд — куда развивать]].
