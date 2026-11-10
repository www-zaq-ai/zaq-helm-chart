import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from release import TEST_REPOSITORY, assert_version_absent, publish_chart, release_version


class ReleaseTests(unittest.TestCase):
    @patch("release.subprocess.run")
    @patch("release.assert_version_absent")
    @patch("release.urlopen")
    @patch.dict("os.environ", {"GHCR_USERNAME": "test", "GHCR_TOKEN": "not-a-real-token"})
    def test_shared_publisher_keeps_test_namespace_and_version(self, request, absent, command):
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(b'{"token":"test-bearer"}')
        request.return_value = response
        publish_chart("charts/zaq", "0.1.0-test.123.1", TEST_REPOSITORY)
        absent.assert_called_once_with("0.1.0-test.123.1", "test-bearer", TEST_REPOSITORY)
        commands = [call.args[0] for call in command.call_args_list]
        package = next(cmd for cmd in commands if cmd[1] == "package")
        self.assertEqual(package[package.index("--version") + 1], "0.1.0-test.123.1")
        push = next(cmd for cmd in commands if cmd[1] == "push")
        self.assertEqual(push[-1], "oci://ghcr.io/www-zaq-ai/charts/test")
        show = next(cmd for cmd in commands if cmd[1:3] == ["show", "chart"])
        self.assertIn("oci://ghcr.io/" + TEST_REPOSITORY, show)

    def test_unexpected_publish_repositories_are_rejected(self):
        with self.assertRaises(ValueError):
            publish_chart("charts/zaq", "0.1.0", "unrelated/chart")
        with self.assertRaises(ValueError):
            assert_version_absent("0.1.0", "test", "unrelated/chart")

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
