"""OCI publication guard. No mutation except with explicit 'publish' command."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import base64

import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "ghcr.io"
REPOSITORY = "www-zaq-ai/charts/zaq"


def release_version(tag, chart_version):
    if not re.fullmatch(r"chart-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?", tag):
        raise ValueError("Expected chart-vX.Y.Z release tag")
    version = tag.removeprefix("chart-v")
    if version != chart_version:
        raise ValueError("Release tag does not match Chart.yaml version")
    return version


def assert_version_absent(version, bearer):
    request = Request("https://" + REGISTRY + "/v2/" + REPOSITORY + "/manifests/" + version,
                      headers={"Authorization": "Bearer " + bearer,
                               "Accept": "application/vnd.oci.image.manifest.v1+json"})
    try:
        with urlopen(request, timeout=30):
            raise RuntimeError("Chart version already exists; refusing to overwrite " + version)
    except HTTPError as error:
        if error.code != 404:
            raise RuntimeError("Registry lookup failed; publication refused") from None
        body = json.load(error)
        codes = {item.get("code") for item in body.get("errors", [])}
        if not codes or not codes.issubset({"MANIFEST_UNKNOWN", "NAME_UNKNOWN"}):
            raise RuntimeError("Registry did not confirm an absent version; publication refused")


def main():
    chart = yaml.safe_load((ROOT / "charts/zaq/Chart.yaml").read_text())
    version = release_version(os.environ["RELEASE_TAG"], chart["version"])
    if sys.argv[1] == "check-tag":
        print("Chart release tag matches version " + version)
        return
    if sys.argv[1] != "publish":
        raise ValueError("Expected check-tag or publish")
    username, token = os.environ["GHCR_USERNAME"], os.environ["GHCR_TOKEN"]
    basic = base64.b64encode((username + ":" + token).encode()).decode()
    query = urlencode({"service": REGISTRY, "scope": "repository:" + REPOSITORY + ":pull,push"})
    with urlopen(Request("https://" + REGISTRY + "/token?" + query,
                         headers={"Authorization": "Basic " + basic}), timeout=30) as response:
        bearer = json.load(response)["token"]
    assert_version_absent(version, bearer)
    with tempfile.TemporaryDirectory(prefix="zaq-publish-") as directory:
        env = dict(os.environ, HELM_REGISTRY_CONFIG=str(Path(directory) / "registry.json"))
        subprocess.run(["helm", "registry", "login", REGISTRY, "--username", username, "--password-stdin"],
                       input=token, text=True, check=True, env=env)
        subprocess.run(["helm", "package", str(ROOT / "charts/zaq"), "--destination", directory], check=True, env=env)
        subprocess.run(["helm", "push", str(Path(directory) / ("zaq-" + version + ".tgz")),
                        "oci://" + REGISTRY + "/www-zaq-ai/charts"], check=True, env=env)
        subprocess.run(["helm", "show", "chart", "oci://" + REGISTRY + "/" + REPOSITORY,
                        "--version", version], check=True, env=env)


if __name__ == "__main__":
    main()
