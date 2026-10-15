import csv
import io
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'soulsleek_downloader' / 'app'))
import download_recovery as recovery
import main
from youtube_fallback import missing_tracks


class RecoveryTests(unittest.TestCase):
    def test_limits_respect_hard_limit_and_never_lower_existing_limit(self):
        for soft, hard, expected in [(1024, 8192, 8192), (1024, 65536, 16384),
                                     (32768, 65536, None), (-1, -1, None), (1024, -1, 16384)]:
            with self.subTest(soft=soft, hard=hard), \
                    patch.object(resource, 'getrlimit', return_value=(soft, hard)), \
                    patch.object(resource, 'setrlimit') as setlimit:
                recovery.configure_file_limit()
                if expected is None:
                    setlimit.assert_not_called()
                else:
                    setlimit.assert_called_once_with(resource.RLIMIT_NOFILE, (expected, hard))

    def test_refused_limit_does_not_abort(self):
        with patch.object(resource, 'getrlimit', return_value=(1024, 65536)), \
                patch.object(resource, 'setrlimit', side_effect=OSError('denied')):
            recovery.configure_file_limit()

    def test_real_child_inherits_raised_soft_limit(self):
        script = '''import resource, subprocess, sys
from download_recovery import configure_file_limit
resource.setrlimit(resource.RLIMIT_NOFILE, (256, 4096))
configure_file_limit()
subprocess.run([sys.executable, '-c', 'import resource; assert resource.getrlimit(resource.RLIMIT_NOFILE) == (4096, 4096)'], check=True)
'''
        import os
        subprocess.run([sys.executable, '-c', script], check=True,
                       env=dict(os.environ, PYTHONPATH=str(Path(recovery.__file__).parent)))

    def test_abort_reconciles_pending_absent_and_retry_exhausted_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist, index = root / 'playlist.csv', root / 'index.csv'
            with playlist.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['artist', 'title', 'album', 'length'])
                for title in ['Complete', 'Bonobo retries', 'Pending', 'Never started']:
                    writer.writerow(['Artist', title, 'Album', '180'])
            index.write_text(','.join(recovery.HEADER) + '\n' +
                             'x.mp3,Artist,Album,Complete,180,0,1,0\n' +
                             ',Artist,Album,Bonobo retries,180,0,2,2\n' +
                             ',Artist,Album,Pending,180,0,0,0\n')
            process = Mock(stdout=io.StringIO('Out of download retries: Bonobo retries\n'), returncode=-6)
            with patch.object(main.os.path, 'exists', return_value=True), \
                    patch.object(main.subprocess, 'Popen', return_value=process), \
                    patch.object(main, 'configure_file_limit'), patch('sys.stdout', io.StringIO()) as output:
                success, failed = main.download_music(str(playlist), directory, str(root/'log'),
                                                     'user', 'password', 'mp3', str(index))
            self.assertFalse(success)
            self.assertEqual(len(failed), 3)
            self.assertEqual([t['title'] for t in missing_tracks(index)],
                             ['Bonobo retries', 'Pending', 'Never started'])
            self.assertIn('SIGABRT', output.getvalue())

    def test_missing_or_truncated_index_uses_complete_audio_tags_not_partial_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist, index = root/'playlist.csv', root/'index.csv'
            playlist.write_text('artist,title,album,length\nArtist,Complete,Album,180\nArtist,Missing,Album,180\n')
            (root/'complete.flac').touch()
            (root/'partial.mp3.incomplete').touch()
            audio = {'artist': ['Artist'], 'title': ['Complete'], 'album': ['Album']}
            audio = Mock(wraps=audio, tags=True, info=Mock(length=180))
            for content in [None, '', ','.join(recovery.HEADER)+'\nx.mp3,Artist,Album,Complete,180,0,']:
                if content is not None:
                    index.write_text(content)
                with patch.object(recovery, 'File', return_value=audio) as read:
                    self.assertEqual(recovery.rebuild_crashed_index(playlist, index, root), 1)
                    self.assertEqual(read.call_count, 1)
                    self.assertEqual([t['title'] for t in missing_tracks(index)], ['Missing'])

    def test_text_summary_includes_retries_once_without_index(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock(stdout=io.StringIO('Out of download retries: Bonobo\nOut of download retries: Bonobo\n'), returncode=1)
            with patch.object(main.os.path, 'exists', return_value=True), \
                    patch.object(main.subprocess, 'Popen', return_value=process), \
                    patch.object(main, 'configure_file_limit'):
                success, failed = main.download_music('playlist.csv', directory, str(Path(directory)/'log'),
                                                     'user', 'password', 'mp3')
            self.assertEqual(failed, ['Bonobo'])
            self.assertFalse(success)
