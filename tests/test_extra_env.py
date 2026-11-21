import copy
import unittest

import jsonschema
import yaml

from test_chart import CHART, DEFAULTS, SCHEMA, documents, env, pod, render, resource


class ExtraEnvironmentTests(unittest.TestCase):
    def test_application_only_secret_references_and_literal_strings(self):
        first = render(fixture="tests/fixtures/extra-env.yaml")
        self.assertEqual(first.stdout, render(fixture="tests/fixtures/extra-env.yaml").stdout)
        docs = documents(first)
        spec = pod(docs)
        values = env(spec["containers"][0])
        self.assertEqual(values["REQ_LLM_POOL_SIZE"]["value"], "8")
        self.assertEqual(values["CUSTOM_FEATURE"]["value"], "false")
        self.assertEqual(values["CUSTOM_TEXT"]["value"], "literal {{ .Release.Name }} and $(NOT_EXPANDED)")
        self.assertEqual(values["MY_API_TOKEN"]["valueFrom"], {"secretKeyRef": {"name": "integration-secrets", "key": "api-token"}})
        custom = {"REQ_LLM_POOL_SIZE", "CUSTOM_FEATURE", "CUSTOM_TEXT", "MY_API_TOKEN"}
        for container in spec["initContainers"] + resource(docs, "Job")["spec"]["template"]["spec"]["containers"]:
            self.assertTrue(custom.isdisjoint(env(container)))
        self.assertNotIn("envFrom", spec["containers"][0])
        self.assertEqual(len(values), len(spec["containers"][0]["env"]))
        self.assertNotIn("Secret", {d["kind"] for d in docs})

    def test_form_map_and_defaults(self):
        questions = yaml.safe_load((CHART / "questions.yaml").read_text())["questions"]
        question = next(q for q in questions if q["variable"] == "app.extraEnv")
        self.assertEqual(question["type"], "map[string]")
        self.assertEqual(question["default"], {})
        docs = documents(render({"app": {"extraEnv": {"CUSTOM_EMPTY": "", "CUSTOM_MULTILINE": "one\ntwo"}},
                                 "database": {"provisioning": {"enabled": False}}}))
        values = env(pod(docs)["containers"][0])
        self.assertEqual(values["CUSTOM_EMPTY"]["value"], "")
        self.assertEqual(values["CUSTOM_MULTILINE"]["value"], "one\ntwo")
        self.assertNotEqual(pod(documents(render())), pod(docs))

    def test_invalid_types_and_references(self):
        invalid = [{"extraEnv": []}, {"extraEnv": {"FLAG": True}}, {"extraEnv": {"COUNT": 5}},
                   {"extraEnv": {"BAD-NAME": "value"}}, {"extraEnv": {"": "value"}},
                   {"extraEnv": {"9NAME": "value"}}, {"extraEnv": None},
                   {"extraEnvSecrets": None}, {"extraEnvSecrets": {}},
                   {"extraEnvSecrets": [{"name": "MY_TOKEN", "value": "forbidden"}]},
                   {"extraEnvSecrets": [{"name": "MY_TOKEN", "secretKeyRef": {"name": "", "key": "token"}}]},
                   {"extraEnvSecrets": [{"name": "MY_TOKEN", "secretKeyRef": {"name": "external", "key": ""}}]},
                   {"extraEnvSecrets": [{"name": "BAD.NAME", "secretKeyRef": {"name": "external", "key": "token"}}]},
                   {"extraEnvSecrets": [{"name": "MY_TOKEN", "secretKeyRef": {"name": "external", "key": "token", "optional": True}}]}]
        for app in invalid:
            with self.subTest(app=app):
                values = copy.deepcopy(DEFAULTS)
                values["app"].update(app)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(values, SCHEMA)
                self.assertNotEqual(render({"app": app}).returncode, 0)

    def test_reserved_names_in_both_sources(self):
        managed = set(env(pod(documents(render()))["containers"][0]))
        names = managed | {"DATABASE_URL", "PGUSER", "PGPASSWORD", "PGSERVICE", "ZAQ_READER_PASSWORD",
                           "STORAGE_VOLUMES", "INGESTION_VOLUMES_BASE", "RELEASE_BOOT_SCRIPT", "ERL_FLAGS",
                           "ELIXIR_ERL_OPTIONS", "LD_PRELOAD", "PATH", "HOME", "MIX_ENV", "PYTHONPATH", "ENV"}
        for name in names:
            for app in [{"extraEnv": {name: "not-allowed"}},
                        {"extraEnvSecrets": [{"name": name, "secretKeyRef": {"name": "external", "key": "token"}}]}]:
                with self.subTest(name=name, app=app):
                    result = render({"app": app})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("reserved", result.stderr)

    def test_duplicate_names_and_credential_isolation(self):
        ref = {"name": "MY_TOKEN", "secretKeyRef": {"name": "external", "key": "token"}}
        for app in [{"extraEnv": {"MY_TOKEN": "non-sensitive"}, "extraEnvSecrets": [ref]},
                    {"extraEnvSecrets": [ref, dict(ref, secretKeyRef={"name": "another", "key": "token"})]}]:
            result = render({"app": app})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate", result.stderr)
        for name, key in [("zaq-dba", "username"), ("zaq-dba", "password"), ("zaq-runtime", "reader-password")]:
            for enabled in [True, False]:
                result = render({"app": {"extraEnvSecrets": [{"name": "ALIAS", "secretKeyRef": {"name": name, "key": key}}]},
                                 "database": {"provisioning": {"enabled": enabled}}})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot reference", result.stderr)
        for name, key in [("custom-dba", "dba-password"), ("custom-runtime", "reader")]:
            result = render({"app": {"extraEnvSecrets": [{"name": "ALIAS", "secretKeyRef": {"name": name, "key": key}}]}},
                            fixture="tests/fixtures/custom.yaml")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot reference", result.stderr)

    def test_secret_names_and_keys_remain_strings(self):
        docs = documents(render({"app": {"extraEnvSecrets": [{"name": "CUSTOM_TOKEN", "secretKeyRef": {"name": "123", "key": "456"}}]}}))
        self.assertEqual(env(pod(docs)["containers"][0])["CUSTOM_TOKEN"]["valueFrom"],
                         {"secretKeyRef": {"name": "123", "key": "456"}})

    def test_default_image_is_new_release_without_changing_minimum(self):
        chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
        self.assertEqual(DEFAULTS["image"]["tag"], "v0.19.2")
        self.assertEqual(chart["appVersion"], "0.19.2")
        self.assertEqual(chart["annotations"]["zaq.ai/min-app-version"], "0.19.1")
        docs = documents(render())
        app = pod(docs)["containers"][0]
        self.assertEqual(app["image"], "ghcr.io/www-zaq-ai/zaq:v0.19.2")
        self.assertEqual(app["image"], pod(docs)["initContainers"][0]["image"])
        questions = yaml.safe_load((CHART / "questions.yaml").read_text())["questions"]
        owner = next(q for q in questions if q["variable"] == "database.owner")
        self.assertIn("cluster-wide CREATEROLE", owner["description"])
        readme = (CHART / "README.md").read_text()
        self.assertIn("cluster-wide `CREATEROLE`", readme)
        self.assertIn("upstream DBA maintenance", readme)
