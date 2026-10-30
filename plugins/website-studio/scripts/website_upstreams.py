#!/usr/bin/env python3
"""Pinned documentation snapshots for Website Studio; never executes upstream code."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
import urllib.request

VERSION = '1.1.0'
MAX_BYTES = 1_048_576
DEFAULT_STORE = Path(__file__).resolve().parents[1] / 'upstream'
SOURCES = {
    'DavidHDev/react-bits': ['README.md', 'LICENSE.md'],
    'greensock/gsap': ['README.md', 'package.json'],
    'darkroomengineering/lenis': ['README.md', 'LICENSE', 'packages/react/README.md'],
    'pbakaus/impeccable': ['README.md', 'LICENSE', '.hermes/skills/impeccable/SKILL.md'],
    'leonxlnx/taste-skill': ['README.md', 'LICENSE', 'skills/taste-skill/SKILL.md'],
}
LEGACY_REPOS = frozenset(SOURCES)
SOURCES['emilkowalski/skills'] = ['README.md', 'LICENSE', 'skills/apple-design/SKILL.md']
SCHEMA_REPOS = {1: LEGACY_REPOS, 2: frozenset(SOURCES)}


def encode(data):
    return (json.dumps(data, sort_keys=True, indent=2) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def valid_id(value, revision=False):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}' if revision else r'[0-9a-f]{64}', value):
        raise ValueError('invalid full revision/snapshot identifier')
    return value


def bounded(data):
    if len(data) > MAX_BYTES:
        raise ValueError('source exceeds one MiB limit')
    return data


def allowed_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port or p.fragment:
        return False
    if p.netloc == 'api.github.com':
        return any(url == f'https://api.github.com/repos/{repo}/commits?per_page=1' for repo in SOURCES)
    if p.netloc != 'raw.githubusercontent.com' or p.query:
        return False
    for repo, files in SOURCES.items():
        prefix = f'/{repo}/'
        if p.path.startswith(prefix):
            revision, sep, file = p.path[len(prefix):].partition('/')
            return bool(sep and re.fullmatch(r'[0-9a-f]{40}', revision) and file in files)
    return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect refused; investigate source identity')


def fetch(url):
    if not allowed_url(url):
        raise ValueError('URL is outside the exact repository/file allowlist')
    opener = urllib.request.build_opener(NoRedirect())
    req = urllib.request.Request(url, headers={'User-Agent': 'WebsiteStudio/1.0', 'Accept': 'application/vnd.github+json' if 'api.github.com' in url else 'text/plain'})
    with opener.open(req, timeout=20) as response:
        return bounded(response.read(MAX_BYTES + 1))


def head(repo):
    data = json.loads(bounded(fetch(f'https://api.github.com/repos/{repo}/commits?per_page=1')))
    if not isinstance(data, list) or not data:
        raise ValueError('missing default-branch commit')
    return valid_id(data[0]['sha'], revision=True)


def safe_file(root, relative):
    p = root / relative
    if not p.is_relative_to(root) or any(part == '..' for part in Path(relative).parts) or Path(relative).is_absolute():
        raise ValueError('unsafe relative source path')
    if any(q.is_symlink() for q in [p, *p.parents] if q != root.parent):
        raise ValueError('symlink source/store refused')
    return p


def pointer(store):
    p = safe_file(store, 'active.json')
    if not p.exists():
        return {'active': None, 'previous': None}
    data = json.loads(bounded(p.read_bytes()))
    if not isinstance(data, dict) or set(data) != {'active', 'previous'}:
        raise ValueError('invalid active pointer object')
    valid_id(data['active'])
    if data.get('previous') is not None:
        valid_id(data['previous'])
    return data


def validate(store, snapshot):
    valid_id(snapshot)
    root = safe_file(store, 'snapshots/' + snapshot)
    raw = bounded(safe_file(root, 'manifest.json').read_bytes())
    if digest(raw) != snapshot:
        raise ValueError('manifest content-address mismatch')
    data = json.loads(raw)
    if not isinstance(data, dict) or type(data.get('schema')) is not int or data['schema'] not in SCHEMA_REPOS or not isinstance(data.get('sources'), list):
        raise ValueError('invalid source manifest schema/count')
    expected_repos = SCHEMA_REPOS[data['schema']]
    if len(data['sources']) != len(expected_repos):
        raise ValueError('invalid source manifest schema/count')
    seen = set()
    for item in data['sources']:
        if not isinstance(item, dict) or not isinstance(item.get('repo'), str):
            raise ValueError('invalid source entry object')
        repo = item['repo']
        if repo not in expected_repos or repo in seen:
            raise ValueError('unknown or repeated source repository')
        seen.add(repo)
        revision = valid_id(item.get('revision'), revision=True)
        files = item.get('files')
        if not isinstance(files, list) or not all(isinstance(f, dict) and isinstance(f.get('path'), str) for f in files):
            raise ValueError('invalid source file list')
        if len(files) != len(SOURCES[repo]) or {f['path'] for f in files} != set(SOURCES[repo]):
            raise ValueError('missing, duplicate or unexpected source file')
        for f in files:
            expected = repo.replace('/', '--') + '/' + f['path']
            if f.get('local') != expected or f.get('url') != f'https://raw.githubusercontent.com/{repo}/{revision}/{f["path"]}':
                raise ValueError('source path/URL binding mismatch')
            if not isinstance(f.get('bytes'), int) or not 0 <= f['bytes'] <= MAX_BYTES:
                raise ValueError('invalid source byte count')
            valid_id(f.get('sha256'))
            content = bounded(safe_file(root, expected).read_bytes())
            if digest(content) != f['sha256'] or len(content) != f['bytes']:
                raise ValueError('source bytes differ from manifest')
    return data


@contextmanager
def locked(store):
    # ponytail: one project-local writer; no daemon or distributed lease required.
    if any(p.is_symlink() for p in [store, *store.parents]):
        raise ValueError('symlink store refused')
    store.mkdir(parents=True, exist_ok=True)
    lock = store / '.update-lock'
    lock.mkdir()  # existing lock fails closed; a killed writer needs explicit inspection.
    try:
        yield
    finally:
        lock.rmdir()


def stage(store):
    with locked(store):
        snapshots = safe_file(store, 'snapshots')
        snapshots.mkdir(exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='.stage-', dir=snapshots))
        try:
            manifest = {'schema': 2, 'sources': []}
            for repo, paths in SOURCES.items():
                revision = head(repo)
                item = {'repo': repo, 'revision': revision, 'files': []}
                for file in paths:
                    url = f'https://raw.githubusercontent.com/{repo}/{revision}/{file}'
                    content = bounded(fetch(url))
                    local = repo.replace('/', '--') + '/' + file
                    target = safe_file(tmp, local)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    item['files'].append({'path': file, 'local': local, 'url': url, 'bytes': len(content), 'sha256': digest(content)})
                manifest['sources'].append(item)
            raw = encode(manifest)
            snapshot = digest(raw)
            (tmp / 'manifest.json').write_bytes(raw)
            target = safe_file(store, 'snapshots/' + snapshot)
            if target.exists():
                validate(store, snapshot)
            else:
                os.replace(tmp, target)
            validate(store, snapshot)
            return {'status': 'staged', 'snapshot': snapshot, 'manifest': str(target / 'manifest.json'), 'activated': False}
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)


def write_pointer(store, raw):
    """Atomically publish exact bytes (or restore absence), then sync the directory."""
    path = store / 'active.json'
    if raw is None:
        path.unlink(missing_ok=True)
    else:
        fd, name = tempfile.mkstemp(prefix='.active-', dir=store)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    directory_fd = os.open(store, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def activate(store, snapshot):
    with locked(store):
        validate(store, snapshot)
        before = pointer(store)
        if before['active'] == snapshot:
            return {'status': 'unchanged', **before}
        record = {'active': snapshot, 'previous': before['active']}
        path = store / 'active.json'
        original = path.read_bytes() if path.exists() else None
        try:
            write_pointer(store, encode(record))
            if pointer(store) != record:
                raise OSError('active pointer readback mismatch')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            rollback_error = None
            try:
                write_pointer(store, original)
            except (OSError, ValueError) as restore_exc:
                rollback_error = str(restore_exc)
            try:
                observed = pointer(store)
            except (OSError, ValueError, KeyError, TypeError):
                observed = None
            state = 'indeterminate'
            if observed == before:
                state = 'restored_previous' if rollback_error is None else 'previous_observed_durability_unconfirmed'
            elif observed == record:
                state = 'new_pointer_observed_durability_unconfirmed'
            return {'status': 'failed', 'error': str(exc), 'activation_state': state,
                    'requested': snapshot, 'before': before, 'observed': observed,
                    'rollback_error': rollback_error, 'durability_confirmed': state == 'restored_previous'}
        return {'status': 'activated', **record}


def check(store):
    previous = pointer(store)
    pinned = {}
    if previous['active']:
        pinned = {s['repo']: s['revision'] for s in validate(store, previous['active'])['sources']}
    results = []
    for repo in SOURCES:
        row = {'repo': repo, 'pinned': pinned.get(repo)}
        try:
            row['head'] = head(repo)
            row['status'] = 'current' if row['head'] == row['pinned'] else 'changed'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row.update(status='failed', error=str(exc))
        results.append(row)
    status = 'failed' if any(r['status'] == 'failed' for r in results) else 'changed' if any(r['status'] == 'changed' for r in results) else 'current'
    return {'status': status, 'active': previous['active'], 'sources': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--store', type=Path, default=DEFAULT_STORE)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ['check', 'stage', 'inspect', 'activate']:
        sub = commands.add_parser(command)
        sub.add_argument('--dry-run', action='store_true', help='Print intent only: no network, file reads/writes or validation')
        if command == 'activate':
            sub.add_argument('snapshot')
    args = parser.parse_args(argv)
    if args.command == 'activate':
        try: valid_id(args.snapshot)
        except ValueError as exc: parser.error(str(exc))
    if args.dry_run:
        print(json.dumps({'status': 'dry-run', 'command': args.command, 'store': str(args.store)}))
        return 0
    if args.command in {'stage', 'activate'} and args.store.resolve() == DEFAULT_STORE.resolve():
        parser.error('bundled references are read-only; choose a separate workspace with --store PATH')
    try:
        if args.command == 'check': result = check(args.store)
        elif args.command == 'stage': result = stage(args.store)
        elif args.command == 'activate': result = activate(args.store, args.snapshot)
        else:
            result = pointer(args.store)
            if result['active']: result['manifest'] = validate(args.store, result['active'])
        print(json.dumps(result, indent=2))
        return 1 if result.get('status') == 'failed' else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
