"""Real Git + Windows PowerShell integration tests; only disposable repositories."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ['git-common', 'save', 'restore', 'autosave', 'history', 'start-ai-task',
           'finish-ai-task', 'version-status', 'start-ai-worktree', 'publish-main']

class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dashboard-git-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith('GIT_') or key == 'DASHBOARD_ALLOW_MAIN':
                self.env.pop(key)
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git('init')
        self.git('symbolic-ref', 'HEAD', 'refs/heads/main')
        self.git('config', 'user.name', 'Workflow Test')
        self.git('config', 'user.email', 'test@localhost')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        (self.repo / 'scripts').mkdir()
        for script in SCRIPTS:
            shutil.copyfile(ROOT / 'scripts' / (script + '.ps1'), self.repo / 'scripts' / (script + '.ps1'))
        shutil.copytree(ROOT / '.githooks', self.repo / '.githooks')
        shutil.copyfile(ROOT / '.gitattributes', self.repo / '.gitattributes')
        self.write('sample.txt', 'base\n')
        self.write('delete.txt', 'delete me\n')
        self.write('.gitignore', '*.sqlite*\n.env\n')
        self.git('add', '-A')
        self.git('commit', '-m', 'fixture')
        self.initial = self.git('rev-parse', 'HEAD').stdout.strip()
        self.git('config', 'core.hooksPath', '.githooks')

    def run_cmd(self, args, ok=True, repo=None, env=None):
        result = subprocess.run(args, cwd=repo or self.repo, env=env or self.env,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def git(self, *args, **kw):
        return self.run_cmd(['git', *args], **kw)

    def ps(self, script, *args, **kw):
        return self.run_cmd(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str((kw.get('repo') or self.repo) / 'scripts' / (script + '.ps1')), *args], **kw)

    def write(self, name, value, repo=None):
        path = (repo or self.repo) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def task(self):
        self.ps('start-ai-task', '-Agent', 'Codex', '-Task', 'Test change!')

    def checkpoint(self):
        self.ps('save')
        self.assertEqual(self.git('status', '--porcelain').stdout, '')

    def test_01_clean_checkpoint_no_commit(self):
        self.assertIn('No changes', self.ps('save').stdout)
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.initial)
        self.assertEqual(self.git('tag').stdout, '')

    def test_02_modified_commit_tag_changelog_no_loop(self):
        self.task()
        self.write('sample.txt', 'changed\nsecond\n')
        self.checkpoint()
        self.assertEqual(self.git('tag').stdout.strip(), 'build-0001')
        log = (self.repo / 'CHANGELOG-AUTO.md').read_text()
        self.assertIn('### Modified\n- sample.txt', log)
        self.assertIn('2 insertions', log)
        self.assertIn('1 deletions', log)
        self.assertEqual(self.git('rev-parse', 'build-0001^{commit}').stdout, self.git('rev-parse', 'HEAD').stdout)
        head = self.git('rev-parse', 'HEAD').stdout
        self.checkpoint()
        self.assertEqual(head, self.git('rev-parse', 'HEAD').stdout)

    def test_03_added(self):
        self.task()
        self.write('new file.txt', 'new\n')
        self.checkpoint()
        self.assertIn('### Added\n- new file.txt', (self.repo / 'CHANGELOG-AUTO.md').read_text())

    def test_04_deleted(self):
        self.task()
        (self.repo / 'delete.txt').unlink()
        self.checkpoint()
        self.assertIn('### Deleted\n- delete.txt', (self.repo / 'CHANGELOG-AUTO.md').read_text())

    def test_05_numbering_uses_max_tag_all_branches(self):
        self.task()
        self.write('sample.txt', 'one\n'); self.checkpoint()
        self.write('sample.txt', 'two\n'); self.checkpoint()
        self.assertIn('build-0002', self.git('tag').stdout)
        self.git('tag', 'build-0099', self.initial)
        self.write('sample.txt', 'three\n'); self.checkpoint()
        self.assertIn('build-0100', self.git('tag').stdout)

    def test_06_start_sanitizes_and_reports(self):
        self.task()
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'ai/codex/test-change')
        self.assertEqual(self.git('rev-parse', 'dev').stdout.strip(), self.initial)
        self.assertEqual(self.git('rev-parse', 'main').stdout.strip(), self.initial)

    def test_07_finish_review_then_explicit_dev_merge(self):
        self.task()
        self.write('sample.txt', 'task\n')
        result = self.ps('finish-ai-task')
        self.assertIn('Commits ahead: 1', result.stdout)
        self.assertIn('sample.txt', result.stdout)
        self.assertEqual(self.git('rev-parse', 'dev').stdout.strip(), self.initial)
        self.ps('finish-ai-task', '-Merge')
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'dev')
        self.assertEqual(self.git('rev-parse', 'main').stdout.strip(), self.initial)

    def test_08_main_block_and_override(self):
        self.write('sample.txt', 'protected\n')
        self.git('add', 'sample.txt')
        self.git('commit', '-m', 'accident', ok=False)
        self.ps('save', ok=False)
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.initial)
        self.ps('save', '-AllowMain')
        self.assertIn('build-0001', self.git('tag').stdout)
        self.assertNotIn('DASHBOARD_ALLOW_MAIN', self.env)

    def test_09_restore_preserves_history_and_handles_repeat(self):
        self.task()
        self.write('sample.txt', 'first\n'); self.checkpoint()
        self.write('sample.txt', 'second\n'); self.checkpoint()
        latest = self.git('rev-parse', 'HEAD').stdout
        self.ps('restore', '-Build', 'build-0001')
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'recovery/build-0001')
        self.assertEqual((self.repo / 'sample.txt').read_text(), 'first\n')
        self.assertEqual(self.git('rev-parse', 'ai/codex/test-change').stdout, latest)
        self.ps('restore', '-Tag', 'build-0001')
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'recovery/build-0001-2')

    def test_10_dirty_start_restore_worktree_refuse(self):
        self.git('tag', 'build-0001')
        self.write('unsaved.txt', 'precious\n')
        self.ps('start-ai-task', '-Agent', 'codex', '-Task', 'dirty', ok=False)
        self.ps('restore', 'build-0001', ok=False)
        self.ps('start-ai-worktree', '-Agent', 'codex', '-Task', 'dirty', '-Path', str(self.base/'wt'), ok=False)
        self.assertEqual((self.repo/'unsaved.txt').read_text(), 'precious\n')
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'main')

    def test_11_watcher_real_interval_and_clean_once(self):
        self.task()
        self.ps('autosave', '-Once')
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.initial)
        self.write('sample.txt', 'watch\n')
        proc = subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                 str(self.repo/'scripts/autosave.ps1'), '-IntervalSeconds', '1'],
                                cwd=self.repo, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if 'build-0001' in self.git('tag').stdout: break
                time.sleep(.25)
            self.assertIn('build-0001', self.git('tag').stdout)
            head = self.git('rev-parse', 'HEAD').stdout
            time.sleep(2)
            self.assertEqual(head, self.git('rev-parse', 'HEAD').stdout)
        finally:
            proc.terminate(); proc.wait(timeout=10)

    def test_12_worktree_separate_branch_global_numbering(self):
        wt = self.base/'agent space'
        self.ps('start-ai-worktree', '-Agent', 'astra', '-Task', 'parallel', '-Path', str(wt))
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'main')
        self.assertEqual(self.git('branch', '--show-current', repo=wt).stdout.strip(), 'ai/astra/parallel')
        self.write('sample.txt', 'worktree\n', repo=wt)
        self.ps('save', repo=wt)
        self.assertEqual((self.repo/'sample.txt').read_text(), 'base\n')
        self.task(); self.write('sample.txt', 'primary\n'); self.checkpoint()
        self.assertIn('build-0002', self.git('tag').stdout)
        self.ps('start-ai-worktree', '-Agent', 'astra', '-Task', 'parallel', '-Path', str(self.base/'other'), ok=False)

    def test_13_rename_binary_unicode_and_staged_mix(self):
        self.task()
        self.git('mv', 'sample.txt', 'renamed.txt')
        self.write('new.txt', 'stage one\n'); self.git('add', 'new.txt')
        self.write('new.txt', 'stage two\n')
        self.write('za\u017c\u00f3\u0142\u0107.txt', 'utf8\n')
        (self.repo/'binary.bin').write_bytes(b'\x00\xff\x01')
        self.checkpoint()
        log = (self.repo/'CHANGELOG-AUTO.md').read_text()
        self.assertIn('### Renamed\n- sample.txt -> renamed.txt', log)
        self.assertIn('1 binary files', log)
        self.assertEqual(self.git('show','HEAD:new.txt').stdout, 'stage two\n')

    def test_14_failure_preserves_index_and_log_then_retry(self):
        self.task(); self.write('sample.txt', 'first\n'); self.checkpoint()
        oldlog = (self.repo/'CHANGELOG-AUTO.md').read_bytes()
        self.write('sample.txt', 'staged\n'); self.git('add', 'sample.txt')
        self.write('sample.txt', 'unstaged\n')
        oldindex = (self.repo/'.git/index').read_bytes()
        self.git('config', 'user.name', '')
        self.ps('save', ok=False)
        self.assertEqual(oldindex, (self.repo/'.git/index').read_bytes())
        self.assertEqual(oldlog, (self.repo/'CHANGELOG-AUTO.md').read_bytes())
        self.assertEqual((self.repo/'sample.txt').read_text(), 'unstaged\n')
        self.git('config', 'user.name', 'Workflow Test'); self.checkpoint()
        self.assertEqual((self.repo/'CHANGELOG-AUTO.md').read_text().count('## build-0002'), 1)

    def test_15_merge_conflict_stops_without_resolution(self):
        self.task(); self.write('sample.txt', 'AI\n'); self.checkpoint()
        self.git('switch','dev'); self.write('sample.txt', 'DEV\n'); self.checkpoint()
        self.git('switch','ai/codex/test-change')
        self.ps('finish-ai-task', '-Merge', ok=False)
        self.assertTrue(self.git('ls-files', '--unmerged').stdout)
        self.assertIn('<<<<<<<', (self.repo/'sample.txt').read_text())
        self.ps('save', ok=False)
        self.assertEqual(self.git('rev-parse','main').stdout.strip(), self.initial)

    def test_16_legacy_tag_restore_and_invalid_tag(self):
        self.git('tag','save-20260101-010101')
        self.ps('restore', 'build-9999', ok=False)
        self.ps('restore', '--bad', ok=False)
        self.ps('restore', 'save-20260101-010101')
        self.assertTrue(self.git('branch', '--show-current').stdout.startswith('recovery/save-'))

    def test_17_secrets_ignored_and_new_credential_refused(self):
        self.task()
        self.write('.env', 'SECRET=private\n')
        self.write('private.sqlite', 'private\n')
        self.write('sample.txt', 'safe\n'); self.checkpoint()
        self.assertNotIn('.env', self.git('ls-files').stdout)
        self.write('token.txt', 'ghp_' + 'x'*36)
        self.ps('save', ok=False)
        self.assertNotIn('x'*36, self.ps('save', ok=False).stdout)
        self.assertNotIn('token.txt', self.git('ls-files').stdout)
        (self.repo/'token.txt').unlink()
        self.write('token.txt', 'github_pat_' + 'x'*40)
        self.ps('save', ok=False)
        self.assertNotIn('token.txt', self.git('ls-files').stdout)

    def test_18_status_and_history(self):
        self.assertIn('Hooks: enabled', self.ps('version-status').stdout)
        self.assertIn('origin not configured', self.ps('version-status').stdout)
        self.ps('history')

    def test_19_push_explicit_and_no_remote_local_success(self):
        self.task(); self.write('sample.txt','local\n')
        self.ps('save','-Push',ok=False)
        self.assertIn('build-0001',self.git('tag').stdout)
        bare=self.base/'remote.git'; self.git('init','--bare',str(bare))
        self.git('remote','add','origin',str(bare))
        self.write('sample.txt','remote\n'); self.ps('save','-Push')
        self.assertIn('refs/tags/build-0002',self.git('ls-remote','origin').stdout)

    def test_26_publish_main_and_master_with_release_backup(self):
        bare = self.base/'remote.git'
        self.git('init', '--bare', str(bare))
        self.git('remote', 'add', 'origin', str(bare))
        self.git('push', 'origin', 'main:main', 'main:master')
        self.task()
        self.write('sample.txt', 'published\n')
        self.ps('finish-ai-task', '-Merge')
        self.git('switch', 'main')
        result = self.ps('publish-main')
        self.assertIn('Published main and master', result.stdout)
        local = self.git('rev-parse', 'main').stdout.strip()
        refs = self.git('ls-remote', 'origin').stdout
        self.assertIn(f'{local}\trefs/heads/main', refs)
        self.assertIn(f'{local}\trefs/heads/master', refs)
        self.assertIn('refs/tags/release/', refs)
        self.assertIn('Nothing to publish', self.ps('publish-main').stdout)
        self.assertNotIn('refs/tags/build-0001',self.git('ls-remote','origin').stdout)

    def test_20_detached_and_nested_worktree_refuse(self):
        self.ps('start-ai-worktree','-Agent','codex','-Task','nested','-Path',str(self.repo/'nested'),ok=False)
        self.git('checkout','--detach')
        self.write('sample.txt','detached\n')
        self.ps('save',ok=False)
        self.assertEqual(self.git('rev-parse','HEAD').stdout.strip(),self.initial)

    def test_21_ignored_collision_not_overwritten_on_restore(self):
        self.git('tag','build-0001')
        self.task()
        self.git('rm','delete.txt')
        self.write('.gitignore','*.sqlite*\n.env\ndelete.txt\n'); self.checkpoint()
        self.write('delete.txt','ignored precious\n')
        self.ps('restore','build-0001',ok=False)
        self.assertEqual((self.repo/'delete.txt').read_text(),'ignored precious\n')


    def test_22_shared_lock_rejects_second_helper(self):
        self.task(); self.write('sample.txt', 'locked\n')
        signal = self.base/'lock-ready'
        command = "$s=[IO.File]::Open('" + str(self.repo/'.git/dashboard-backup.lock') + "','OpenOrCreate','ReadWrite','None'); try { [IO.File]::WriteAllText('" + str(signal) + "','ready'); Start-Sleep -Seconds 30 } finally { $s.Dispose() }"
        proc = subprocess.Popen(['powershell.exe','-NoProfile','-Command',command],env=self.env,
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+10
            while not signal.exists() and time.monotonic()<deadline: time.sleep(.05)
            self.assertTrue(signal.exists())
            result=self.ps('save',ok=False)
            self.assertIn('Another Git helper',result.stderr)
            self.assertEqual(self.git('rev-parse','HEAD').stdout.strip(),self.initial)
        finally:
            proc.terminate(); proc.wait(timeout=10)
        self.checkpoint()

    def test_23_concurrent_worktrees_allocate_unique_builds(self):
        a=self.base/'a'; b=self.base/'b'
        for folder,agent in [(a,'astra'),(b,'codex')]:
            self.ps('start-ai-worktree','-Agent',agent,'-Task','parallel','-Path',str(folder))
            self.write('sample.txt',agent+'\n',repo=folder)
        procs=[]
        for folder in (a,b):
            procs.append(subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(folder/'scripts/save.ps1')],
                                          cwd=folder,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        for folder,proc in zip((a,b),procs):
            output,error=proc.communicate(timeout=30)
            if proc.returncode:
                self.assertIn(b'Another Git helper',error)
                self.ps('save',repo=folder)
        self.assertEqual(self.git('tag').stdout.splitlines(),['build-0001','build-0002'])
        for folder,agent in [(a,'astra'),(b,'codex')]:
            self.assertEqual(self.git('show','HEAD:sample.txt',repo=folder).stdout,agent+'\n')

    def test_24_main_merge_hook_blocks_and_override_allows(self):
        self.task(); self.write('sample.txt','merge\n'); self.checkpoint()
        self.git('switch','main')
        self.git('merge','--no-ff','--no-edit','ai/codex/test-change',ok=False)
        self.assertEqual(self.git('rev-parse','HEAD').stdout.strip(),self.initial)
        self.git('merge','--abort')
        env=dict(self.env,DASHBOARD_ALLOW_MAIN='1')
        self.git('merge','--no-ff','--no-edit','ai/codex/test-change',env=env)

    def test_25_sync_requires_existing_remote_dev_and_ff(self):
        self.ps('start-ai-task','-Agent','codex','-Task','sync','-Sync',ok=False)
        self.assertEqual(self.git('branch','--show-current').stdout.strip(),'dev')
        bare=self.base/'remote.git'; self.git('init','--bare',str(bare))
        self.git('remote','add','origin',str(bare)); self.git('push','origin','dev')
        self.ps('start-ai-task','-Agent','codex','-Task','sync','-Sync')
        self.assertEqual(self.git('branch','--show-current').stdout.strip(),'ai/codex/sync')

if __name__ == '__main__':
    unittest.main()
