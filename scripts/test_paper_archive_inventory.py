"""Synthetic metadata tests only; no real archive-wide acceptance."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from paper_archive_inventory import inventory, main


def sample(**changes):
    return dict({'protocol': 'synthetic-v1', 'generated_at_utc': '2026-11-17T20:00:00Z',
                 'forecasts': [{}, {}]}, **changes)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_metadata_and_dynamic_discovery(self):
        self.write('one.json', sample())
        first = inventory(self.root)
        self.assertEqual(first['file_count'], 1)
        self.assertEqual(first['files'][0]['forecast_count'], 2)
        self.write('another.JSON', sample(protocol='different-label', forecasts=[]))
        second = inventory(self.root)
        self.assertEqual(second['file_count'], 2)
        self.assertEqual(second['metadata_ok_count'], 2)
        self.assertEqual(second['forecast_validation'], 'not_assessed')
        self.assertFalse(second['betting_release'])

    def test_corrupt_file_does_not_block_good_file(self):
        self.write('good.json', sample())
        (self.root / 'broken.json').write_text('{')
        result = inventory(self.root)
        self.assertEqual(result['status'], 'complete_with_errors')
        self.assertTrue(result['execution_ok'])
        self.assertEqual(result['metadata_ok_count'], 1)
        self.assertEqual(result['invalid_file_count'], 1)

    def test_invalid_metadata(self):
        cases = [[], sample(protocol=' '), sample(protocol=3), sample(forecasts=None),
                 sample(generated_at_utc=None), sample(generated_at_utc='2026-11-17T20:00:00'),
                 sample(generated_at_utc='invalid')]
        for data in cases:
            with self.subTest(data=data):
                self.write('case.json', data)
                self.assertEqual(inventory(self.root)['invalid_file_count'], 1)

    def test_timezone_normalization(self):
        self.write('offset.json', sample(generated_at_utc='2026-11-17T21:00:00+01:00'))
        self.assertEqual(inventory(self.root)['files'][0]['generated_at_utc'], '2026-11-17T20:00:00+00:00')

    def test_empty_missing_and_non_directory(self):
        self.assertEqual(inventory(self.root)['status'], 'empty')
        self.assertEqual(inventory(self.root / 'absent')['status'], 'source_error')
        path = self.write('file.json', sample())
        self.assertFalse(inventory(path)['execution_ok'])

    def test_read_failures_are_local(self):
        path = self.write('file.json', sample())
        with patch.object(Path, 'read_text', side_effect=PermissionError('synthetic denial')):
            self.assertEqual(inventory(self.root)['invalid_file_count'], 1)
        path.write_bytes(b'\\xff')
        self.assertEqual(inventory(self.root)['invalid_file_count'], 1)

    def test_non_json_ignored_and_json_directory_rejected(self):
        (self.root / 'note.txt').write_text('ignored')
        (self.root / 'directory.json').mkdir()
        self.assertEqual(inventory(self.root)['file_count'], 1)
        self.assertEqual(inventory(self.root)['invalid_file_count'], 1)

    def test_symlink_not_followed(self):
        target = self.write('target.txt', sample())
        (self.root / 'link.json').symlink_to(target)
        self.assertEqual(inventory(self.root)['invalid_file_count'], 1)

    def test_repeatable_and_read_only(self):
        self.write('z.json', sample())
        self.write('a.json', sample())
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = inventory(self.root)
        self.assertEqual(result, inventory(self.root))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual([Path(r['path']).name for r in result['files']], ['a.json', 'z.json'])

    def test_cli_json_and_exit_status(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([str(self.root)]), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'empty')
        self.write('bad.json', {})
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([str(self.root)]), 1)
        self.assertEqual(json.loads(output.getvalue())['invalid_file_count'], 1)


if __name__ == '__main__':
    unittest.main()
