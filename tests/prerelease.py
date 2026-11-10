"""Isolated test publication and bounded cleanup. No writes without explicit commands."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
import re
import subprocess
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

from release import ROOT, TEST_REPOSITORY, publish_chart


REPO = "www-zaq-ai/zaq-helm-chart"
REPO_API = "/repos/" + REPO
PACKAGE_API = "/orgs/www-zaq-ai/packages/container/" + quote("charts/test/zaq", safe="")
MARKER = "<!-- zaq-chart-test-release -->"
CORE = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
VERSION = re.compile(r"^" + CORE + r"-test\.([1-9][0-9]*)\.([1-9][0-9]*)$")
TAG_PREFIX = "chart-test-v"
SHA = re.compile(r"^[a-f0-9]{40}$")


def test_version(chart_version, run_id, attempt):
    match = re.fullmatch(r"(" + CORE + r")(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", chart_version)
    if not match or not re.fullmatch(r"[1-9][0-9]*", str(run_id)) or not re.fullmatch(r"[1-9][0-9]*", str(attempt)):
        raise ValueError("Invalid chart version or workflow run identity")
    return f"{match.group(1)}-test.{run_id}.{attempt}"


def tag_version(tag):
    if not isinstance(tag, str) or not tag.startswith(TAG_PREFIX):
        return None
    version = tag[len(TAG_PREFIX):]
    return version if VERSION.fullmatch(version) else None


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Artifact timestamps must include timezone")
    return parsed


def source_sha(body):
    match = re.search(r"^Source commit: `([a-f0-9]{40})`$", body, re.MULTILINE)
    return match.group(1) if match else None


def managed_release(release):
    body = release.get("body") or ""
    return (tag_version(release.get("tag_name")) is not None
            and release.get("prerelease") is True and release.get("draft") is False
            and MARKER in body and source_sha(body) is not None)


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, data=None, missing_ok=False):
        request = Request("https://api.github.com" + path, method=method,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={"Authorization": "Bearer " + self.token,
                                   "Accept": "application/vnd.github+json",
                                   "Content-Type": "application/json",
                                   "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f"GitHub {method} {path} failed ({error.code}); check token/package permissions") from None

    def list_all(self, path, missing_ok=False):
        items = []
        page = 1
        while True:
            batch = self.request("GET", f"{path}?per_page=100&page={page}", missing_ok=missing_ok)
            if batch is None:
                if page != 1:
                    raise RuntimeError("Artifact inventory disappeared during pagination")
                return None
            if not isinstance(batch, list):
                raise RuntimeError("Unexpected artifact inventory response")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1


@dataclass
class Artifact:
    version: str
    created: datetime
    releases: list = field(default_factory=list)
    packages: list = field(default_factory=list)
    protected: bool = False


def inventory(releases, packages):
    records = {}

    def record(version, created):
        if version not in records:
            records[version] = Artifact(version, created)
        records[version].created = max(records[version].created, created)
        return records[version]

    for release in releases:
        version = tag_version(release.get("tag_name"))
        if version:
            created = max(timestamp(release["created_at"]),
                          timestamp(release.get("published_at") or release["created_at"]))
            item = record(version, created)
            item.releases.append(release)
            item.protected |= not managed_release(release)
    for package in packages:
        tags = package["metadata"]["container"]["tags"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("Unexpected container version tags")
        for version in set(tags):
            if VERSION.fullmatch(version):
                item = record(version, timestamp(package["created_at"]))
                item.packages.append(package)
                # Shared digests/unknown aliases must never be deleted indirectly.
                item.protected |= tags != [version]
    return list(records.values())


def expired(records, now):
    if now.tzinfo is None:
        raise ValueError("Cleanup clock must include timezone")
    ordered = sorted(records, key=lambda item: (item.created, tuple(map(int, VERSION.fullmatch(item.version).groups()))),
                     reverse=True)
    cutoff = now - timedelta(days=7)
    return [item for item in ordered[3:] if not item.protected and item.created < cutoff]


def artifact_id(value):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("Invalid GitHub artifact ID")
    return str(value)


def recheck(api, item):
    """Re-read mutable metadata before deleting anything; fail closed on changes."""
    for package in item.packages:
        current = api.request("GET", PACKAGE_API + "/versions/" + artifact_id(package["id"]), missing_ok=True)
        if current is not None and (current["metadata"]["container"]["tags"] != [item.version]
                                    or current["created_at"] != package["created_at"]):
            raise RuntimeError("Package changed since inventory; refusing deletion")
    for release in item.releases:
        current = api.request("GET", REPO_API + "/releases/" + artifact_id(release["id"]), missing_ok=True)
        if current is None:
            raise RuntimeError("Release disappeared since inventory; retry cleanup")
        if (not managed_release(current) or current["tag_name"] != release["tag_name"]
                or source_sha(current["body"]) != source_sha(release["body"])
                or current["created_at"] != release["created_at"]
                or current.get("published_at") != release.get("published_at")):
            raise RuntimeError("Release changed since inventory; refusing deletion")
        ref = api.request("GET", REPO_API + "/git/ref/tags/" + quote(current["tag_name"], safe=""), missing_ok=True)
        if ref is not None and (ref["object"]["type"] != "commit"
                                or ref["object"]["sha"] != source_sha(current["body"])):
            raise RuntimeError("Test tag moved or became annotated; refusing deletion")


def cleanup(api, now, apply=False):
    releases = api.list_all(REPO_API + "/releases")
    packages = api.list_all(PACKAGE_API + "/versions", missing_ok=True)
    if packages is None:
        if any(tag_version(release.get("tag_name")) for release in releases):
            raise RuntimeError("Test releases exist but the test package is unavailable; check package access")
        packages = []
    candidates = expired(inventory(releases, packages), now)
    for item in candidates:
        print(("Deleting " if apply else "Would delete ") + item.version)
        if not apply:
            continue
        recheck(api, item)
        for package in item.packages:
            api.request("DELETE", PACKAGE_API + "/versions/" + artifact_id(package["id"]), missing_ok=True)
        # The release record is deleted last, so failures remain discoverable on retry.
        for release in item.releases:
            api.request("DELETE", REPO_API + "/git/refs/tags/" + quote(release["tag_name"], safe=""), missing_ok=True)
            api.request("DELETE", REPO_API + "/releases/" + artifact_id(release["id"]), missing_ok=True)
    print(f"{'Deleted' if apply else 'Selected'} {len(candidates)} test versions; newest three and recent versions retained")
    return candidates


def candidate():
    chart = yaml.safe_load((ROOT / "charts/zaq/Chart.yaml").read_text())
    version = test_version(chart["version"], os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"])
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not SHA.fullmatch(sha):
        raise ValueError("Invalid source SHA")
    return {"version": version, "tag": TAG_PREFIX + version, "sha": sha}


def publish(api, selected):
    expected = candidate()
    if selected != expected:
        raise ValueError("Test release does not match checked-out source/run")
    if (api.request("GET", REPO_API + "/releases/tags/" + quote(selected["tag"], safe=""), missing_ok=True) is not None
            or api.request("GET", REPO_API + "/git/ref/tags/" + quote(selected["tag"], safe=""), missing_ok=True) is not None):
        raise RuntimeError("Test tag or release already exists; rerun the workflow with a new attempt")
    publish_chart(ROOT / "charts/zaq", selected["version"], TEST_REPOSITORY)
    body = (f"{MARKER}\n\nSource commit: `{selected['sha']}`\n\n"
            f"Workflow run: https://github.com/{REPO}/actions/runs/{os.environ['GITHUB_RUN_ID']}\n\n"
            "Temporary chart for testing; not a production release.\n\n"
            "```sh\nhelm upgrade --install zaq-test oci://ghcr.io/" + TEST_REPOSITORY + " \\\n"
            f"  --version {selected['version']} --namespace zaq-test --values your-values.yaml \\\n"
            "  --wait --timeout 20m\n```\n\n"
            "Create the namespace and required Secrets first. Cleanup retains the newest three test versions; "
            "other versions expire after seven days.\n")
    api.request("POST", REPO_API + "/releases", {"tag_name": selected["tag"],
                "target_commitish": selected["sha"], "name": "Test chart " + selected["version"],
                "body": body, "draft": False, "prerelease": True, "make_latest": "false"})
    print("Published test chart " + selected["version"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "publish", "cleanup"])
    parser.add_argument("--apply", action="store_true", help="Actually delete expired test artifacts (cleanup only)")
    args = parser.parse_args()
    if os.environ.get("GITHUB_REPOSITORY") != REPO or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Test artifact workflows must run from this repository's main branch")
    if args.command == "prepare":
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for key, value in candidate().items():
                output.write(f"{key}={value}\n")
    elif args.command == "publish":
        publish(GitHub(os.environ["GITHUB_TOKEN"]), {"version": os.environ["TEST_VERSION"],
                "tag": os.environ["TEST_TAG"], "sha": os.environ["SOURCE_SHA"]})
    else:
        cleanup(GitHub(os.environ["GITHUB_TOKEN"]), datetime.now(timezone.utc), apply=args.apply)


if __name__ == "__main__":
    main()
