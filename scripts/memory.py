#!/usr/bin/env python3
"""Local scoped memory. No network, model calls, background hooks, or installation."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

MAX_BYTES = 5_000_000
KINDS = {'preference', 'research_preference', 'project', 'experience'}
FIELDS = {'id', 'kind', 'scope', 'triggers', 'content', 'status', 'basis', 'expires_on'}


class Conflict(ValueError):
    pass


def scope_name(value):
    if value == 'user':
        return value
    if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
        raise ValueError('scope must be user or an absolute project path')
    return str(Path(value).expanduser().resolve())


def entry(data):
    if not isinstance(data, dict) or set(data) - FIELDS or FIELDS - {'expires_on'} - set(data):
        raise ValueError('invalid memory fields')
    result = dict(data)
    if not isinstance(data['id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,95}', data['id']):
        raise ValueError('id must be a stable lowercase identifier')
    if data['kind'] not in KINDS or data['status'] not in {'active', 'candidate', 'archived'}:
        raise ValueError('invalid kind or status')
    result['scope'] = scope_name(data['scope'])
    if data['kind'] == 'project' and result['scope'] == 'user':
        raise ValueError('project memory requires a project scope')
    if not isinstance(data['content'], str) or not 1 <= len(data['content'].strip()) <= 1200:
        raise ValueError('content must contain 1..1200 characters')
    result['content'] = data['content'].strip()
    triggers = data['triggers']
    if not isinstance(triggers, list) or not 1 <= len(triggers) <= 12:
        raise ValueError('provide 1..12 triggers')
    if any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 80 for t in triggers):
        raise ValueError('invalid trigger')
    result['triggers'] = sorted({t.strip().casefold() for t in triggers})
    basis = data['basis']
    if not isinstance(basis, dict) or set(basis) != {'type', 'ref'}:
        raise ValueError('basis requires type and ref')
    if basis['type'] not in {'user_explicit', 'observed', 'inferred'}:
        raise ValueError('invalid basis type')
    if not isinstance(basis['ref'], str) or not 1 <= len(basis['ref'].strip()) <= 800:
        raise ValueError('basis.ref must explain the actual source')
    if data['status'] == 'active':
        if basis['type'] == 'inferred':
            raise ValueError('inferred memory must remain candidate')
        if data['kind'] in {'preference', 'research_preference'} and basis['type'] != 'user_explicit':
            raise ValueError('active preferences require explicit user evidence')
        if data['kind'] == 'experience' and basis['type'] != 'observed':
            raise ValueError('active experience requires observed evidence')
    if 'expires_on' in data:
        if not isinstance(data['expires_on'], str):
            raise ValueError('invalid expires_on')
        date.fromisoformat(data['expires_on'])
    return result


def store_path(value):
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise ValueError('memory store must not be a symlink')
    path = path.resolve()
    if Path(__file__).resolve().parents[1] in path.parents:
        raise ValueError('memory must live outside the skill directory')
    return path


def read_store(path):
    if not path.exists():
        return {'schema_version': 1, 'revision': 0, 'entries': []}
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('memory exceeds size limit; compact explicitly')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'schema_version', 'revision', 'entries'}:
        raise ValueError('invalid store structure; original left unchanged')
    if data['schema_version'] != 1 or type(data['revision']) is not int or data['revision'] < 0:
        raise ValueError('invalid schema or revision')
    if not isinstance(data['entries'], list) or len(data['entries']) > 5000:
        raise ValueError('invalid entry list or capacity exceeded')
    keys = set()
    for record in data['entries']:
        if not isinstance(record, dict) or 'updated_at' not in record:
            raise ValueError('invalid stored entry')
        if not isinstance(record['updated_at'], str):
            raise ValueError('invalid update timestamp')
        datetime.fromisoformat(record['updated_at'])
        clean = entry({k: v for k, v in record.items() if k != 'updated_at'})
        key = (clean['scope'], clean['id'])
        if key in keys:
            raise ValueError('duplicate scoped id')
        keys.add(key)
    return data


def query(data, project=None, scenes=(), text='', limit=6, max_chars=6000, status='active', identifier=None):
    if not 1 <= limit <= 30 or not 512 <= max_chars <= 20000:
        raise ValueError('limit must be 1..30; max-chars 512..20000')
    scopes = {'user'}
    if project:
        project = scope_name(project)
        scopes.add(project)
    scenes = {s.strip().casefold() for s in scenes}
    text = text.casefold()
    ranked = []
    for record in data['entries']:
        if record['scope'] not in scopes:
            continue
        if identifier is not None and record['id'] != identifier:
            continue
        if status == 'active' and (record['status'] != 'active' or
                record.get('expires_on', '9999-12-31') < date.today().isoformat()):
            continue
        hits = sum(t in scenes or (t != '*' and t in text) for t in record['triggers'])
        if identifier is not None or hits or '*' in record['triggers']:
            ranked.append((record['scope'] == project, hits, record))
    ranked.sort(key=lambda r: (r[0], r[1], r[2]['updated_at'], r[2]['id']), reverse=True)
    unique = {}
    for _, _, record in ranked:
        unique.setdefault(record['id'], record)
    result = {'revision': data['revision'], 'entries': [], 'has_more': False}
    for record in unique.values():
        candidate = dict(result, entries=result['entries'] + [record])
        if len(result['entries']) >= limit or len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
            result['has_more'] = True
            continue
        result['entries'].append(record)
    return result


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lockfile = path.with_name(path.name + '.lock')
    try:
        fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Conflict('store locked; verify other writer before retrying') from exc
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lockfile.unlink()


def mutate(path, operation, expected, item=None, identifier=None, scope=None):
    with lock(path):
        if path.is_symlink():
            raise ValueError('memory store must not be a symlink')
        data = read_store(path)
        if expected != data['revision']:
            raise Conflict('revision changed; query and reconcile before retrying')
        if operation == 'upsert':
            item = entry(item)
            identifier, scope = item['id'], item['scope']
        else:
            scope = scope_name(scope)
        index = next((i for i, r in enumerate(data['entries'])
                      if (r['id'], r['scope']) == (identifier, scope)), None)
        changed = False
        if operation == 'upsert':
            comparable = lambda r: {k: v for k, v in r.items() if k != 'updated_at'}
            duplicate = next((r for r in data['entries'] if r['scope'] == scope and
                r['kind'] == item['kind'] and r['id'] != identifier and
                ' '.join(r['content'].split()).casefold() == ' '.join(item['content'].split()).casefold()), None)
            if duplicate:
                raise ValueError('duplicate content; update existing id: ' + duplicate['id'])
            changed = index is None or comparable(data['entries'][index]) != item
            if changed:
                item['updated_at'] = datetime.now(timezone.utc).isoformat()
                if index is None:
                    data['entries'].append(item)
                else:
                    data['entries'][index] = item
        elif operation == 'forget' and index is not None:
            del data['entries'][index]
            changed = True
        elif operation == 'retire' and index is not None and data['entries'][index]['status'] != 'archived':
            data['entries'][index]['status'] = 'archived'
            data['entries'][index]['updated_at'] = datetime.now(timezone.utc).isoformat()
            changed = True
        if changed:
            data['revision'] += 1
            payload = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            if len(payload) > MAX_BYTES or len(data['entries']) > 5000:
                raise ValueError('memory capacity exceeded; merge or forget obsolete entries')
            fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            if read_store(path) != data:
                raise ValueError('write verification failed')
        return {'revision': data['revision'], 'changed': changed, 'operation': operation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for name in ['query', 'upsert', 'retire', 'forget']:
        p = sub.add_parser(name)
        p.add_argument('--store', required=True)
        if name == 'query':
            p.add_argument('--project')
            p.add_argument('--scene', action='append', default=[])
            p.add_argument('--text', default='')
            p.add_argument('--limit', type=int, default=6)
            p.add_argument('--max-chars', type=int, default=6000)
            p.add_argument('--status', choices=['active', 'all'], default='active')
            p.add_argument('--id', help='exact id lookup, still respects project and status')
        else:
            p.add_argument('--expect-revision', required=True, type=int)
            if name == 'upsert':
                p.add_argument('--input', required=True)
            else:
                p.add_argument('--id', required=True)
                p.add_argument('--scope', required=True)
    args = parser.parse_args()
    try:
        path = store_path(args.store)
        if args.operation == 'query':
            result = query(read_store(path), args.project, args.scene, args.text,
                           args.limit, args.max_chars, args.status, args.id)
        else:
            item = None
            if args.operation == 'upsert':
                item = json.loads(Path(args.input).read_text(encoding='utf-8'))
            result = mutate(path, args.operation, args.expect_revision, item,
                            getattr(args, 'id', None), getattr(args, 'scope', None))
        print(json.dumps(result, ensure_ascii=False))
    except Conflict as exc:
        print(json.dumps({'error': str(exc), 'status': 'conflict'}, ensure_ascii=False))
        return 3
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({'error': str(exc), 'status': 'error'}, ensure_ascii=False))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
