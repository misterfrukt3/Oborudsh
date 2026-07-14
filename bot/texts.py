"""Редактируемые пользовательские тексты Оборудыша.

В этом файле хранятся фразы, которые бот отправляет людям. Служебные значения
статусов, названия таблиц и ключи API сюда намеренно не вынесены: их изменение
сломает логику приложения. Тексты можно переписывать, сохраняя имена переменных
и поля в фигурных скобках у шаблонов.
"""
import random


# Отправляется пользователю сразу после фактической выдачи оборудования,
# если состав не подходит под отдельную категорию или крупный комплект.
GENERIC_ISSUE_WISHES = (
    "Оборудыш желает приятных съёмок и отличных кадров!",
    "Удачной съёмки! Пусть техника работает безупречно, а результат радует.",
    "Оборудыш желает вдохновения, хорошего света и удачных дублей!",
    "Пусть съёмка пройдёт легко, а все задуманные кадры получатся!",
    "Приятных съёмок! Берегите оборудование и творите с удовольствием.",
)


# Готовые фразы по категориям. Название категории в предложение не подставляется,
# поэтому склонения всегда корректны. Если в комплекте несколько категорий,
# бот случайно выбирает подходящую фразу из общего набора найденных категорий.
CATEGORY_ISSUE_WISHES = {
    "Камеры": (
        "Красивых кадров и точного фокуса!",
        "Пусть камера поймает именно тот кадр, который вы задумали!",
    ),
    "Объективы": (
        "Точного фокуса, красивого боке и выразительных кадров!",
        "Пусть каждый выбранный ракурс сработает как надо!",
    ),
    "Свет": (
        "Пусть свет ляжет идеально с первого раза!",
        "Красивого света и выразительной картинки!",
    ),
    "Звук": (
        "Чистого звука без помех и лишних дублей!",
        "Пусть каждый голос прозвучит чисто и разборчиво!",
    ),
    "Стабилизаторы": (
        "Плавных проходок и уверенных движений камеры!",
        "Пусть каждый кадр получится плавным и динамичным!",
    ),
    "Грипповка": (
        "Надёжных креплений и спокойно собранной площадки!",
        "Пусть всё держится крепко, а работа идёт легко!",
    ),
    "Акумы": (
        "Пусть заряда хватит на все задуманные дубли!",
        "Долгой съёмки без внезапно разряженных аккумуляторов!",
    ),
    "Аккумы": (  # алиас на случай исправления названия категории в каталоге
        "Пусть заряда хватит на все задуманные дубли!",
        "Долгой съёмки без внезапно разряженных аккумуляторов!",
    ),
    "Стойки и Штативы": (
        "Устойчивых кадров и точных движений!",
        "Пусть композиция будет идеальной, а кадр — стабильным!",
    ),
    "Штативы": (  # алиас для старых и добавленных вручную позиций
        "Устойчивых кадров и точных движений!",
        "Пусть композиция будет идеальной, а кадр — стабильным!",
    ),
    "Хранение данных": (
        "Пусть все материалы запишутся надёжно и без потерь!",
        "Удачной записи и побольше отличных дублей на карте памяти!",
    ),
    "Сумки": (
        "Пусть техника доберётся до площадки удобно и безопасно!",
        "Лёгкой дороги и аккуратной перевозки всего комплекта!",
    ),
    "Фоны": (
        "Пусть фон дополнит идею и поможет собрать цельный кадр!",
        "Ровной установки и красивой картинки без лишних деталей!",
    ),
}


# Отправляется вместо категорийной фразы, если выдан крупный комплект.
# Порог настраивается двумя числами ниже.
LARGE_KIT_WISHES = (
    "Серьёзный комплект! Пусть большая съёмка пройдёт легко и организованно.",
    "Внушительный набор техники — желаем слаженной работы и отличного результата!",
    "Оборудыш собрал большую корзину техники. Пусть каждый прибор отработает идеально!",
    "Большая съёмка начинается с хорошей подготовки. Удачи всей команде!",
)
LARGE_KIT_MIN_POSITIONS = 4
LARGE_KIT_MIN_UNITS = 5


# Основной текст уведомления после выдачи оборудования.
# Поля request_id, items, return_at, comment и wish заполняются автоматически.
EQUIPMENT_ISSUED_MESSAGE = (
    "Оборудование выдано по заявке ID {request_id}:\n"
    "{items}\n"
    "Вернуть до: {return_at}.{comment}\n\n"
    "{wish}"
)


# Отправляется владельцу согласованной брони 626 один раз после начала слота.
STUDIO_626_START_WISHES = (
    "Бронь 626 №{booking_id} началась. Оборудыш желает приятной съёмки и отличных кадров!",
    "Время брони 626 №{booking_id} началось. Хорошего света, чистого звука и удачных дублей!",
    "626 готова к работе по брони №{booking_id}. Пусть съёмка пройдёт легко и продуктивно!",
    "Бронь 626 №{booking_id} уже идёт. Вдохновения, слаженной работы и красивого результата!",
    "Съёмка в 626 по брони №{booking_id} начинается. Удачи всей команде!",
)


def equipment_issue_wish(items, catalog_meta):
    """Выбирает пожелание по размеру и категориям фактически выданного комплекта."""
    positions = len(items)
    units = sum(int(qty) for _, qty in items)
    if positions >= LARGE_KIT_MIN_POSITIONS or units >= LARGE_KIT_MIN_UNITS:
        return random.choice(LARGE_KIT_WISHES)

    category_pool = []
    for short, _ in items:
        category = (catalog_meta.get(short) or {}).get("cat")
        category_pool.extend(CATEGORY_ISSUE_WISHES.get(category, ()))
    return random.choice(category_pool or GENERIC_ISSUE_WISHES)


def equipment_issued_message(request_id, items, return_at, comment, catalog_meta):
    """Собирает полное личное уведомление после выдачи оборудования."""
    lines = "\n".join("  - %s × %s" % (short, qty) for short, qty in items)
    comment_text = "\nКомментарий: " + comment if comment else ""
    return EQUIPMENT_ISSUED_MESSAGE.format(
        request_id=request_id,
        items=lines,
        return_at=return_at,
        comment=comment_text,
        wish=equipment_issue_wish(items, catalog_meta),
    )


def studio_626_start_message(booking_id):
    """Выбирает одно пожелание при фактическом начале брони аудитории 626."""
    return random.choice(STUDIO_626_START_WISHES).format(booking_id=booking_id)

# ---------------------------------------------------------------------------
# Общие подписи Telegram. Используются в кнопках, меню, карточках и файлах.
# ---------------------------------------------------------------------------
APP_BUTTON_TEXT = "📦 Открыть Оборудыш"
DEEPLINK_BUTTON_TEXT = "Открыть в приложении"
MENU_BUTTON_TEXT = "Оборудыш"
PHOTO_FILENAME = "photo.jpg"
EXPORT_FILENAMES = {"admins": "admins.md", "626": "studio626.md", "requests": "requests.md"}

STATUS_LABELS = {
    "new": "Новая", "curator": "Назначен куратор", "approved": "Согласована",
    "issued": "Выдана", "ret": "Возврат на проверке", "closed": "Закрыта",
    "rejected": "Отклонена", "canceled": "Отменена пользователем",
}


_MARKDOWN_V2_SPECIALS = set("\\_*[]()~`>#+-=|{}.!")


def markdown_v2_escape(value):
    """Экранирует произвольное значение для Telegram MarkdownV2."""
    text = "" if value is None else str(value)
    return "".join("\\" + char if char in _MARKDOWN_V2_SPECIALS else char
                   for char in text)


def markdown_v2_bold(value):
    return "*%s*" % markdown_v2_escape(value)


def markdown_v2_heading(value):
    """Визуальный заголовок: Telegram не поддерживает синтаксис # из Markdown."""
    return "*__%s__*" % markdown_v2_escape(value)


def markdown_v2_code(value):
    text = "" if value is None else str(value)
    return "`%s`" % text.replace("\\", "\\\\").replace("`", "\\`")


def photo_filename(index):
    """Имя файла у второй и последующих фотографий медиагруппы."""
    return "photo%s.jpg" % index


def request_card_message(request_id, status, author_name, author_ref, date_from,
                         date_to, event, items, comment="", late_notes=None,
                         curator=""):
    """Карточка заявки на оборудование в служебном канале (MarkdownV2)."""
    item_lines = "\n".join("• %s × %s" % (
        markdown_v2_escape(short), markdown_v2_code(qty),
    ) for short, qty in items)
    lines = [
        "%s  %s" % (
            markdown_v2_heading("📦 Заявка · %s" % STATUS_LABELS.get(status, status)),
            markdown_v2_code("ID %s" % request_id),
        ),
        "%s %s · %s" % (
            markdown_v2_bold("От:"), markdown_v2_escape(author_name or "?"),
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
        lines.append(">%s %s" % (
            markdown_v2_bold("Комментарий:"), markdown_v2_escape(comment),
        ))
    if late_notes:
        labels = {"return": "поздний возврат (сб после 18:00)",
                  "issue": "поздняя выдача (сб после 18:00)"}
        note = "; ".join(labels[item] for item in late_notes if item in labels)
        if note:
            lines.append(">⚠️ %s" % markdown_v2_escape(
                "%s — команда может отказать" % note))
    if curator:
        lines.append("%s %s" % (
            markdown_v2_bold("Куратор:"), markdown_v2_escape(curator),
        ))
    return "\n".join(lines)


def studio_card_message(booking_id, status, author_name, author_ref, day, slot,
                        goal, needs, curator=""):
    """Карточка брони аудитории 626 в служебном канале (MarkdownV2)."""
    lines = [
        "%s  %s" % (
            markdown_v2_heading("🏛 Бронь 626 · %s" % STATUS_LABELS.get(status, status)),
            markdown_v2_code("№%s" % booking_id),
        ),
        "%s %s · %s" % (
            markdown_v2_bold("От:"), markdown_v2_escape(author_name or "?"),
            markdown_v2_escape(author_ref),
        ),
        "%s %s · %s" % (
            markdown_v2_bold("Когда:"), markdown_v2_code(day),
            markdown_v2_code(slot),
        ),
        "%s %s" % (markdown_v2_bold("Цель:"), markdown_v2_escape(goal)),
        "%s %s" % (
            markdown_v2_bold("Дополнительно:"),
            markdown_v2_escape(", ".join(needs) or "без дополнительного оборудования"),
        ),
    ]
    if curator:
        lines.append("%s %s" % (
            markdown_v2_bold("Куратор:"), markdown_v2_escape(curator),
        ))
    return "\n".join(lines)


# Регистрация, верификация и управление пользователями.
def verification_request_message(name, user_ref, orgs, missing_mb):
    """Новая заявка на ручную верификацию в служебный канал."""
    reason = " · не найден в таблице Media BMSTU" if missing_mb else ""
    return ("⏳ Заявка на верификацию: %s (%s), орг.: %s%s. "
            "Решение — в приложении.") % (name, user_ref, ", ".join(orgs), reason)


def verification_approved_message(role):
    """Личное сообщение после успешной ручной верификации."""
    return "✅ Верификация пройдена! Роль: %s. Приложение открыто — можно бронировать." % role


def verification_rejected_message(reason=""):
    """Личное сообщение после отказа в верификации."""
    suffix = " Причина: %s." % reason if reason else ""
    return "Заявка на верификацию отклонена.%s Можно исправить данные и подать заново." % suffix


def user_blocked_message(until="", reason=""):
    """Личное сообщение при блокировке пользователя."""
    until_text = " до %s" % until if until else ""
    reason_text = ". Причина: %s" % reason if reason else ""
    return "Вы заблокированы в Оборудыше%s%s. По вопросам — @Kyuller" % (until_text, reason_text)


def user_unblocked_message():
    """Личное сообщение после разблокировки пользователя."""
    return "✅ Вас разблокировали в Оборудыше — доступ снова открыт."


def user_role_updated_message(role):
    """Личное сообщение после изменения роли."""
    return "Ваша роль обновлена: %s." % role


def verification_missing_after_resync_message(user_ref):
    """Канал: человек исчез из источника верификации."""
    return "⚠️ %s пропал из списка верификации — статус изменён на pending." % user_ref


# Жизненный цикл заявки на оборудование.
def request_updated_for_curator_message(request_id):
    """Куратору после редактирования заявки пользователем."""
    return "✏️ Заявка ID %s изменена пользователем — проверьте актуальные детали." % request_id


def request_canceled_for_curator_message(request_id):
    """Куратору после отмены заявки пользователем."""
    return "Заявка ID %s отменена пользователем." % request_id


def request_return_caption(request_id, comment="", photo_count=1):
    """Форматированная подпись к фотографиям сдачи оборудования."""
    lines = [
        markdown_v2_heading("📷 Сдача оборудования"),
        "%s · %s" % (
            markdown_v2_code("ID %s" % request_id),
            markdown_v2_code("%s фото" % photo_count),
        ),
    ]
    if comment:
        lines.append(">%s %s" % (
            markdown_v2_bold("Комментарий:"), markdown_v2_escape(comment),
        ))
    return "\n".join(lines)


def request_return_submitted_message(request_id):
    """Куратору после отправки фотографий сдачи."""
    return ("📷 Пользователь сдал оборудование по заявке ID %s. "
            "Проверьте фотографии и комплект в приложении.") % request_id


def request_curator_assigned_message(request_id, curator):
    """Пользователю после назначения куратора."""
    return ("По заявке ID %s назначен куратор %s. Откройте Оборудыш, "
            "чтобы посмотреть детали.") % (request_id, curator)


def request_curator_left_message(request_id):
    """Пользователю, когда куратор снял себя."""
    return "По заявке ID %s куратор снял себя. Заявка возвращена в очередь." % request_id


def request_curator_left_channel_message(request_id):
    """Каналу, когда заявка снова осталась без куратора."""
    return "⚠️ Заявка ID %s снова без куратора — возьмите её в работу." % request_id


def request_approved_message(request_id, date_from):
    """Пользователю после согласования заявки."""
    return "✅ Заявка ID %s согласована! Получение: %s." % (request_id, date_from)


def request_rejected_message(request_id, reason=""):
    """Пользователю после отклонения заявки."""
    suffix = " Причина: %s" % reason if reason else ""
    return "⛔ Заявка ID %s отклонена.%s" % (request_id, suffix)


def problem_return_message(request_id, comment):
    """Старшим администраторам при проблемном возврате."""
    return ("⚠️ Проблемный возврат по заявке ID %s: «%s». "
            "Откройте заявку в приложении.") % (request_id, comment)


def request_closed_message(request_id):
    """Пользователю после успешной приёмки оборудования."""
    return "✅ Возврат по заявке ID %s принят, заявка закрыта. Спасибо!" % request_id


# Жизненный цикл брони аудитории 626.
def new_studio_booking_message(booking_id, day, slot):
    """Старшим администраторам о новой брони 626."""
    return "🏛 Новая бронь 626 №%s: %s %s — согласуйте её в приложении." % (booking_id, day, slot)


def studio_return_caption(booking_id, comment="", photo_count=1):
    """Форматированная подпись к фотографиям сдачи аудитории 626."""
    lines = [
        markdown_v2_heading("📷 Сдача аудитории 626"),
        "%s · %s" % (
            markdown_v2_code("№%s" % booking_id),
            markdown_v2_code("%s фото" % photo_count),
        ),
    ]
    if comment:
        lines.append(">%s %s" % (
            markdown_v2_bold("Комментарий:"), markdown_v2_escape(comment),
        ))
    return "\n".join(lines)


def studio_return_submitted_message(booking_id):
    """Куратору после отправки фотографий аудитории."""
    return ("📷 По брони 626 №%s пользователь отправил фотографии сдачи. "
            "Проверьте аудиторию в приложении.") % booking_id


def studio_approved_message(booking_id, day, slot):
    """Пользователю после согласования брони 626."""
    return ("✅ Бронь 626 №%s (%s, %s) согласована! Аудитория закреплена "
            "за вами на это время.") % (booking_id, day, slot)



def studio_rejected_message(booking_id, day, slot, reason=""):
    """Пользователю после отклонения брони 626."""
    suffix = " Причина: %s" % reason if reason else ""
    return "⛔ Бронь 626 №%s (%s, %s) отклонена.%s" % (booking_id, day, slot, suffix)


def studio_curator_assigned_message(booking_id, curator):
    """Пользователю после назначения куратора брони 626."""
    return "По брони 626 №%s назначен куратор %s." % (booking_id, curator)


def studio_closed_message(booking_id):
    """Пользователю после успешной приёмки аудитории."""
    return "✅ Бронь 626 №%s завершена. Спасибо, приходите ещё!" % booking_id


# Переписка внутри заявок.
def conversation_label(kind, ref):
    """Название заявки для Telegram-уведомлений чата."""
    return "заявке ID %s" % ref if kind == "req" else "брони 626 №%s" % ref


def chat_from_user_message(label, sender, message):
    """Куратору о сообщении пользователя."""
    return "💬 Сообщение по %s от %s:\n«%s»" % (label, sender, message)


def chat_to_user_message(role, label, message):
    """Пользователю о сообщении куратора или старшего."""
    return "💬 %s по %s:\n«%s»\nОтветить можно в приложении." % (role, label, message)


def chat_senior_joined_message(label, message):
    """Куратору, когда подключился старший."""
    return "💬 Старший подключился к %s:\n«%s»" % (label, message)


# Обращения, блокировки категорий и рассылки.
def appeal_sender(anonymous, name, user_ref):
    """Подпись автора обращения."""
    return "аноним" if anonymous else "%s (%s)" % (name, user_ref)


def appeal_card_message(sender, message):
    """Карточка обращения в служебном канале."""
    return "💬 Обращение в команду Оборудыша\nОт: %s\n\n%s" % (sender, message)


def category_blocked_message(category, term):
    """Канал: блокировка категории оборудования."""
    return "🔒 Категория «%s» заблокирована %s" % (category, term)


def export_caption(kind):
    """Подпись к отправленному файлу выгрузки."""
    labels = {"requests": "заявки", "626": "брони 626", "admins": "администраторы"}
    return "📊 Выгрузка «%s» из Оборудыша" % labels.get(kind, kind)


def broadcast_message(message):
    """Текст рассылки каждому пользователю."""
    return "📣 %s" % message

# ---------------------------------------------------------------------------
# Планировщик: напоминания пользователям, кураторам и служебному каналу.
# ---------------------------------------------------------------------------
def user_return_in_hour_message(request_id, deadline):
    """Пользователю за час до возврата оборудования."""
    return ("Через час нужно вернуть оборудование по заявке ID %s — до %s. "
            "Откройте Оборудыш, зайдите в карточку заявки и нажмите "
            "«Сдать оборудование», приложив фото комплекта.") % (request_id, deadline)


def user_return_overdue_message(request_id, deadline):
    """Пользователю при просрочке возврата."""
    return ("Возврат по заявке ID %s просрочен: срок был %s. Как можно скорее "
            "откройте карточку заявки в Оборудыше, нажмите «Сдать оборудование» "
            "и приложите фото комплекта.") % (request_id, deadline)


def curator_issue_day_message(request_id, date_from):
    """Куратору за сутки до выдачи."""
    return ("Заявка ID %s: выдача через сутки, %s. Подготовьте комплект и "
            "откройте эту заявку в Оборудыше к времени выдачи.") % (request_id, date_from)


def curator_issue_hour_message(request_id, date_from):
    """Куратору за час до выдачи."""
    return ("Заявка ID %s: через час нужно выдать оборудование, время %s. "
            "Откройте заявку в Оборудыше и нажмите «Выдать оборудование».") % (request_id, date_from)


def curator_return_day_message(request_id, deadline):
    """Куратору за сутки до возврата."""
    return ("Заявка ID %s: возврат через сутки, %s. Откройте заявку в "
            "Оборудыше и будьте готовы принять комплект.") % (request_id, deadline)


def curator_return_hour_message(request_id, deadline):
    """Куратору за час до возврата."""
    return ("Заявка ID %s: через час возврат, время %s. Откройте заявку в "
            "Оборудыше; после сдачи проверьте комплект и нажмите «Принять возврат».") % (request_id, deadline)


def stale_request_without_curator_message(request_id, hours):
    """Канал: заявка шесть часов без куратора."""
    return "Заявка ID %s без куратора уже %s ч — возьмите в работу." % (request_id, hours)


def stale_request_unapproved_message(request_id, curator):
    """Канал: куратор долго не согласовывает заявку."""
    return "Заявка ID %s у куратора %s не согласована — проверьте." % (request_id, curator)


def request_auto_canceled_message(request_id, reason):
    """Пользователю после автоматической отмены."""
    return ("Заявка ID %s отменена автоматически: %s. Оборудование освобождено — "
            "можно подать заявку заново.") % (request_id, reason)


def studio_finished_user_message(booking_id):
    """Пользователю сразу после окончания слота 626."""
    return ("Бронь 626 №%s завершилась. Откройте её карточку в Оборудыше, "
            "нажмите «Сдать аудиторию» и приложите фото убранного помещения.") % booking_id


def studio_finished_curator_message(booking_id, day, slot):
    """Куратору сразу после окончания слота 626."""
    return ("Бронь 626 №%s завершилась (%s %s). Откройте бронь в Оборудыше "
            "и после фотографий пользователя примите аудиторию.") % (booking_id, day, slot)


def stale_studio_booking_message(booking_id, day, slot):
    """Канал: бронь 626 долго ждёт согласования."""
    return "Бронь 626 №%s ждёт согласования старшими (%s %s)." % (booking_id, day, slot)


# ---------------------------------------------------------------------------
# Сводки и экспортируемые текстовые файлы.
# ---------------------------------------------------------------------------
def daily_digest_message(issued, approved, curator, awaiting_return, admin_day,
                         equipment_bookings, studio_bookings):
    """Полный текст ежедневной сводки в служебный канал (MarkdownV2)."""
    admin_text = ""
    if admin_day:
        admin_text = "\n\n🏆 %s %s\n%s" % (
            markdown_v2_bold("Админ дня:"), markdown_v2_escape(admin_day["name"]),
            markdown_v2_code("К/В/П/О/А: {k}/{v}/{p}/{o}/{a}".format(**admin_day)),
        )
    equipment_blocks = []
    for booking in equipment_bookings:
        lines = ["• %s · %s" % (
            markdown_v2_code("ID %s" % booking["id"]),
            markdown_v2_escape(booking["user"]),
        )]
        for item in booking["items"]:
            if item["qty"] == 1 and item.get("num"):
                item_text = "%s №%s" % (item["short"], item["num"])
            else:
                item_text = "%s × %s" % (item["short"], item["qty"])
            lines.append("  ↳ %s" % markdown_v2_escape(item_text))
        lines.append("%s %s" % (
            markdown_v2_bold("Мероприятие:"), markdown_v2_escape(booking["event"])))
        lines.append("%s %s" % (markdown_v2_bold("Время:"), markdown_v2_code(
            "%s, %s — %s, %s" % (
                booking["date_from"], booking["time_from"],
                booking["date_to"], booking["time_to"],
            ))))
        equipment_blocks.append("\n".join(lines))
    equipment_text = "\n\n".join(equipment_blocks) if equipment_blocks else "— нет"
    studio_lines = ["• %s · %s\n  ↳ %s" % (
        markdown_v2_code("%s–%s" % (item["start"], item["end"])),
        markdown_v2_escape(item["user"]), markdown_v2_escape(item["goal"]),
    ) for item in studio_bookings]
    studio_text = "\n".join(studio_lines) if studio_lines else "— свободно"
    return ("{title}\n\n"
            "• Активных бронирований: {issued}\n"
            "• Ожидают выдачи: {approved}\n"
            "• Согласовано: {curator}\n"
            "• Выдано: {issued}\n"
            "• Ожидают возврата: {awaiting_return}{admin}\n\n"
            "{equipment_title}\n{equipment}\n\n"
            "{studio_title}\n{studio}").format(
                title=markdown_v2_heading("📊 Ежедневная статистика Оборудыша"),
                issued=issued, approved=approved, curator=curator,
                awaiting_return=awaiting_return, admin=admin_text,
                equipment_title=markdown_v2_heading("📅 Оборудование на завтра"),
                equipment=equipment_text, studio=studio_text,
                studio_title=markdown_v2_heading("🏛 Аудитория 626 на завтра"),
            )


def monthly_digest_message(month, requests_count, studio_count, top_items):
    """Полный текст ежемесячной сводки в служебный канал (MarkdownV2)."""
    text = "%s\n• Заявки: %s\n• Брони 626: %s" % (
        markdown_v2_heading("📈 Итоги месяца · %s" % month),
        requests_count, studio_count)
    if top_items:
        text += "\n\n%s\n" % markdown_v2_heading("Топ оборудования:")
        text += "\n".join("• %s · %s" % (
            markdown_v2_escape(item), markdown_v2_code("%s шт" % count),
        ) for item, count in top_items)
    return text


def export_admins_file(admin_stats):
    """Имя и содержимое файла статистики администраторов."""
    top = [item for item in sorted(admin_stats, key=lambda row: -row["rejected"])
           if item["rejected"] > 0]
    lines = ["АДМИНИСТРАТОРЫ ОБОРУДЫША", ""]
    for item in admin_stats:
        lines.append("{name}\nКурировал: {curated}\nВыдал: {issued}\nПринял: "
                     "{returned}\nОтказал: {rejected}\n---".format(**item))
    if top:
        lines.extend(["", "ТОП ПО ОТКАЗАМ"])
        for index, item in enumerate(top, 1):
            lines.append("%s. %s — %s" % (index, item["name"], item["rejected"]))
    return EXPORT_FILENAMES["admins"], "\n".join(lines)


def export_studio_file(bookings):
    """Имя и содержимое файла всех броней 626."""
    lines = ["БРОНИ 626", ""]
    for item in bookings:
        lines.append("Бронь #{id}\nАвтор: {author}\nДень: {day}\nСлот: {slot}\n"
                     "Цель: {goal}\nСтатус: {status}\nКуратор: {curator}\n---".format(**item))
    return EXPORT_FILENAMES["626"], "\n".join(lines)


def export_requests_file(requests):
    """Имя и содержимое файла всех заявок на оборудование."""
    lines = ["ЗАЯВКИ ОБОРУДЫША", ""]
    for item in requests:
        lines.append("Заявка #{id}\nАвтор: {author}\nМероприятие: {event}\n"
                     "Даты: {date_from} → {date_to}\nСтатус: {status}\n"
                     "Куратор: {curator}\nСостав: {items}\n---".format(**item))
    return EXPORT_FILENAMES["requests"], "\n".join(lines)


# ---------------------------------------------------------------------------
# Ответы на личные команды Telegram-бота.
# ---------------------------------------------------------------------------
def start_message():
    """Ответ на /start."""
    return ("Привет! Это «Оборудыш» — бронирование съёмочного оборудования и "
            "студии 626 Media BMSTU.\n\nВсё происходит в приложении — открывай:")


def chat_id_message(chat_id):
    """Ответ на /chatid."""
    return "chat_id этого чата: <code>%s</code>" % chat_id


def digest_done_message():
    """Подтверждение ручного запуска сводки."""
    return "Сводка отправлена в канал."


def backup_done_message():
    """Подтверждение ручного бэкапа."""
    return "Бэкап базы сделан."


def checks_done_message():
    """Подтверждение ручного запуска проверок."""
    return "Плановые проверки прогнаны."


def add_admin_usage_message():
    """Подсказка по /addadmin."""
    return "Использование: /addadmin <id>"


def admin_added_message(user_id):
    """Подтверждение добавления администратора."""
    return "%s теперь админ." % user_id


def delete_admin_usage_message():
    """Подсказка по /deladmin."""
    return "Использование: /deladmin <id>"


def admin_deleted_message(user_id):
    """Подтверждение удаления администратора."""
    return "%s больше не админ." % user_id


def admins_list_message(senior_ids, env_admin_ids, extra_admin_ids):
    """Ответ на /admins со всеми источниками прав."""
    def joined(values):
        return ", ".join(str(value) for value in sorted(values)) or "—"
    return "\n".join([
        "Старшие (.env): " + joined(senior_ids),
        "Админы (.env): " + joined(env_admin_ids),
        "Админы (добавлены /addadmin): " + joined(extra_admin_ids),
    ])


def forwarded_chat_id_message(chat_id):
    """Ответ на пересланное сообщение для настройки ADMIN_CHAT_ID."""
    return ("id этого канала/чата: <code>%s</code>\n"
            "Впишите его в ADMIN_CHAT_ID в .env и перезапустите бота.") % chat_id


def private_fallback_message():
    """Ответ на произвольное личное сообщение боту."""
    return "Я только открываю приложение и присылаю уведомления. Всё остальное — внутри:"


# Служебные значения, которые попадают в экспортируемые Telegram-файлы.
UNKNOWN_VALUE = "?"
EMPTY_VALUE = "—"


def export_items_text(items):
    """Состав комплекта в файле выгрузки заявок."""
    return "; ".join("%s×%s" % (short, qty) for short, qty in items)


def category_block_term_label(hours=None, date_text="", forever=False):
    """Читаемая длительность блокировки категории для БД, сайта и сообщения в канал."""
    if hours:
        return "на %s %s" % (hours, "час" if hours == 1 else "часов")
    if date_text:
        return "до %s" % date_text
    if forever:
        return "навсегда"
    return ""


def auto_cancel_reason(kind):
    """Причина автоматической отмены, вставляемая в уведомление пользователю."""
    if kind == "review_timeout":
        return "не рассмотрена за 3 дня"
    if kind == "issue_timeout":
        return "срок получения истёк"
    return ""