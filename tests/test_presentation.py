import copy
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

import jsonschema
import yaml

from test_chart import CHART, DEFAULTS, HELM, SCHEMA, documents, render


def lookup(data, name):
    for part in name.split("."):
        data = data[part]
    return data


def question_schema(name):
    node = SCHEMA
    for part in name.split("."):
        if "$ref" in node:
            node = SCHEMA["definitions"][node["$ref"].split("/")[-1]]
        node = node["properties"][part]
    if "$ref" in node:
        node = SCHEMA["definitions"][node["$ref"].split("/")[-1]]
    return node


def visible(question, values):
    for condition in question.get("show_if", "").split("&&"):
        if not condition:
            continue
        path, wanted = condition.split("=", 1)
        actual = lookup(values, path)
        if wanted == "":
            if actual not in (None, ""):
                return False
        elif wanted in {"true", "false"}:
            if actual is not (wanted == "true"):
                return False
        elif actual != wanted:
            return False
    return True


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.questions = yaml.safe_load((CHART / "questions.yaml").read_text())["questions"]

    def test_question_paths_types_defaults_and_enum_options(self):
        names = [q["variable"] for q in self.questions]
        self.assertEqual(len(names), len(set(names)))
        for q in self.questions:
            with self.subTest(variable=q["variable"]):
                expected = lookup(DEFAULTS, q["variable"])
                self.assertEqual(q["default"], expected)
                self.assertIs(type(q["default"]), type(expected))
                field = question_schema(q["variable"])
                jsonschema.validate(q["default"], dict(field, definitions=SCHEMA["definitions"]))
                types = {"boolean": bool, "int": int, "string": str, "enum": str,
                         "secret": str, "hostname": str, "pvc": str, "array[string]": list}
                if q["type"] == "storageclass":
                    self.assertIsNone(expected)
                else:
                    self.assertIsInstance(expected, types[q["type"]])
                if q["type"] == "enum":
                    self.assertEqual(q["options"], field["enum"])
                for key in ["min", "max"]:
                    if key in q:
                        self.assertEqual(q[key], field["minimum" if key == "min" else "maximum"])

    def test_only_secret_names_and_key_mappings_not_credentials(self):
        selectors = {q["variable"] for q in self.questions if q["type"] == "secret"}
        self.assertEqual(selectors, {"secrets.existingSecret", "database.provisioning.existingSecret"})
        self.assertFalse(any(q["type"] == "password" for q in self.questions))
        self.assertFalse(any(q["type"] == "yaml" for q in self.questions))  # Rancher 2.10 emits text, not typed arrays.
        for q in self.questions:
            if "password" in q["variable"].lower() or q["variable"].endswith(("secretKeyBase", "encryptionKey")):
                self.assertIn(".keys.", q["variable"])
                self.assertEqual(q["type"], "string")

    def test_conditional_fields_match_configuration(self):
        app_only = copy.deepcopy(DEFAULTS)
        app_only["database"]["provisioning"]["enabled"] = False
        enabled = copy.deepcopy(DEFAULTS)
        enabled["preflight"]["enabled"] = True
        enabled["ingress"]["enabled"] = True
        for q in self.questions:
            visible(q, DEFAULTS)  # Every conditional path must resolve in actual values.
            if q["variable"].startswith("database.provisioning.") and q["variable"] != "database.provisioning.enabled":
                self.assertTrue(visible(q, DEFAULTS))
                self.assertFalse(visible(q, app_only))
            if q["variable"] == "secrets.keys.readerPassword":
                self.assertFalse(visible(q, app_only))
            if ((q["variable"].startswith("preflight.") and q["variable"] != "preflight.enabled")
                    or (q["variable"].startswith("ingress.") and q["variable"] != "ingress.enabled")):
                self.assertFalse(visible(q, DEFAULTS))
                self.assertTrue(visible(q, enabled))
        reuse = copy.deepcopy(DEFAULTS)
        reuse["persistence"]["existingClaim"] = "data"
        for q in self.questions:
            if q["variable"] in {"persistence.storageClass", "persistence.size", "persistence.retain"}:
                self.assertFalse(visible(q, reuse))
        # Form defaults and representative typed answers must still render offline.
        documents(render())
        documents(render({"persistence": {"existingClaim": "data"},
                          "database": {"provisioning": {"enabled": False}},
                          "preflight": {"enabled": True}}))

    def test_chart_archive_includes_documentation_and_form(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([HELM, "package", str(CHART), "--destination", directory],
                           capture_output=True, text=True, check=True)
            archive = next(Path(directory).glob("*.tgz"))
            with tarfile.open(archive) as package:
                files = set(package.getnames())
                self.assertIn("zaq/README.md", files)
                self.assertIn("zaq/questions.yaml", files)
                readme = package.extractfile("zaq/README.md").read().decode()
                self.assertIn("secretKeyRef", (CHART / "templates/_helpers.tpl").read_text())
                self.assertIn("does not enable TLS", readme)
                self.assertIn("https://github.com/www-zaq-ai/zaq-helm-chart/blob/main/docs/", readme)
                self.assertEqual(yaml.safe_load(package.extractfile("zaq/questions.yaml"))["questions"], self.questions)

    def test_icon_is_pinned_official_asset_and_application_version_unchanged(self):
        chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
        self.assertRegex(chart["icon"], r"^https://raw\.githubusercontent\.com/www-zaq-ai/zaq/[a-f0-9]{40}/priv/static/images/zaq\.png$")
        self.assertEqual(chart["appVersion"], "0.18.0")
        self.assertIn("agents", chart["keywords"])
