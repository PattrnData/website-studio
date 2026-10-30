"""Offline Apple Design registry/schema migration tests; provider bytes are fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('apple_upstreams', ROOT/'plugins/website-studio/scripts/website_upstreams.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
APPLE = 'emilkowalski/skills'


class AppleDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)/'upstream'

    def fetch(self, url):
        if '/commits?' in url:
            return json.dumps([{'sha': 'a'*40}]).encode()
        return ('OFFLINE FIXTURE: '+url).encode()

    def stage(self):
        with patch.object(u, 'fetch', side_effect=self.fetch):
            return u.stage(self.store)['snapshot']

    def rewrite(self, snapshot, data):
        old = self.store/'snapshots'/snapshot
        raw = u.encode(data)
        new = old.with_name(u.digest(raw))
        old.rename(new)
        (new/'manifest.json').write_bytes(raw)
        return new.name

    def legacy(self):
        sid = self.stage()
        data = u.validate(self.store, sid)
        data['schema'] = 1
        data['sources'] = [s for s in data['sources'] if s['repo'] != APPLE]
        sid = self.rewrite(sid, data)
        self.assertEqual(len(u.validate(self.store, sid)['sources']), 5)
        return sid

    def test_apple_source_exact_files_registered(self):
        self.assertEqual(u.SOURCES.get(APPLE), ['README.md', 'LICENSE', 'skills/apple-design/SKILL.md'])

    def test_new_snapshot_schema_two_contains_six(self):
        data = u.validate(self.store, self.stage())
        self.assertEqual(data['schema'], 2)
        self.assertEqual(len(data['sources']), 6)
        self.assertIn(APPLE, {s['repo'] for s in data['sources']})

    def test_legacy_five_source_snapshot_remains_valid_and_rollbackable(self):
        old = self.legacy()
        self.assertEqual(u.activate(self.store, old)['status'], 'activated')
        new = self.stage()
        self.assertEqual(u.activate(self.store, new)['previous'], old)
        self.assertEqual(u.activate(self.store, old)['previous'], new)
        self.assertEqual(u.pointer(self.store)['active'], old)
        self.assertEqual(u.validate(self.store, old)['schema'], 1)

    def test_schema_two_cannot_omit_apple(self):
        sid = self.stage()
        data = u.validate(self.store, sid)
        data['schema'] = 2
        data['sources'] = [s for s in data['sources'] if s['repo'] != APPLE]
        sid = self.rewrite(sid, data)
        with self.assertRaises(ValueError):
            u.validate(self.store, sid)

    def test_schema_one_cannot_smuggle_sixth_source(self):
        sid = self.stage()
        data = u.validate(self.store, sid)
        data['schema'] = 1
        sid = self.rewrite(sid, data)
        with self.assertRaises(ValueError):
            u.validate(self.store, sid)

    def test_schema_one_rejects_apple_even_with_legacy_count(self):
        sid = self.stage()
        data = u.validate(self.store, sid)
        data['schema'] = 1
        data['sources'] = data['sources'][1:]
        self.assertEqual(len(data['sources']), 5)
        sid = self.rewrite(sid, data)
        with self.assertRaisesRegex(ValueError, 'repository'):
            u.validate(self.store, sid)

    def test_unsupported_and_noninteger_schemas_fail_structurally(self):
        for schema in [0, 3, True, '2', None, [], {}]:
            with self.subTest(schema=schema):
                sid = self.stage()
                data = u.validate(self.store, sid)
                data['schema'] = schema
                sid = self.rewrite(sid, data)
                with self.assertRaises(ValueError):
                    u.validate(self.store, sid)

    def test_apple_exact_url_allowlist_not_entire_skill_repository(self):
        root = 'https://raw.githubusercontent.com/'+APPLE+'/'+'a'*40+'/'
        for path in ['README.md', 'LICENSE', 'skills/apple-design/SKILL.md']:
            self.assertTrue(u.allowed_url(root+path), path)
        for path in ['skills/other/SKILL.md', 'scripts/run.sh', 'skills/apple-design/../../x']:
            self.assertFalse(u.allowed_url(root+path), path)
        self.assertFalse(u.allowed_url('https://raw.githubusercontent.com/'+APPLE+'/main/skills/apple-design/SKILL.md'))

    def test_legacy_check_reports_new_apple_without_mutating_store(self):
        self.assertIn(APPLE, u.SOURCES)
        u.activate(self.store, self.legacy())
        before = {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        with patch.object(u, 'fetch', side_effect=self.fetch):
            result = u.check(self.store)
        apple = next(s for s in result['sources'] if s['repo'] == APPLE)
        self.assertEqual(apple['status'], 'changed')
        self.assertIsNone(apple['pinned'])
        self.assertEqual(len(result['sources']), 6)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})

    def test_apple_failure_is_failed_and_other_sources_still_checked(self):
        self.assertIn(APPLE, u.SOURCES)
        sid = self.stage()
        u.activate(self.store, sid)
        def unavailable(url):
            if '/'+APPLE+'/' in url:
                raise OSError('OFFLINE FIXTURE: Apple source unavailable')
            return self.fetch(url)
        with patch.object(u, 'fetch', side_effect=unavailable):
            result = u.check(self.store)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['sources']), 6)
        self.assertEqual([s['repo'] for s in result['sources'] if s['status'] == 'failed'], [APPLE])

    def test_coordinator_apple_module_is_conditional_and_source_linked(self):
        main = (ROOT/'plugins/website-studio/skills/website-studio/SKILL.md').read_text()
        refs = (ROOT/'plugins/website-studio/skills/website-studio/references/integrations.md').read_text()
        self.assertIn('Apple Design', main)
        for term in ['emilkowalski--skills/skills/apple-design/SKILL.md', 'Initial Response', 'keyboard', 'pointercancel', 'reduced-transparency']:
            self.assertIn(term, refs)
        self.assertIn('not a mandatory dependency', refs)


if __name__ == '__main__':
    unittest.main()
