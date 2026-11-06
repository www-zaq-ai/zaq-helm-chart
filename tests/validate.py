"""Canonical offline validation: schema, chart contract, lint, manifest schemas."""

import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "zaq"
values = yaml.safe_load((CHART / "values.yaml").read_text())
schema = json.loads((CHART / "values.schema.json").read_text())
jsonschema.Draft7Validator.check_schema(schema)
jsonschema.validate(values, schema)
subprocess.run(["helm", "lint", "--strict", str(CHART)], check=True)
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
               cwd=ROOT, check=True)
fixtures = [None, "examples/production.yaml", "examples/existing-database-pvc.yaml", "tests/fixtures/custom.yaml"]
for version in ["1.31.0", "1.32.0", "1.33.0", "1.34.0"]:
    for fixture in fixtures:
        command = ["helm", "template", "validate", str(CHART), "--namespace", "validate", "--kube-version", version]
        if fixture:
            command += ["-f", str(ROOT / fixture)]
        rendered = subprocess.run(command, capture_output=True, text=True, check=True).stdout
        subprocess.run(["kubeconform", "-strict", "-summary", "-kubernetes-version", version],
                       input=rendered, text=True, check=True)
subprocess.run(["actionlint"], cwd=ROOT, check=True)
print("Offline validation passed; this does not establish real ZAQ readiness.")
