"""Offline regression tests. Fake provider bytes are fixtures, not online evidence."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upstreams', ROOT / 'plugins/website-studio/scripts/website_upstreams.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)

class UpstreamsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / 'upstream'

    def fetch(self, url):
        if '/commits?' in url:
            return json.dumps([{'sha': 'a' * 40}]).encode()
        return ('fixture source: ' + url).encode()

    def stage(self):
        with patch.object(u, 'fetch', side_effect=self.fetch):
            return u.stage(self.store)

    def active(self):
        result = self.stage()
        u.activate(self.store, result['snapshot'])
        return result['snapshot']

    def test_exact_six_sources(self):
        self.assertEqual(set(u.SOURCES), {'DavidHDev/react-bits', 'greensock/gsap', 'darkroomengineering/lenis', 'pbakaus/impeccable', 'leonxlnx/taste-skill', 'emilkowalski/skills'})

    def test_stage_is_not_activation(self):
        s = self.stage()
        self.assertFalse((self.store / 'active.json').exists())
        data = u.validate(self.store, s['snapshot'])
        self.assertEqual(len(data['sources']), 6)
        for r in data['sources']:
            self.assertRegex(r['revision'], r'^[a-f0-9]{40}$')
            for f in r['files']:
                self.assertRegex(f['sha256'], r'^[a-f0-9]{64}$')

    def test_activate_and_rollback_previous(self):
        first = self.active()
        with patch.object(u, 'fetch', side_effect=lambda url: self.fetch(url).replace(b'a' * 40, b'b' * 40)):
            second = u.stage(self.store)['snapshot']
        u.activate(self.store, second)
        self.assertEqual(u.pointer(self.store)['previous'], first)
        u.activate(self.store, first)
        self.assertEqual(u.pointer(self.store)['active'], first)

    def test_check_current_and_changed(self):
        self.active()
        with patch.object(u, 'fetch', side_effect=self.fetch):
            r = u.check(self.store)
        self.assertEqual(r['status'], 'current')
        self.assertEqual(len(r['sources']), 6)
        with patch.object(u, 'fetch', return_value=json.dumps([{'sha': 'b'*40}]).encode()):
            r = u.check(self.store)
        self.assertEqual(r['status'], 'changed')
        self.assertTrue(all(s['status'] == 'changed' for s in r['sources']))

    def test_check_error_not_current_and_checks_all(self):
        self.active()
        for error in [OSError('HTTP 429 rate limit'), OSError('HTTP 503 unavailable'), ValueError('bad JSON')]:
            with self.subTest(error=str(error)), patch.object(u, 'fetch', side_effect=error):
                r = u.check(self.store)
                self.assertEqual(r['status'], 'failed')
                self.assertEqual(len(r['sources']), 6)
                self.assertTrue(all(s['status'] == 'failed' for s in r['sources']))

    def test_check_does_not_change_store(self):
        self.active()
        before = {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        with patch.object(u, 'fetch', side_effect=self.fetch):
            u.check(self.store)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})

    def test_partial_stage_never_changes_active_or_keeps_candidate(self):
        self.active()
        before = (self.store/'active.json').read_bytes()
        candidates = set((self.store/'snapshots').iterdir())
        calls = 0
        def broken(url):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('network interrupted')
            return self.fetch(url)
        with patch.object(u, 'fetch', side_effect=broken), self.assertRaises(OSError):
            u.stage(self.store)
        self.assertEqual(before, (self.store/'active.json').read_bytes())
        self.assertEqual(candidates, set((self.store/'snapshots').iterdir()))
        self.assertFalse((self.store/'.update-lock').exists())

    def test_tampered_raw_bytes_refused(self):
        s = self.active()
        data = u.validate(self.store, s)
        f = data['sources'][0]['files'][0]['local']
        (self.store/'snapshots'/s/f).write_text('tampered')
        with self.assertRaises(ValueError):
            u.validate(self.store, s)

    def test_manifest_path_traversal_and_remote_revision_rejected(self):
        for value in ['../outside', '/etc/passwd', 'x/y', 'not-a-sha', 'a'*40+';echo evil']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                u.valid_id(value)
        with patch.object(u, 'fetch', return_value=b'[{"sha":"../../evil"}]'), self.assertRaises(ValueError):
            u.stage(self.store)

    def test_wrong_repo_or_duplicate_manifest_rejected(self):
        s = self.active()
        p = self.store/'snapshots'/s/'manifest.json'
        original = p.read_bytes()
        for mutate in [lambda d: d['sources'][0].update(repo='attacker/other'), lambda d: d['sources'].append(d['sources'][0]), lambda d: d['sources'][0]['files'][0].update(local='../../outside')]:
            d=json.loads(original); mutate(d); raw=u.encode(d); p.write_bytes(raw)
            moved=p.parent.with_name(u.digest(raw)); p.parent.rename(moved)
            try:
                with self.assertRaises(ValueError): u.validate(self.store,moved.name)
            finally:
                moved.rename(p.parent); p.write_bytes(original)

    def test_symlink_source_refused(self):
        s=self.active(); d=u.validate(self.store,s)
        p=self.store/'snapshots'/s/d['sources'][0]['files'][0]['local']
        data=p.read_bytes(); target=Path(self.tmp.name)/'outside';target.write_bytes(data)
        p.unlink();p.symlink_to(target)
        with self.assertRaises(ValueError): u.validate(self.store,s)

    def test_lock_exclusion(self):
        self.store.mkdir();(self.store/'.update-lock').mkdir()
        with self.assertRaises(FileExistsError): self.stage()
        self.assertTrue((self.store/'.update-lock').is_dir())

    def test_atomic_pointer_failure_preserves_previous(self):
        self.active(); before=(self.store/'active.json').read_bytes()
        with patch.object(u, 'fetch', side_effect=lambda url: self.fetch(url).replace(b'a' * 40, b'b' * 40)):
            s = u.stage(self.store)['snapshot']
        with patch.object(u.os,'replace',side_effect=OSError('replace interrupted')):
            result=u.activate(self.store,s)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['observed'],json.loads(before))
        self.assertEqual(before,(self.store/'active.json').read_bytes())
        self.assertFalse((self.store/'.update-lock').exists())

    def test_max_bytes(self):
        with patch.object(u,'fetch',return_value=b'x'*(u.MAX_BYTES+1)),self.assertRaises(ValueError):u.head('greensock/gsap')

    def test_url_allowlist(self):
        for url in ['http://api.github.com/repos/a/b','https://evil.invalid/x','https://raw.githubusercontent.com.evil.invalid/x']:
            with self.subTest(url=url),self.assertRaises(ValueError):u.fetch(url)

    def test_cli_help_version_missing_unknown_and_dry_run_inert(self):
        for args in [[],['--help'],['--version'],['oops'],['stage','--oops'],['stage','--dry-run'],['check','--dry-run'],['activate','a'*64,'--dry-run'],['inspect','--dry-run']]:
            with self.subTest(args=args), patch.object(u,'fetch',side_effect=AssertionError('network forbidden')):
                with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    try: u.main(['--store',str(self.store)]+args)
                    except SystemExit: pass
                self.assertFalse(self.store.exists())

    def test_post_replace_fsync_failure_restores_previous(self):
        self.active(); before=(self.store/'active.json').read_bytes()
        with patch.object(u,'fetch',side_effect=lambda url:self.fetch(url).replace(b'a'*40,b'b'*40)):
            candidate=u.stage(self.store)['snapshot']
        original_fsync=u.os.fsync; calls=0
        def fail_directory_once(fd):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('directory fsync failed after replace')
            return original_fsync(fd)
        out=io.StringIO()
        with patch.object(u.os,'fsync',side_effect=fail_directory_once),contextlib.redirect_stdout(out):
            self.assertEqual(u.main(['--store',str(self.store),'activate',candidate]),1)
        result=json.loads(out.getvalue())
        self.assertEqual(result['activation_state'],'restored_previous')
        self.assertEqual(result['requested'],candidate)
        self.assertEqual(before,(self.store/'active.json').read_bytes())
        self.assertFalse((self.store/'.update-lock').exists())

    def test_post_replace_readback_failure_restores_previous(self):
        self.active(); before=(self.store/'active.json').read_bytes()
        with patch.object(u,'fetch',side_effect=lambda url:self.fetch(url).replace(b'a'*40,b'b'*40)):
            candidate=u.stage(self.store)['snapshot']
        real_pointer=u.pointer; calls=0
        def fail_readback_once(store):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('readback failed after replace')
            return real_pointer(store)
        with patch.object(u,'pointer',side_effect=fail_readback_once):
            result=u.activate(self.store,candidate)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['activation_state'],'restored_previous')
        self.assertEqual(before,(self.store/'active.json').read_bytes())

    def test_failed_restoration_reports_new_pointer_not_unchanged(self):
        self.active()
        with patch.object(u,'fetch',side_effect=lambda url:self.fetch(url).replace(b'a'*40,b'b'*40)):
            candidate=u.stage(self.store)['snapshot']
        real_write=u.write_pointer;calls=0
        def write_then_fail(store,raw):
            nonlocal calls
            calls+=1
            if calls==1:real_write(store,raw)
            raise OSError('injected commit/restore failure')
        with patch.object(u,'write_pointer',side_effect=write_then_fail):
            result=u.activate(self.store,candidate)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['activation_state'],'new_pointer_observed_durability_unconfirmed')
        self.assertEqual(result['observed']['active'],candidate)
        self.assertFalse(result['durability_confirmed'])

    def test_unreadable_postfailure_state_is_indeterminate(self):
        self.active();before=(self.store/'active.json').read_bytes()
        with patch.object(u,'fetch',side_effect=lambda url:self.fetch(url).replace(b'a'*40,b'b'*40)):
            candidate=u.stage(self.store)['snapshot']
        real_pointer=u.pointer;calls=0
        def unreadable_after_start(store):
            nonlocal calls
            calls+=1
            if calls>1:raise OSError('pointer unreadable')
            return real_pointer(store)
        with patch.object(u,'pointer',side_effect=unreadable_after_start):
            result=u.activate(self.store,candidate)
        self.assertEqual(result['activation_state'],'indeterminate')
        self.assertIsNone(result['observed'])
        self.assertFalse(result['durability_confirmed'])
        self.assertEqual(before,(self.store/'active.json').read_bytes())

    def test_failed_initial_activation_restores_absence(self):
        candidate=self.stage()['snapshot'];real=u.os.fsync;calls=0
        def fail_once(fd):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('directory sync failed')
            return real(fd)
        with patch.object(u.os,'fsync',side_effect=fail_once):result=u.activate(self.store,candidate)
        self.assertEqual(result['activation_state'],'restored_previous')
        self.assertIsNone(result['observed']['active'])
        self.assertFalse((self.store/'active.json').exists())

    def test_malformed_manifest_shapes_are_structured_cli_failures(self):
        valid=u.validate(self.store,self.active())
        malformed=[[],None,{'schema':1,'sources':None},
                   {'schema':1,'sources':[None]*5},
                   {**valid,'sources':[{**valid['sources'][0],'files':None},*valid['sources'][1:]]}]
        for data in malformed:
            with self.subTest(data_type=type(data).__name__):
                raw=u.encode(data);sid=u.digest(raw);p=self.store/'snapshots'/sid;p.mkdir(exist_ok=True);(p/'manifest.json').write_bytes(raw)
                (self.store/'active.json').write_bytes(u.encode({'active':sid,'previous':None}))
                out=io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(u.main(['--store',str(self.store),'inspect']),1)
                self.assertEqual(json.loads(out.getvalue())['status'],'failed')

    def test_failed_check_cli_exit_not_success(self):
        self.active()
        with patch.object(u,'fetch',side_effect=OSError('HTTP 429')),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(u.main(['--store',str(self.store),'check']),1)

if __name__ == '__main__':
    unittest.main()
