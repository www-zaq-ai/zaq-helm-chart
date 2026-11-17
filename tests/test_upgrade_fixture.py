"""Offline safety checks for fetching the historical upgrade-test chart."""

import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from integration import LEGACY_CHART_COMMIT, legacy_chart


class UpgradeFixtureTests(unittest.TestCase):
    def archive(self, names):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name in names:
                content = b"fixture only\n"
                member = tarfile.TarInfo(f"zaq-helm-chart-{LEGACY_CHART_COMMIT}/{name}")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        return buffer.getvalue()

    def test_only_chart_files_are_extracted_from_verified_source(self):
        data = self.archive(["charts/zaq/Chart.yaml", "charts/zaq/templates/service.yaml", "README.md"])
        with tempfile.TemporaryDirectory() as directory, \
                patch("integration.urlopen", return_value=io.BytesIO(data)) as fetch, \
                patch("integration.LEGACY_CHART_SHA256", hashlib.sha256(data).hexdigest()):
            chart = legacy_chart(directory)
            self.assertTrue((chart / "Chart.yaml").is_file())
            self.assertTrue((chart / "templates/service.yaml").is_file())
            self.assertFalse((chart / "README.md").exists())
            self.assertEqual(chart.parent, Path(directory))
            self.assertIn(LEGACY_CHART_COMMIT, fetch.call_args.args[0])

    def test_checksum_mismatch_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("integration.urlopen", return_value=io.BytesIO(b"wrong source")):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                legacy_chart(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unsafe_or_missing_chart_fails(self):
        for names in [["charts/zaq/../../outside"], ["README.md"]]:
            data = self.archive(names)
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory, \
                    patch("integration.urlopen", return_value=io.BytesIO(data)), \
                    patch("integration.LEGACY_CHART_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(RuntimeError):
                    legacy_chart(directory)
