"""One off-site rental, isolated from normal equipment reservations."""
import asyncio
import json
import re
import secrets
import sqlite3
import time
from datetime import datetime

TESTERS = {1896340090, 1122855409, 5027289530, 849637263, 566220990, 489836280}
NEEDS = ['Камера (видео)', 'Камера (фото)', 'Звук', 'Свет (маленький)',
         'Свет (большой)', 'Штатив', 'Стабилизатор', 'Другое']
ACTIVE = ('new', 'assembling', 'ready', 'issued')
LABELS = dict(new='Подана', assembling='Собирается', ready='Готова к выдаче',
              issued='Выдана', returned='Возвращена', rejected='Отказ', canceled='Отменена')


class MediaTrip:
    def __init__(self, context):
        self.c = context
        self.lock = asyncio.Lock()

    def db(self):
        return self.c['db']()

    def schema(self):
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS trip_settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trip_teams(number INTEGER PRIMARY KEY, curator INTEGER NOT NULL, code TEXT UNIQUE NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS trip_members(uid INTEGER PRIMARY KEY, team INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS trip_blocks(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS trip_items(id INTEGER PRIMARY KEY, name TEXT NOT NULL, total INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS trip_requests(id INTEGER PRIMARY KEY, team INTEGER NOT NULL, block INTEGER NOT NULL,
                author INTEGER NOT NULL, needs TEXT NOT NULL, purpose TEXT NOT NULL, wanted TEXT NOT NULL,
                kit TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'new', reason TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS trip_one_active ON trip_requests(team,block)
                WHERE status IN ('new','assembling','ready','issued');
            CREATE TABLE IF NOT EXISTS trip_history(id INTEGER PRIMARY KEY, ref INTEGER NOT NULL, uid INTEGER NOT NULL, status TEXT NOT NULL, stamp REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS trip_outbox(key TEXT PRIMARY KEY, recipient INTEGER NOT NULL, text TEXT NOT NULL,
                ref INTEGER, guard TEXT NOT NULL DEFAULT '', sent INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, retry REAL NOT NULL DEFAULT 0, expires REAL NOT NULL DEFAULT 0);
            ''')
            if 'deleted' not in {r['name'] for r in c.execute('PRAGMA table_info(trip_teams)')}:
                c.execute('ALTER TABLE trip_teams ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0')
            if 'expires' not in {r['name'] for r in c.execute('PRAGMA table_info(trip_outbox)')}:
                c.execute('ALTER TABLE trip_outbox ADD COLUMN expires REAL NOT NULL DEFAULT 0')
            c.execute('INSERT OR IGNORE INTO trip_settings VALUES(1,?)', (json.dumps(
                dict(testing=True, staff=[], place='', channel=0), ensure_ascii=False),))

    def settings(self):
        with self.db() as c:
            return json.loads(c.execute('SELECT data FROM trip_settings WHERE id=1').fetchone()[0])

    def allowed(self, uid, settings=None):
        s = settings or self.settings()
        user = self.c['get_user'](uid)
        return not (user and user['verified'] == 'blocked') and (not s['testing'] or uid in TESTERS)

    def manager(self, uid, settings=None):
        s = settings or self.settings()
        return self.allowed(uid, s) and (uid in s['staff'] or (s['testing'] and uid in TESTERS))

    def current_block(self, now=None):
        now = time.time() if now is None else now
        with self.db() as c:
            # Current block takes precedence; otherwise only the closest future one.
            return c.execute('SELECT * FROM trip_blocks WHERE end>? ORDER BY start LIMIT 1', (now,)).fetchone()

    def members(self, c, team):
        return {r[0] for r in c.execute('SELECT uid FROM trip_members WHERE team=?', (team,))}

    def enqueue(self, c, key, recipients, text, ref=None, guard='', expires=0):
        for uid in set(recipients) - {0}:
            # Telegram limits ordinary text to 4096 characters.
            for part, offset in enumerate(range(0, len(text), 3500)):
                c.execute('INSERT OR IGNORE INTO trip_outbox(key,recipient,text,ref,guard,expires) VALUES(?,?,?,?,?,?)',
                          (f'{key}:{uid}:{part}', uid, text[offset:offset+3500], ref, guard, expires))

    def fmt(self, stamp):
        return datetime.fromtimestamp(stamp, self.c['MSK']).strftime('%d.%m %H:%M')

    def payload(self, uid):
        s = self.settings()
        if not self.allowed(uid, s):
            return {'allowed': False}
        manage = self.manager(uid, s)
        with self.db() as c:
            member = c.execute('SELECT team FROM trip_members WHERE uid=?', (uid,)).fetchone()
            team = member[0] if member else None
            teams = [dict(r) for r in c.execute('SELECT * FROM trip_teams WHERE deleted=0 ORDER BY number')
                     if manage or r['number'] == team]
            for t in teams:
                t['members'] = [{'id': n, 'name': self.c['_disp_user'](n)} for n in sorted(self.members(c, t['number']))]
                if not manage and t['curator'] != uid:
                    t.pop('code', None)
            blocks = [dict(r) for r in c.execute('SELECT * FROM trip_blocks ORDER BY start')]
            items = [dict(r) for r in c.execute('SELECT * FROM trip_items ORDER BY name') if manage or r['active']]
            reqs = [dict(r) for r in c.execute('SELECT * FROM trip_requests ORDER BY id DESC') if manage or r['team'] == team]
            for r in reqs:
                for k in ('needs', 'wanted', 'kit'):
                    r[k] = json.loads(r[k])
                r['history'] = [dict(h) for h in c.execute('SELECT uid,status,stamp FROM trip_history WHERE ref=? ORDER BY id', (r['id'],))]
            unsent = c.execute('SELECT COUNT(*) FROM trip_outbox WHERE sent=0').fetchone()[0] if manage else 0
        block = self.current_block()
        return dict(allowed=True, canManage=manage, canConfigure=uid in TESTERS, team=team,
                    teams=teams, blocks=blocks, items=items, requests=reqs, needs=NEEDS,
                    currentBlock=block['id'] if block else None, settings=s if manage or uid in TESTERS else {'place': s['place']},
                    unsent=unsent)

    def ids(self, value):
        values = value if isinstance(value, list) else re.split(r'[\s,;]+', str(value).strip())
        out = set()
        for v in values:
            if not v:
                continue
            if str(v).startswith('@'):
                with self.db() as c:
                    rows = c.execute('SELECT id FROM users WHERE lower(username)=?', (str(v)[1:].lower(),)).fetchall()
                if len(rows) != 1:
                    raise ValueError(f'Не нашли {v}. Укажите Telegram ID.')
                out.add(rows[0][0])
            else:
                n = int(v)
                if n <= 0:
                    raise ValueError('Укажите личный Telegram ID.')
                out.add(n)
        return sorted(out)

    def stamp(self, value):
        return datetime.strptime(value, '%Y-%m-%dT%H:%M').replace(tzinfo=self.c['MSK']).timestamp()

    def kit(self, c, values, request):
        if not isinstance(values, list) or len(values) > 200:
            raise ValueError('Некорректный состав оборудования.')
        result, seen = [], set()
        for value in values:
            if not isinstance(value, list) or len(value) != 2 or type(value[0]) is not int or type(value[1]) is not int:
                raise ValueError('Количество оборудования должно быть целым числом.')
            ident, qty = int(value[0]), int(value[1])
            if ident in seen or qty < 1 or qty > 999:
                raise ValueError('Проверьте количество и повторы оборудования.')
            seen.add(ident)
            item = c.execute('SELECT * FROM trip_items WHERE id=? AND active=1', (ident,)).fetchone()
            if not item:
                raise ValueError('Позиция удалена из каталога выезда.')
            others = c.execute("""SELECT r.kit FROM trip_requests r JOIN trip_blocks b ON b.id=r.block
                WHERE r.id<>? AND (r.status='issued' OR (r.status='ready' AND b.end>? AND b.start<?))""",
                (request['id'], request['start'], request['end'])).fetchall()
            used = sum(q for r in others for i, q in json.loads(r['kit']) if i == ident)
            if used + qty > item['total']:
                raise ValueError(f"{item['name']}: доступно {max(0, item['total'] - used)}.")
            result.append([ident, qty])
        return result

    async def handle(self, body, uid):
        try:
            async with self.lock:
                result = self.mutate(body, uid)
            return result
        except (ValueError, TypeError, KeyError, IndexError, sqlite3.IntegrityError) as exc:
            return self.c['jerr'](str(exc) if not isinstance(exc, sqlite3.IntegrityError) else 'У команды уже есть активная заявка на этот блок.')

    def mutate(self, body, uid):
        s = self.settings()
        if not self.allowed(uid, s):
            return self.c['jerr']('Режим пока доступен только участникам тестирования.', 403)
        action = body.get('action')
        manage = self.manager(uid, s)
        if action in ('team', 'delete_team', 'block', 'item') and not manage:
            return self.c['jerr']('Доступно только команде рентала.', 403)
        with self.db() as c:
            if action == 'settings':
                if uid not in TESTERS and not manage:
                    return self.c['jerr']('Недостаточно прав.', 403)
                staff = self.ids(body.get('staff', []))
                testing = bool(body.get('testing', True))
                if not testing and not staff:
                    raise ValueError('Перед открытием режима назначьте команду рентала.')
                channel = int(body.get('channel', 0))
                if channel > 0:
                    raise ValueError('Укажите ID канала или группы, начиная с минуса.')
                s = dict(testing=testing, staff=staff, channel=channel, place=str(body.get('place', '')).strip()[:300])
                c.execute('UPDATE trip_settings SET data=? WHERE id=1', (json.dumps(s, ensure_ascii=False),))
            elif action == 'team':
                number = int(body['number'])
                cur = self.ids([body['curator']])
                if number < 1 or number > 999 or len(cur) != 1:
                    raise ValueError('Укажите номер команды и куратора.')
                old = c.execute('SELECT deleted FROM trip_teams WHERE number=?', (number,)).fetchone()
                if old and old['deleted']:
                    raise ValueError('Номер удалённой команды сохранён в истории. Выберите другой номер.')
                c.execute('INSERT INTO trip_teams(number,curator,code) VALUES(?,?,?) ON CONFLICT(number) DO UPDATE SET curator=excluded.curator',
                          (number, cur[0], secrets.token_urlsafe(8)))
                existing = c.execute('SELECT team FROM trip_members WHERE uid=?', (cur[0],)).fetchone()
                if existing and existing[0] != number:
                    raise ValueError('Куратор уже состоит в другой команде.')
                c.execute('INSERT OR REPLACE INTO trip_members VALUES(?,?)', (cur[0], number))
            elif action == 'delete_team':
                number = int(body['number'])
                if not c.execute('SELECT 1 FROM trip_teams WHERE number=? AND deleted=0', (number,)).fetchone():
                    raise ValueError('Команда не найдена.')
                if c.execute("SELECT 1 FROM trip_requests WHERE team=? AND status IN ('new','assembling','ready','issued')", (number,)).fetchone():
                    raise ValueError('У команды есть активные заявки. Сначала отмените их или примите возврат оборудования.')
                c.execute('DELETE FROM trip_members WHERE team=?', (number,))
                if c.execute('SELECT 1 FROM trip_requests WHERE team=?', (number,)).fetchone():
                    # Keep the number reserved so a new team cannot inherit this team's history.
                    c.execute('UPDATE trip_teams SET deleted=1 WHERE number=?', (number,))
                else:
                    c.execute('DELETE FROM trip_teams WHERE number=?', (number,))
            elif action == 'members':
                number = int(body['number'])
                t = c.execute('SELECT * FROM trip_teams WHERE number=? AND deleted=0', (number,)).fetchone()
                if not t or not (manage or t['curator'] == uid):
                    return self.c['jerr']('Добавлять участников может рентал или куратор команды.', 403)
                people = self.ids(body.get('members', []))
                for person in people:
                    old = c.execute('SELECT team FROM trip_members WHERE uid=?', (person,)).fetchone()
                    if old and old[0] != number:
                        raise ValueError(f'{person} уже в команде {old[0]}. Сначала удалите его из неё.')
                    c.execute('INSERT OR IGNORE INTO trip_members VALUES(?,?)', (person, number))
                if body.get('remove'):
                    person = int(body['remove'])
                    if person == t['curator']:
                        raise ValueError('Сначала назначьте другого куратора.')
                    c.execute('DELETE FROM trip_members WHERE uid=? AND team=?', (person, number))
            elif action == 'join':
                t = c.execute('SELECT * FROM trip_teams WHERE code=? AND deleted=0', (str(body.get('code', '')).strip(),)).fetchone()
                if not t:
                    raise ValueError('Неверный код команды.')
                old = c.execute('SELECT team FROM trip_members WHERE uid=?', (uid,)).fetchone()
                if old and old[0] != t['number']:
                    raise ValueError('Вы уже в другой команде. Обратитесь к ренталу.')
                c.execute('INSERT OR IGNORE INTO trip_members VALUES(?,?)', (uid, t['number']))
            elif action == 'block':
                kind, start, end = body['kind'], self.stamp(body['start']), self.stamp(body['end'])
                ident = int(body.get('id', 0))
                if kind not in ('task', 'night') or end <= start or end <= time.time():
                    raise ValueError('Проверьте тип и даты блока. Конец должен быть позже начала.')
                if c.execute('SELECT 1 FROM trip_blocks WHERE id<>? AND start<? AND end>?', (ident, end, start)).fetchone():
                    raise ValueError('Блоки не должны пересекаться.')
                if ident:
                    if not c.execute('SELECT 1 FROM trip_blocks WHERE id=?', (ident,)).fetchone():
                        raise ValueError('Блок не найден.')
                    if c.execute("SELECT 1 FROM trip_requests WHERE block=? AND status IN ('ready','issued')", (ident,)).fetchone():
                        raise ValueError('У блока есть готовое или выданное оборудование. Завершите заявки перед изменением расписания.')
                    c.execute('UPDATE trip_blocks SET kind=?,start=?,end=? WHERE id=?', (kind, start, end, ident))
                else:
                    c.execute('INSERT INTO trip_blocks(kind,start,end) VALUES(?,?,?)', (kind, start, end))
            elif action == 'item':
                ident, name, total = int(body.get('id', 0)), str(body['name']).strip()[:200], int(body['total'])
                if not name or not 1 <= total <= 999:
                    raise ValueError('Укажите название и количество от 1 до 999.')
                if ident:
                    kits = c.execute("SELECT kit FROM trip_requests WHERE status IN ('ready','issued')").fetchall()
                    if any(i == ident for r in kits for i, q in json.loads(r['kit'])):
                        raise ValueError('Позиция зарезервирована или выдана. Измените её после возврата.')
                    c.execute('UPDATE trip_items SET name=?,total=?,active=? WHERE id=?', (name, total, int(bool(body.get('active', True))), ident))
                else:
                    c.execute('INSERT INTO trip_items(name,total) VALUES(?,?)', (name, total))
            elif action == 'create':
                member = c.execute('SELECT team FROM trip_members WHERE uid=?', (uid,)).fetchone()
                block = self.current_block()
                if not member:
                    raise ValueError('Сначала вступите в команду.')
                if not block or int(body['block']) != block['id']:
                    raise ValueError('Можно подать заявку только на текущий или ближайший блок. Обновите экран.')
                needs = body.get('needs', {})
                if not isinstance(needs, dict) or any(k not in NEEDS or type(v) is not int or not 1 <= v <= 99 for k, v in needs.items()):
                    raise ValueError('Проверьте выбранные потребности.')
                purpose = str(body.get('purpose', '')).strip()[:2000]
                if not purpose:
                    raise ValueError('Опишите, что будете снимать.')
                wanted = self.kit(c, body.get('wanted', []), dict(id=0, start=block['start'], end=block['end']))
                if not needs and not wanted:
                    raise ValueError('Выберите хотя бы одну потребность или оборудование.')
                ref = c.execute('INSERT INTO trip_requests(team,block,author,needs,purpose,wanted,created) VALUES(?,?,?,?,?,?,?)',
                                (member[0], block['id'], uid, json.dumps(needs, ensure_ascii=False), purpose, json.dumps(wanted), time.time())).lastrowid
                c.execute('INSERT INTO trip_history(ref,uid,status,stamp) VALUES(?,?,?,?)', (ref, uid, 'new', time.time()))
                need_text = ', '.join(f'{k} × {v}' for k, v in needs.items())
                wanted_text = ', '.join(f"{c.execute('SELECT name FROM trip_items WHERE id=?', (i,)).fetchone()[0]} × {q}" for i, q in wanted)
                self.enqueue(c, f'new:{ref}', [s['channel']], f'Медиа выезд · заявка №{ref} · команда {member[0]}\nБлок: {self.fmt(block["start"])} — {self.fmt(block["end"])}\n{need_text}\n{wanted_text}\nЗадача: {purpose}')
            elif action == 'request':
                ref, target = int(body['id']), body['status']
                r = c.execute('SELECT r.*,b.start,b.end FROM trip_requests r JOIN trip_blocks b ON b.id=r.block WHERE r.id=?', (ref,)).fetchone()
                if not r:
                    raise ValueError('Заявка не найдена.')
                member = c.execute('SELECT team FROM trip_members WHERE uid=?', (uid,)).fetchone()
                own = bool(member and member[0] == r['team'])
                if target == 'canceled':
                    if not own:
                        return self.c['jerr']('Отменять заявку может только её команда.', 403)
                    if r['status'] not in ('new', 'assembling', 'ready'):
                        raise ValueError('Выданное оборудование нужно вернуть.')
                else:
                    if not manage:
                        return self.c['jerr']('Доступно только команде рентала.', 403)
                    transitions = {'assembling': ('new',), 'kit': ('assembling',), 'ready': ('assembling',),
                                   'issued': ('ready',), 'returned': ('issued',), 'rejected': ('new', 'assembling', 'ready')}
                    if target not in transitions or r['status'] not in transitions[target]:
                        raise ValueError('Статус заявки уже изменён. Обновите экран.')
                if target in ('kit', 'ready', 'issued'):
                    if r['end'] <= time.time():
                        raise ValueError('Блок закончился. Отклоните заявку.')
                    kit = self.kit(c, body.get('kit', json.loads(r['kit'])), r)
                    if target != 'kit' and not kit:
                        raise ValueError('Добавьте оборудование в состав выдачи.')
                    if target == 'ready' and not s['place']:
                        raise ValueError('Сначала укажите место выдачи в настройках.')
                    c.execute('UPDATE trip_requests SET kit=? WHERE id=?', (json.dumps(kit), ref))
                reason = str(body.get('reason', '')).strip()[:500]
                if target == 'rejected' and not reason:
                    raise ValueError('Укажите причину отказа.')
                if target != 'kit':
                    c.execute('UPDATE trip_requests SET status=?,reason=? WHERE id=?', (target, reason, ref))
                    c.execute('INSERT INTO trip_history(ref,uid,status,stamp) VALUES(?,?,?,?)', (ref, uid, target, time.time()))
                    text = f'Медиа выезд · команда {r["team"]} · заявка №{ref}: {LABELS[target]}.'
                    if target == 'ready':
                        text += f'\nПодойдите и заберите оборудование. Место: {s["place"]}.\nВернуть до {self.fmt(r["end"])}.'
                        text += '\nСостав: ' + ', '.join(
                            f"{c.execute('SELECT name FROM trip_items WHERE id=?', (i,)).fetchone()[0]} × {q}" for i, q in kit)
                    if reason:
                        text += '\n' + reason
                    self.enqueue(c, f'status:{ref}:{target}', self.members(c, r['team']), text, ref, target,
                                 r['end'] if target == 'ready' else 0)
                    self.enqueue(c, f'channel:{ref}:{target}', [s['channel']], text, ref,
                                 target if target == 'ready' else '', r['end'] if target == 'ready' else 0)
            else:
                raise ValueError('Неизвестное действие.')
        return self.c['web'].json_response(self.c['boot_payload'](uid))

    async def tick(self, now=None):
        now = time.time() if now is None else now
        s = self.settings()
        async with self.lock:
            with self.db() as c:
                eligible = lambda ids: [i for i in ids if self.allowed(i, s)]
                for b in c.execute('SELECT * FROM trip_blocks WHERE start>? AND start<=?', (now, now + 1800)).fetchall():
                    people = eligible([r[0] for r in c.execute('SELECT uid FROM trip_members')])
                    self.enqueue(c, f'block:{b["id"]}:{b["start"]}', people,
                                 f'Медиа выезд: скоро {"ночной блок" if b["kind"] == "night" else "блок задания"} ({self.fmt(b["start"])}). Забронируйте оборудование.', expires=b['start'])
                for r in c.execute("SELECT r.*,b.end FROM trip_requests r JOIN trip_blocks b ON b.id=r.block WHERE r.status='issued'").fetchall():
                    if now < r['end'] <= now + 900:
                        self.enqueue(c, f'return:{r["id"]}', eligible(self.members(c, r['team'])),
                                     f'Медиа выезд · команда {r["team"]}: пора вернуть оборудование по заявке №{r["id"]}. Срок: {self.fmt(r["end"])}.', r['id'], 'issued', r['end'])
                    if now >= r['end']:
                        self.enqueue(c, f'overdue:{r["id"]}', [s['channel']],
                                     f'Медиа выезд: команда {r["team"]} ещё не вернула оборудование по заявке №{r["id"]}. Блок закончился {self.fmt(r["end"])}.', r['id'], 'issued')
        bot = self.c['bot']
        if bot is None:
            return
        with self.db() as c:
            pending = c.execute('SELECT * FROM trip_outbox WHERE sent=0 AND retry<=? ORDER BY rowid LIMIT 100', (now,)).fetchall()
        for row in pending:
            with self.db() as c:
                if row['expires'] and now >= row['expires']:
                    c.execute('UPDATE trip_outbox SET sent=1 WHERE key=?', (row['key'],))
                    continue
                if row['guard']:
                    current = c.execute('SELECT status FROM trip_requests WHERE id=?', (row['ref'],)).fetchone()
                    if not current or current[0] != row['guard']:
                        c.execute('UPDATE trip_outbox SET sent=1 WHERE key=?', (row['key'],))
                        continue
            try:
                await bot.send_message(row['recipient'], row['text'], parse_mode=None,
                                       reply_markup=self.c['deeplink_kb']())
            except Exception as exc:
                self.c['log'].warning('Media trip delivery failed for %s: %s', row['recipient'], exc)
                with self.db() as c:
                    c.execute('UPDATE trip_outbox SET attempts=attempts+1,retry=? WHERE key=?',
                              (now + min(1800, 30 * 2 ** min(row['attempts'], 6)), row['key']))
            else:
                with self.db() as c:
                    c.execute('UPDATE trip_outbox SET sent=1 WHERE key=?', (row['key'],))

    async def loop(self):
        while True:
            before = self.c['db_revision']()
            try:
                await self.tick()
            except Exception:
                self.c['log'].exception('Media trip scheduler failed')
            if self.c['db_revision']() != before:
                await self.c['sse_broadcast']()
            await asyncio.sleep(30)
