"""Редактируемые пользовательские тексты и Telegram-разметка Оборудыша."""

import random


APP_BUTTON_TEXT = "📦 Открыть Оборудыш"
DEEPLINK_BUTTON_TEXT = "Открыть в приложении"
MENU_BUTTON_TEXT = "Оборудыш"
PHOTO_FILENAME = "photo.jpg"

STATUS_LABELS = {
    "new": "Новая",
    "curator": "Назначен куратор",
    "approved": "Согласована",
    "issued": "Выдана",
    "ret": "Возврат на проверке",
    "closed": "Закрыта",
    "rejected": "Отклонена",
    "canceled": "Отменена пользователем",
}

GENERIC_ISSUE_WISHES = (
    "Оборудыш желает приятных съёмок и отличных кадров!",
    "Удачной съёмки! Пусть техника работает безупречно, а результат радует.",
    "Оборудыш желает вдохновения, хорошего света и удачных дублей!",
    "Пусть съёмка пройдёт легко, а все задуманные кадры получатся!",
)

CATEGORY_ISSUE_WISHES = {
    "Камеры": ("Красивых кадров и точного фокуса!",),
    "Объективы": ("Точного фокуса, красивого боке и выразительных кадров!",),
    "Свет": ("Пусть свет ляжет идеально с первого раза!",),
    "Звук": ("Чистого звука без помех и лишних дублей!",),
    "Стабилизаторы": ("Плавных проходок и уверенных движений камеры!",),
    "Грипповка": ("Надёжных креплений и спокойно собранной площадки!",),
    "Акумы": ("Пусть заряда хватит на все задуманные дубли!",),
    "Аккумы": ("Пусть заряда хватит на все задуманные дубли!",),
    "Стойки и Штативы": ("Устойчивых кадров и точных движений!",),
    "Штативы": ("Устойчивых кадров и точных движений!",),
    "Хранение данных": ("Пусть все материалы запишутся надёжно и без потерь!",),
    "Сумки": ("Пусть техника доберётся до площадки удобно и безопасно!",),
    "Фоны": ("Пусть фон дополнит идею и поможет собрать цельный кадр!",),
}

LARGE_KIT_WISHES = (
    "Серьёзный комплект! Пусть большая съёмка пройдёт легко и организованно.",
    "Внушительный набор техники — желаем слаженной работы и отличного результата!",
    "Большая съёмка начинается с хорошей подготовки. Удачи всей команде!",
)

STUDIO_626_START_WISHES = (
    "Бронь 626 №{booking_id} началась. Оборудыш желает приятной съёмки и отличных кадров!",
    "Время брони 626 №{booking_id} началось. Хорошего света, чистого звука и удачных дублей!",
    "626 готова к работе по брони №{booking_id}. Пусть съёмка пройдёт легко и продуктивно!",
)

_MARKDOWN_V2_SPECIALS = set("\\_*[]()~`>#+-=|{}.!")


def markdown_v2_escape(value) -> str:
    text = "" if value is None else str(value)
    return "".join("\\" + char if char in _MARKDOWN_V2_SPECIALS else char for char in text)


def markdown_v2_bold(value) -> str:
    return "*%s*" % markdown_v2_escape(value)


def markdown_v2_code(value) -> str:
    value = "" if value is None else str(value)
    return "`%s`" % value.replace("\\", "\\\\").replace("`", "\\`")


def equipment_issue_wish(items, catalog_meta) -> str:
    if len(items) >= 4 or sum(int(qty) for _, qty in items) >= 5:
        return random.choice(LARGE_KIT_WISHES)
    choices = []
    for short, _ in items:
        category = (catalog_meta.get(short) or {}).get("cat")
        choices.extend(CATEGORY_ISSUE_WISHES.get(category, ()))
    return random.choice(choices or GENERIC_ISSUE_WISHES)


def equipment_issued_message(request_id, items, return_at, comment, catalog_meta) -> str:
    lines = "\n".join("  · %s × %s" % (short, qty) for short, qty in items)
    comment_text = "\nКомментарий: " + comment if comment else ""
    return (
        "Оборудование выдано по заявке ID {request_id}:\n"
        "{items}\nВернуть до: {return_at}.{comment}\n\n{wish}"
    ).format(
        request_id=request_id,
        items=lines,
        return_at=return_at,
        comment=comment_text,
        wish=equipment_issue_wish(items, catalog_meta),
    )


def request_return_caption(request_id, comment="") -> str:
    text = "📷 Фото сдачи по заявке ID %s" % request_id
    return text + ("\nКомментарий: " + comment if comment else "")


def studio_return_caption(booking_id, comment="") -> str:
    text = "📷 Фото сдачи аудитории 626 по брони №%s" % booking_id
    return text + ("\nКомментарий: " + comment if comment else "")


def studio_626_start_message(booking_id) -> str:
    return random.choice(STUDIO_626_START_WISHES).format(booking_id=booking_id)


def request_card_message(request_id, status, author, author_ref, date_from, date_to,
                         event, items, comment="", late_note="", curator="") -> str:
    item_lines = "\n".join(
        "• %s × %s" % (markdown_v2_escape(short), markdown_v2_code(qty))
        for short, qty in items
    )
    lines = [
        "%s  %s" % (
            markdown_v2_bold("📦 Заявка · %s" % STATUS_LABELS.get(status, status)),
            markdown_v2_code("ID %s" % request_id),
        ),
        "%s %s · %s" % (
            markdown_v2_bold("От:"), markdown_v2_escape(author or "не указано"),
            markdown_v2_escape(author_ref),
        ),
        "%s %s → %s" % (
            markdown_v2_bold("Когда:"), markdown_v2_code(date_from),
            markdown_v2_code(date_to),
        ),
        "%s %s" % (markdown_v2_bold("Мероприятие:"), markdown_v2_escape(event)),
        "%s\n%s" % (markdown_v2_bold("Состав:"), item_lines),
    ]
    if comment:
        lines.append("%s %s" % (
            markdown_v2_bold("Комментарий:"), markdown_v2_escape(comment),
        ))
    if late_note:
        lines.append("%s %s" % (
            markdown_v2_bold("⚠️ Внимание:"), markdown_v2_escape(late_note + " — команда может отказать"),
        ))
    if curator:
        lines.append("%s %s" % (
            markdown_v2_bold("Куратор:"), markdown_v2_escape(curator),
        ))
    return "\n".join(lines)


def studio_card_message(booking_id, status, author, author_ref, day, slot,
                        goal, needs, curator="") -> str:
    lines = [
        "%s  %s" % (
            markdown_v2_bold("🏛 Бронь 626 · %s" % STATUS_LABELS.get(status, status)),
            markdown_v2_code("№%s" % booking_id),
        ),
        "%s %s · %s" % (
            markdown_v2_bold("От:"), markdown_v2_escape(author or "не указано"),
            markdown_v2_escape(author_ref),
        ),
        "%s %s · %s" % (
            markdown_v2_bold("Когда:"), markdown_v2_code(day), markdown_v2_code(slot),
        ),
        "%s %s" % (markdown_v2_bold("Цель:"), markdown_v2_escape(goal)),
        "%s %s" % (
            markdown_v2_bold("Допы:"),
            markdown_v2_escape(", ".join(needs) if needs else "без допов"),
        ),
    ]
    if curator:
        lines.append("%s %s" % (
            markdown_v2_bold("Куратор:"), markdown_v2_escape(curator),
        ))
    return "\n".join(lines)


# Одноразовое приглашение пользователям старой кнопочной версии.
LEGACY_MIGRATION_MESSAGE = (
    "Неважно, в цепях ты или свободен. Главное, что тебе есть куда расти! "
    "И пришло моё время стать лучшей версией себя. "
    "Надеюсь, вы не будете скучать.\n\n"
    "Нажми /start"
)
