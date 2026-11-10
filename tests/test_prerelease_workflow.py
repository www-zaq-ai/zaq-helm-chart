from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


class PrereleaseWorkflowTests(unittest.TestCase):
    def test_manual_only_and_resolves_main(self):
        config = workflow("test-release.yml")
        self.assertEqual(set(config["on"]), {"workflow_dispatch"})
        job = config["jobs"]["prepare"]
        self.assertEqual(job["if"], "${{ github.ref == 'refs/heads/main' }}")
        self.assertEqual(job["steps"][0]["with"], {"ref": "main", "persist-credentials": "false"})
        for key in ["sha", "version", "tag"]:
            self.assertEqual(job["outputs"][key], "${{ steps.candidate.outputs." + key + " }}")

    def test_validation_and_publication_use_resolved_sha_and_gates(self):
        jobs = workflow("test-release.yml")["jobs"]
        self.assertEqual(set(jobs["publish"]["needs"]), {"prepare", "validate", "install"})
        for name in ["validate", "install", "publish"]:
            with self.subTest(job=name):
                checkout = jobs[name]["steps"][0]
                self.assertEqual(checkout["with"], {"ref": "${{ needs.prepare.outputs.sha }}", "persist-credentials": "false"})
                self.assertNotIn("always()", jobs[name].get("if", ""))
        install = jobs["install"]["steps"][-1]
        self.assertEqual(jobs["validate"]["steps"][-1]["shell"], "bash")
        self.assertIn('--version "$TEST_VERSION"', install["run"])
        self.assertIn("export ZAQ_CHART_PATH=", install["run"])
        self.assertIn("tests/integration.py", install["run"])
        publish = jobs["publish"]["steps"][-1]
        self.assertIn("tests/prerelease.py publish", publish["run"])
        self.assertEqual(publish["env"]["SOURCE_SHA"], "${{ needs.prepare.outputs.sha }}")

    def test_automatic_cleanup_and_manual_preview(self):
        config = workflow("cleanup-test-releases.yml")
        self.assertEqual(set(config["on"]), {"schedule", "workflow_dispatch", "workflow_call"})
        self.assertEqual(config["on"]["schedule"], [{"cron": "23 3 * * *"}])
        self.assertEqual(config["on"]["workflow_dispatch"]["inputs"]["dry_run"]["default"], "true")
        self.assertEqual(config["on"]["workflow_call"]["inputs"]["dry_run"]["default"], "false")
        jobs = workflow("test-release.yml")["jobs"]
        self.assertEqual(jobs["cleanup"]["needs"], "publish")
        self.assertEqual(jobs["cleanup"]["uses"], "./.github/workflows/cleanup-test-releases.yml")
        self.assertEqual(jobs["cleanup"]["with"]["dry_run"], "false")
        step = config["jobs"]["cleanup"]["steps"][-1]
        self.assertEqual(step["env"]["CLEANUP_APPLY"], "${{ !inputs.dry_run }}")
        self.assertIn('if [[ "$CLEANUP_APPLY" == true ]]', step["run"])
        self.assertIn("--apply", step["run"])

    def test_publish_cleanup_are_serialized_and_permissions_scoped(self):
        release = workflow("test-release.yml")
        cleanup = workflow("cleanup-test-releases.yml")
        self.assertEqual(release["permissions"], {"contents": "read"})
        self.assertEqual(cleanup["permissions"], {"contents": "read"})
        for job in [release["jobs"]["publish"], cleanup["jobs"]["cleanup"]]:
            self.assertEqual(job["permissions"], {"contents": "write", "packages": "write"})
            self.assertEqual(job["concurrency"], {"group": "chart-test-artifacts", "cancel-in-progress": "false"})
        for name in ["prepare", "validate", "install"]:
            self.assertNotIn("permissions", release["jobs"][name])
        for config in [release, cleanup]:
            for job in config["jobs"].values():
                for step in job.get("steps", []):
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")
