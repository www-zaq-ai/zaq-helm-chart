"""Release PR/publish wiring; offline and never invokes a write API."""

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def workflow():
    # BaseLoader keeps GitHub's YAML 1.2 'on' key, unlike YAML 1.1 booleans.
    return yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_main_push_not_tag_or_pull_request(self):
        config = workflow()
        self.assertEqual(config["on"], {"push": {"branches": ["main"]}})
        self.assertEqual(config["concurrency"], {"group": "chart-release-main", "cancel-in-progress": "false"})

    def test_native_helm_configuration_and_initial_release(self):
        config = json.loads((ROOT / "release-please-config.json").read_text())
        self.assertEqual(list(config["packages"]), ["charts/zaq"])
        chart = config["packages"]["charts/zaq"]
        self.assertEqual(chart["release-type"], "helm")
        self.assertEqual(chart["component"], "chart")
        self.assertTrue(chart["include-component-in-tag"])
        self.assertTrue(chart["include-v-in-tag"])
        self.assertEqual(chart["changelog-path"], "CHANGELOG.md")
        self.assertEqual(chart["initial-version"], "0.1.0")
        self.assertNotIn("release-as", chart)  # Never pin every release to the initial version.
        self.assertNotIn("bump-minor-pre-major", chart)
        self.assertNotIn("bump-patch-for-minor-pre-major", chart)
        self.assertRegex(config["bootstrap-sha"], r"^[a-f0-9]{40}$")
        manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
        # Empty means not yet released; subsequent Release Please PRs record the chart version.
        self.assertTrue(set(manifest).issubset({"charts/zaq"}))
        if manifest:
            self.assertTrue((ROOT / "charts/zaq/CHANGELOG.md").exists())
        for version in manifest.values():
            self.assertRegex(version, r"^\d+\.\d+\.\d+")

    def test_release_please_outputs_are_path_specific_and_pinned(self):
        job = workflow()["jobs"]["release"]
        step = job["steps"][0]
        self.assertEqual(step["id"], "release")
        self.assertRegex(step["uses"], r"^googleapis/release-please-action@[a-f0-9]{40}$")
        self.assertEqual(step["with"]["config-file"], "release-please-config.json")
        self.assertEqual(step["with"]["manifest-file"], ".release-please-manifest.json")
        self.assertEqual(step["with"]["target-branch"], "main")
        self.assertEqual(step["with"]["token"], "${{ secrets.RELEASE_PLEASE_TOKEN || secrets.GITHUB_TOKEN }}")
        for output, field in [("release_created", "release_created"), ("tag_name", "tag_name"), ("sha", "sha")]:
            self.assertEqual(job["outputs"][output], "${{ steps.release.outputs['charts/zaq--" + field + "'] }}")

    def test_only_new_release_runs_gates_and_publishes(self):
        jobs = workflow()["jobs"]
        for name in ["validate", "install", "publish"]:
            with self.subTest(job=name):
                self.assertEqual(jobs[name]["if"], "${{ needs.release.outputs.release_created == 'true' }}")
                needs = jobs[name]["needs"]
                self.assertIn("release", [needs] if isinstance(needs, str) else needs)
        self.assertEqual(set(jobs["publish"]["needs"]), {"release", "validate", "install"})
        self.assertNotIn("always()", jobs["publish"]["if"])

    def test_gates_and_publication_use_the_exact_released_commit(self):
        jobs = workflow()["jobs"]
        for name in ["validate", "install", "publish"]:
            checkout = next(step for step in jobs[name]["steps"] if step.get("uses", "").startswith("actions/checkout@"))
            self.assertEqual(checkout["with"]["ref"], "${{ needs.release.outputs.sha }}")
            self.assertEqual(checkout["with"]["persist-credentials"], "false")
        for name in ["validate", "publish"]:
            steps = [step for step in jobs[name]["steps"] if "RELEASE_TAG" in step.get("env", {})]
            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0]["env"]["RELEASE_TAG"], "${{ needs.release.outputs.tag_name }}")
        self.assertTrue(any("tests/validate.py" in step.get("run", "") for step in jobs["validate"]["steps"]))
        self.assertTrue(any("tests/release.py check-tag" in step.get("run", "") for step in jobs["validate"]["steps"]))
        self.assertTrue(any("tests/integration.py" in step.get("run", "") for step in jobs["install"]["steps"]))

    def test_permissions_and_publication_token_are_scoped(self):
        config = workflow()
        self.assertEqual(config["permissions"], {"contents": "read"})
        jobs = config["jobs"]
        self.assertEqual(jobs["release"]["permissions"],
                         {"contents": "write", "issues": "write", "pull-requests": "write"})
        self.assertEqual(jobs["publish"]["permissions"], {"contents": "read", "packages": "write"})
        for name in ["validate", "install"]:
            self.assertNotIn("permissions", jobs[name])
        publish = jobs["publish"]["steps"][-1]
        self.assertIn("tests/release.py publish", publish["run"])
        self.assertEqual(publish["env"]["GHCR_TOKEN"], "${{ secrets.GITHUB_TOKEN }}")
