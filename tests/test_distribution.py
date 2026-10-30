"""Offline distribution checks; no model calls, credentials or installed user config."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins' / 'website-studio'
HELPER = PLUGIN / 'scripts' / 'website_upstreams.py'


def load_helper(path=HELPER):
    spec = importlib.util.spec_from_file_location('distribution_upstreams', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


class DistributionTests(unittest.TestCase):
    def test_marketplace_and_manifests(self):
        self.assertTrue((PLUGIN / 'plugin.json').is_file(), 'portable manifest missing')
        manifest = json.loads((PLUGIN / 'plugin.json').read_text())
        compat = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())
        market = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual(manifest['$schema'], 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json')
        self.assertEqual((manifest['name'], manifest['version']), ('website-studio', '1.0.0'))
        self.assertEqual((compat['name'], compat['version']), (manifest['name'], manifest['version']))
        self.assertEqual(compat['skills'], './skills/')
        self.assertEqual(market['name'], 'pattrndata-private')
        self.assertEqual(len(market['plugins']), 1)
        self.assertEqual(market['plugins'][0]['source'], {'source': 'local', 'path': './plugins/website-studio'})
        self.assertFalse(any((PLUGIN / p).exists() for p in ['mcp.json', '.mcp.json', '.app.json', 'hooks']))
        self.assertEqual(list((PLUGIN / 'skills').rglob('SKILL.md')), [PLUGIN / 'skills/website-studio/SKILL.md'])

    def test_pinned_sources_and_notices(self):
        self.assertTrue(HELPER.is_file(), 'portable helper missing')
        u = load_helper()
        state = u.pointer(u.DEFAULT_STORE)
        manifest = u.validate(u.DEFAULT_STORE, state['active'])
        self.assertIsNone(state['previous'])
        self.assertEqual(len(manifest['sources']), 6)
        self.assertEqual(sum(len(s['files']) for s in manifest['sources']), 16)
        self.assertEqual(len(list((u.DEFAULT_STORE / 'snapshots').iterdir())), 1)
        self.assertTrue((PLUGIN / 'THIRD_PARTY_NOTICES.md').is_file())
        for source in manifest['sources']:
            self.assertIn(source['repo'], (PLUGIN / 'THIRD_PARTY_NOTICES.md').read_text())

    def test_relocated_inspect_without_network_or_package_writes(self):
        self.assertTrue(HELPER.is_file(), 'portable helper missing')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            location = Path(tmp) / 'portable path with spaces'
            shutil.copytree(PLUGIN, location)
            before = tree_bytes(location)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, str(location / 'scripts/website_upstreams.py'), 'inspect'], cwd=tmp, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(len(json.loads(result.stdout)['manifest']['sources']), 6)
            self.assertEqual(tree_bytes(location), before)

    def test_bundled_mutations_refused_before_provider_or_file_writes(self):
        self.assertTrue(HELPER.is_file(), 'portable helper missing')
        u = load_helper()
        before = tree_bytes(PLUGIN)
        snapshot = u.pointer(u.DEFAULT_STORE)['active']
        # Stub operational entrypoints only for this inert-CLI boundary test.
        # Fixture results are never treated as provider or production evidence.
        with patch.object(u, 'fetch', side_effect=AssertionError('must not fetch')), patch.object(u, 'stage', return_value={'status': 'OFFLINE FIXTURE'}), patch.object(u, 'activate', return_value={'status': 'OFFLINE FIXTURE'}), contextlib.redirect_stdout(io.StringIO()):
            for args in [['stage'], ['activate', snapshot], ['--store', str(u.DEFAULT_STORE), 'stage']]:
                with self.subTest(args=args):
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                        u.main(args)
                    self.assertEqual(raised.exception.code, 2)
        self.assertEqual(tree_bytes(PLUGIN), before)

    def test_inert_cli_and_default_dry_run(self):
        self.assertTrue(HELPER.is_file(), 'portable helper missing')
        before = tree_bytes(PLUGIN)
        u = load_helper()
        for args in [['--help'], ['--version'], [], ['unknown'], ['--typo']]:
            with self.subTest(args=args), patch.object(u, 'fetch', side_effect=AssertionError('must not fetch')), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                u.main(args)
        with patch.object(u, 'fetch', side_effect=AssertionError('must not fetch')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(u.main(['stage', '--dry-run']), 0)
        self.assertEqual(tree_bytes(PLUGIN), before)

    def test_coordinator_has_no_host_or_tool_loader_dependency(self):
        skill = PLUGIN / 'skills/website-studio/SKILL.md'
        self.assertTrue(skill.is_file(), 'portable coordinator missing')
        text = skill.read_text()
        for mode in ['create', 'analyse', 'refine', 'redesign']:
            self.assertIn(mode, text.lower())
        self.assertIn('references/workflows.md', text)
        for path in [skill, *(skill.parent / 'references').glob('*.md')]:
            content = path.read_text()
            self.assertNotRegex(content, r'/(?:home|Users)/')
            for dependency in ['skill_view(', 'hermes skills', 'website-ops', 'default-worker-', '3b24ef8a55a5']:
                self.assertNotIn(dependency, content)
        self.assertIn('reference data', text)
        self.assertIn('read-only', text)

    def test_provenance_and_private_package(self):
        self.assertTrue((ROOT / 'PROVENANCE.json').is_file(), 'provenance missing')
        provenance = json.loads((ROOT / 'PROVENANCE.json').read_text())
        self.assertEqual(provenance['upstream_snapshot'], json.loads((PLUGIN / 'upstream/active.json').read_text())['active'])
        self.assertTrue((ROOT / 'LICENSE').is_file())
        self.assertIn('private', (ROOT / 'README.md').read_text().lower())
        for p in ROOT.rglob('*'):
            if '.git' in p.parts or not p.is_file():
                continue
            self.assertNotIn(p.name, ['hosts.yml', 'auth.json', '.env', 'config.yaml', 'state.db'])
            if p.suffix in ['.md', '.py', '.json', '.yml', '.toml']:
                self.assertNotRegex(p.read_text(), r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-proj-[A-Za-z0-9_-]{20,})')


if __name__ == '__main__':
    unittest.main()
