"""Clear this trip's requests with a database backup; run with the bot stopped."""
import argparse
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path


TRIP_TABLES = ('trip_requests', 'trip_history', 'trip_outbox', 'trip_teams', 'trip_members')


def clear_history(database, teams, apply=False):
    if teams not in ('keep', 'clear'):
        raise ValueError('Выберите teams=keep или teams=clear.')
    database = Path(database).resolve(strict=True)
    # mode=rw refuses to create an empty database at a mistyped location.
    connection = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=10)
    try:
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in TRIP_TABLES}
        issued = connection.execute("SELECT COUNT(*) FROM trip_requests WHERE status='issued'").fetchone()[0]
        deleted_teams = connection.execute('SELECT COUNT(*) FROM trip_teams WHERE deleted=1').fetchone()[0]
        result = dict(before=counts, issued=issued, deletedTeams=deleted_teams, teams=teams, applied=False)
        if not apply:
            return result
        if issued:
            raise ValueError(f'Есть выданное оборудование: {issued} заявок. Сначала отметьте возврат в рентале.')
        backup_directory = database.parent / 'backup'
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup = backup_directory / f'media-trip-before-clear-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.db'
        version = connection.execute('PRAGMA data_version').fetchone()[0]
        with closing(sqlite3.connect(backup)) as saved:
            backup.chmod(0o600)
            connection.backup(saved)
            if saved.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Резервная копия не прошла проверку; очистка не выполнена.')
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('PRAGMA data_version').fetchone()[0] != version:
            raise ValueError('База изменилась во время подготовки. Остановите сервис и повторите очистку.')
        for table in ('trip_outbox', 'trip_history', 'trip_requests'):
            connection.execute(f'DELETE FROM {table}')
        if teams == 'clear':
            connection.execute('DELETE FROM trip_members')
            connection.execute('DELETE FROM trip_teams')
        else:
            connection.execute('DELETE FROM trip_members WHERE team IN (SELECT number FROM trip_teams WHERE deleted=1)')
            connection.execute('DELETE FROM trip_teams WHERE deleted=1')
        result['after'] = {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                           for table in TRIP_TABLES}
        connection.commit()
        result.update(applied=True, backup=str(backup))
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description='Очистка заявок медиа-выезда. Перед применением остановите сервис oborudka.')
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().parent / 'oborudka.db')
    parser.add_argument('--teams', choices=['keep', 'clear'], required=True,
                        help='keep — сохранить действующие команды; clear — удалить команды и их участников')
    parser.add_argument('--apply', action='store_true', help='Выполнить очистку; без флага только показать количество записей')
    args = parser.parse_args()
    try:
        result = clear_history(args.db, args.teams, args.apply)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'Очистка не выполнена: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
