import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from release import assert_version_absent, release_version


class ReleaseTests(unittest.TestCase):
    def test_matching_tag(self):
        self.assertEqual(release_version("chart-v0.1.0", "0.1.0"), "0.1.0")
        self.assertEqual(release_version("chart-v0.2.0-rc.1", "0.2.0-rc.1"), "0.2.0-rc.1")

    def test_refuse_mismatch_or_non_chart_tags(self):
        for tag in ["v0.1.0", "chart-v0.2.0", "chart-v01.1.0", "chart-v0.1.0;echo bad", "chart-v0.1"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_version(tag, "0.1.0")

    @patch("release.urlopen")
    def test_refuse_existing_version(self, request):
        request.return_value = MagicMock()
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            assert_version_absent("0.1.0", "test-only")

    @patch("release.urlopen")
    def test_allow_only_confirmed_missing_manifests(self, request):
        for status, code in [(404, "MANIFEST_UNKNOWN"), (404, "NAME_UNKNOWN"),
                             (401, "UNAUTHORIZED"), (403, "DENIED"),
                             (500, "UNKNOWN"), (404, "DENIED")]:
            with self.subTest(status=status, code=code):
                body = io.BytesIO(json.dumps({"errors": [{"code": code}]}).encode())
                request.side_effect = HTTPError("https://example.org", status, "test", {}, body)
                if status == 404 and code in {"MANIFEST_UNKNOWN", "NAME_UNKNOWN"}:
                    assert_version_absent("0.1.0", "test-only")
                else:
                    with self.assertRaises(RuntimeError):
                        assert_version_absent("0.1.0", "test-only")
