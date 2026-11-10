import copy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from prerelease import (GitHub, MARKER, PACKAGE_API, REPO_API, TAG_PREFIX,
                        TEST_REPOSITORY, cleanup, expired, inventory, main, publish,
                        tag_version, test_version as make_version)


NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
SOURCE = "a" * 40


def version(run):
    return f"0.1.0-test.{run}.1"


def release(run, age):
    date = (NOW - timedelta(days=age)).isoformat()
    return {"id": run + 2000, "tag_name": TAG_PREFIX + version(run),
            "created_at": date, "published_at": date, "draft": False, "prerelease": True,
            "body": f"{MARKER}\n\nSource commit: `{SOURCE}`\n"}


def package(run, age):
    return {"id": run + 1000, "created_at": (NOW - timedelta(days=age)).isoformat(),
            "metadata": {"container": {"tags": [version(run)]}}}


def fake_api(releases, packages):
    api = MagicMock()
    api.list_all.side_effect = [releases, packages]

    def request(method, path, *args, **kwargs):
        if method == "DELETE":
            return None
        if path.startswith(PACKAGE_API + "/versions/"):
            return next(p for p in packages if path.endswith("/" + str(p["id"])))
        if path.startswith(REPO_API + "/releases/"):
            return next(r for r in releases if path.endswith("/" + str(r["id"])))
        if path.startswith(REPO_API + "/git/ref/tags/"):
            return {"object": {"type": "commit", "sha": SOURCE}}
        raise AssertionError(path)

    api.request.side_effect = request
    return api


def mutations(api):
    return [call.args[:2] for call in api.request.call_args_list if call.args[0] != "GET"]


class RetentionTests(unittest.TestCase):
    def test_old_versions_except_newest_three(self):
        records = inventory([release(i, age) for i, age in enumerate([1, 2, 3, 8, 9, 10], 1)], [])
        self.assertEqual({r.version for r in expired(records, NOW)}, {version(4), version(5), version(6)})

    def test_keep_newest_three_even_when_all_old(self):
        records = inventory([], [package(i, 20 - i) for i in range(1, 6)])
        self.assertEqual({r.version for r in expired(records, NOW)}, {version(1), version(2)})
        self.assertEqual(expired(records[:2], NOW), [])

    def test_keep_every_version_inside_seven_days(self):
        self.assertEqual(expired(inventory([], [package(i, i) for i in range(1, 7)]), NOW), [])

    def test_age_boundary_is_strict_and_uses_newest_artifact_time(self):
        records = inventory([release(i, i) for i in range(1, 4)] + [release(7, 7), release(8, 8)],
                            [package(8, 2)])
        self.assertEqual(expired(records, NOW), [])
        record = inventory([], [package(i, i) for i in range(1, 4)] + [package(7, 7)])[3]
        self.assertEqual(expired(records[:3] + [record], NOW), [])
        self.assertEqual([r.version for r in expired(records[:3] + [record], NOW + timedelta(seconds=1))], [version(7)])

    def test_production_artifacts_are_not_candidates(self):
        stable = release(1, 99)
        stable["tag_name"] = "chart-v0.1.0"
        stable["prerelease"] = False
        production = package(1, 99)
        production["metadata"]["container"]["tags"] = ["0.1.0", "latest"]
        self.assertEqual(inventory([stable], [production]), [])
        for tag in ["chart-v0.1.0", "chart-test-v0.1.0", "chart-test-v0.1.0-test.1.1-extra"]:
            self.assertIsNone(tag_version(tag))

    def test_unmanaged_stable_and_draft_test_tags_are_protected(self):
        for changes in [{"prerelease": False}, {"draft": True}, {"body": "not managed"}]:
            with self.subTest(changes=changes):
                old = release(1, 99)
                old.update(changes)
                records = inventory([old] + [release(i, i) for i in range(2, 5)], [package(1, 99)])
                self.assertEqual(expired(records, NOW), [])

    def test_shared_or_unknown_aliases_are_protected(self):
        for tags in [[version(1), "latest"], [version(1), version(2)], []]:
            with self.subTest(tags=tags):
                old = package(1, 99)
                old["metadata"]["container"]["tags"] = tags
                records = inventory([], [old] + [package(i, i) for i in range(3, 6)])
                self.assertEqual(expired(records, NOW), [])

    def test_orphan_package_versions_are_included(self):
        records = inventory([release(i, i) for i in range(2, 5)], [package(1, 99)])
        self.assertEqual([r.version for r in expired(records, NOW)], [version(1)])

    def test_naive_timestamps_are_rejected(self):
        malformed = package(1, 9)
        malformed["created_at"] = "2026-10-01T00:00:00"
        with self.assertRaises(ValueError):
            inventory([], [malformed])
        with self.assertRaises(ValueError):
            expired([], NOW.replace(tzinfo=None))


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.releases = [release(i, 20 - i) for i in range(1, 5)]
        self.packages = [package(i, 20 - i) for i in range(1, 5)]

    def test_dry_run_has_no_mutating_requests(self):
        api = fake_api(self.releases, self.packages)
        with redirect_stdout(io.StringIO()):
            selected = cleanup(api, NOW)
        self.assertEqual([r.version for r in selected], [version(1)])
        self.assertEqual(mutations(api), [])

    def test_delete_only_test_package_then_tag_then_release(self):
        api = fake_api(self.releases, self.packages)
        with redirect_stdout(io.StringIO()):
            cleanup(api, NOW, apply=True)
        self.assertEqual(mutations(api), [
            ("DELETE", PACKAGE_API + "/versions/1001"),
            ("DELETE", REPO_API + "/git/refs/tags/" + TAG_PREFIX + version(1)),
            ("DELETE", REPO_API + "/releases/2001")])

    def test_package_permission_failure_does_not_remove_release(self):
        api = fake_api(self.releases, self.packages)
        original = api.request.side_effect

        def deny(method, path, **kwargs):
            if method == "DELETE":
                raise RuntimeError("package access denied")
            return original(method, path, **kwargs)

        api.request.side_effect = deny
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "access denied"):
            cleanup(api, NOW, apply=True)
        self.assertEqual(mutations(api), [("DELETE", PACKAGE_API + "/versions/1001")])

    def test_metadata_changes_prevent_any_deletion(self):
        for change in ["alias", "stable", "moved-tag", "republished"]:
            with self.subTest(change=change):
                api = fake_api(self.releases, self.packages)
                original = api.request.side_effect

                def changed(method, path, **kwargs):
                    value = copy.deepcopy(original(method, path, **kwargs))
                    if change == "alias" and path == PACKAGE_API + "/versions/1001":
                        value["metadata"]["container"]["tags"].append("stable")
                    if change == "stable" and path == REPO_API + "/releases/2001":
                        value["prerelease"] = False
                    if change == "moved-tag" and "/git/ref/tags/" in path:
                        value["object"]["sha"] = "b" * 40
                    if change == "republished" and path == REPO_API + "/releases/2001":
                        value["published_at"] = NOW.isoformat()
                    return value

                api.request.side_effect = changed
                with redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                    cleanup(api, NOW, apply=True)
                self.assertEqual(mutations(api), [])

    def test_partial_deletion_keeps_release_discoverable_for_retry(self):
        api = fake_api(self.releases, self.packages)
        original = api.request.side_effect

        def fail_tag(method, path, **kwargs):
            if method == "DELETE" and "/git/refs/tags/" in path:
                raise RuntimeError("tag deletion failed")
            return original(method, path, **kwargs)

        api.request.side_effect = fail_tag
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "tag deletion failed"):
            cleanup(api, NOW, apply=True)
        self.assertNotIn(("DELETE", REPO_API + "/releases/2001"), mutations(api))
        # The OCI version was removed; the retained release identifies the remainder.
        retry = fake_api(self.releases, self.packages[1:])
        with redirect_stdout(io.StringIO()):
            cleanup(retry, NOW, apply=True)
        self.assertEqual(mutations(retry), [
            ("DELETE", REPO_API + "/git/refs/tags/" + TAG_PREFIX + version(1)),
            ("DELETE", REPO_API + "/releases/2001")])

    def test_missing_package_with_existing_releases_fails_closed(self):
        api = fake_api(self.releases, None)
        with self.assertRaisesRegex(RuntimeError, "package is unavailable"):
            cleanup(api, NOW, apply=True)
        self.assertEqual(mutations(api), [])

    def test_empty_repository_is_safe(self):
        api = fake_api([], None)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cleanup(api, NOW, apply=True), [])
        self.assertEqual(mutations(api), [])


class PublicationTests(unittest.TestCase):
    def test_versions_are_unique_and_separate_from_production(self):
        self.assertEqual(make_version("0.1.0", "123", "1"), version(123))
        self.assertEqual(make_version("0.2.0-rc.1+build", "123", "2"), "0.2.0-test.123.2")
        self.assertNotEqual(make_version("0.1.0", 123, 1), make_version("0.1.0", 123, 2))
        for chart, run, attempt in [("0.1", 1, 1), ("01.1.0", 1, 1), ("0.1.0", 0, 1),
                                    ("0.1.0", "1;echo bad", 1), ("0.1.0", 1, 0)]:
            with self.subTest(chart=chart, run=run, attempt=attempt), self.assertRaises(ValueError):
                make_version(chart, run, attempt)

    @patch("prerelease.publish_chart")
    @patch("prerelease.candidate")
    @patch.dict("os.environ", {"GITHUB_RUN_ID": "123"})
    def test_publishes_only_isolated_repository_and_prerelease(self, candidate, push):
        selected = {"version": version(123), "tag": TAG_PREFIX + version(123), "sha": SOURCE}
        candidate.return_value = selected
        api = MagicMock()
        api.request.return_value = None
        with redirect_stdout(io.StringIO()):
            publish(api, selected)
        self.assertEqual(push.call_args.args[1:], (version(123), TEST_REPOSITORY))
        request = api.request.call_args.args
        self.assertEqual(request[:2], ("POST", REPO_API + "/releases"))
        self.assertTrue(request[2]["prerelease"])
        self.assertFalse(request[2]["draft"])
        self.assertEqual(request[2]["make_latest"], "false")
        self.assertEqual(request[2]["target_commitish"], SOURCE)
        self.assertIn(MARKER, request[2]["body"])
        self.assertIn(TEST_REPOSITORY, request[2]["body"])

    @patch("prerelease.publish_chart")
    @patch("prerelease.candidate")
    def test_mismatch_or_existing_release_does_not_publish(self, candidate, push):
        selected = {"version": version(123), "tag": TAG_PREFIX + version(123), "sha": SOURCE}
        candidate.return_value = selected
        api = MagicMock()
        with self.assertRaises(ValueError):
            publish(api, dict(selected, sha="b" * 40))
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            publish(api, selected)
        api.request.side_effect = [None, {"object": {"type": "commit", "sha": "b" * 40}}]
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            publish(api, selected)
        push.assert_not_called()


class ApiTests(unittest.TestCase):
    @patch("prerelease.GitHub")
    @patch("sys.argv", ["prerelease.py", "cleanup", "--apply"])
    def test_cli_rejects_non_main_or_other_repositories_before_api_access(self, api):
        for repo, ref in [("www-zaq-ai/zaq-helm-chart", "refs/heads/feature"),
                          ("other/zaq-helm-chart", "refs/heads/main")]:
            with patch.dict("os.environ", {"GITHUB_REPOSITORY": repo, "GITHUB_REF": ref}, clear=True):
                with self.subTest(repo=repo, ref=ref), self.assertRaises(ValueError):
                    main()
        api.assert_not_called()

    @patch("prerelease.cleanup")
    @patch("sys.argv", ["prerelease.py", "cleanup"])
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "www-zaq-ai/zaq-helm-chart",
                               "GITHUB_REF": "refs/heads/main", "GITHUB_TOKEN": "not-a-real-token"})
    def test_cli_cleanup_defaults_to_dry_run(self, clean):
        main()
        self.assertFalse(clean.call_args.kwargs["apply"])

    def test_inventory_paginates(self):
        api = GitHub("not-a-real-token")
        api.request = MagicMock(side_effect=[[{}] * 100, [{"id": 101}]])
        self.assertEqual(len(api.list_all(REPO_API + "/releases")), 101)
        self.assertIn("page=2", api.request.call_args.args[1])

    def test_inventory_disappearance_fails_closed(self):
        api = GitHub("not-a-real-token")
        api.request = MagicMock(side_effect=[[{}] * 100, None])
        with self.assertRaisesRegex(RuntimeError, "disappeared"):
            api.list_all(PACKAGE_API + "/versions", missing_ok=True)

    @patch("prerelease.urlopen")
    def test_http_errors_do_not_expose_tokens_or_enable_deletion(self, request):
        api = GitHub("not-a-real-token")
        for status in [401, 403, 500]:
            request.side_effect = HTTPError("https://example.org", status, "test", {}, None)
            with self.subTest(status=status), self.assertRaises(RuntimeError) as error:
                api.request("GET", PACKAGE_API + "/versions", missing_ok=True)
            self.assertNotIn("not-a-real-token", str(error.exception))
        request.side_effect = HTTPError("https://example.org", 404, "test", {}, None)
        self.assertIsNone(api.request("GET", PACKAGE_API + "/versions", missing_ok=True))
