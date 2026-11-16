import copy
import unittest

import jsonschema

from test_chart import DEFAULTS, SCHEMA, documents, env, pod, render, resource


CA_PATH = "/etc/zaq/database-ca/ca.crt"


class DatabaseTlsTests(unittest.TestCase):
    def fixed(self, database=None):
        return {"image": {"digest": "sha256:" + "a" * 64, "appVersion": "0.19.0", "databaseTlsSupported": True},
                "database": database or {"tls": {"enabled": True}}}

    def test_shared_dba_secret_projects_only_ca_to_app_init_and_hook(self):
        docs = documents(render(fixture="tests/fixtures/database-tls.yaml"))
        spec = pod(docs)
        hook = resource(docs, "Job")["spec"]["template"]["spec"]
        for container in spec["containers"] + spec["initContainers"]:
            values = env(container)
            self.assertEqual(values["ZAQ_DATABASE_SSL"]["value"], "true")
            self.assertEqual(values["ZAQ_DATABASE_SSL_CA_CERT_FILE"]["value"], CA_PATH)
        for target, container in [(spec, spec["containers"][0]), (spec, spec["initContainers"][0]),
                                  (hook, hook["containers"][0])]:
            ca = next(v for v in target["volumes"] if v["name"] == "database-ca")
            self.assertEqual(ca["secret"], {"secretName": "zaq-dba", "defaultMode": 292,
                                           "items": [{"key": "ca.crt", "path": "ca.crt"}]})
            mount = next(v for v in container["volumeMounts"] if v["name"] == "database-ca")
            self.assertEqual(mount, {"name": "database-ca", "mountPath": "/etc/zaq/database-ca", "readOnly": True})
        for container in [spec["initContainers"][0], hook["containers"][0]]:
            self.assertEqual(env(container)["PGSSLROOTCERT"]["value"], CA_PATH)
            self.assertEqual(env(container)["PGSSLMODE"]["value"], "verify-full")
        app = spec["containers"][0]
        self.assertTrue({"PGUSER", "PGPASSWORD", "PGSSLMODE", "PGSSLROOTCERT"}.isdisjoint(env(app)))
        self.assertFalse(any(e.get("valueFrom", {}).get("secretKeyRef", {}).get("name") == "zaq-dba" for e in app["env"]))
        self.assertNotIn("command", app)
        self.assertEqual(app["args"], ["server"])
        self.assertEqual(app["image"], spec["initContainers"][0]["image"])
        self.assertFalse(hook["automountServiceAccountToken"])

    def test_system_trust_no_mount_and_independent_modes(self):
        values = self.fixed({"tls": {"enabled": True}, "provisioning": {"sslMode": "disable"}})
        values["preflight"] = {"enabled": True, "sslMode": "verify-full"}
        docs = documents(render(values))
        spec = pod(docs)
        init = env(spec["initContainers"][0])
        app = env(spec["containers"][0])
        hook = resource(docs, "Job")["spec"]["template"]["spec"]
        self.assertEqual(init["PGSSLMODE"]["value"], "disable")
        self.assertNotIn("PGSSLROOTCERT", init)
        self.assertNotIn("ZAQ_DATABASE_SSL_CA_CERT_FILE", app)
        self.assertEqual(env(hook["containers"][0])["PGSSLROOTCERT"]["value"], "system")
        self.assertNotIn("volumeMounts", spec["initContainers"][0])
        self.assertNotIn("volumes", hook)

    def test_app_only_ca_selection_does_not_inject_dba_credentials(self):
        values = self.fixed({"tls": {"enabled": True, "ca": {"existingSecret": "zaq-dba", "key": "public-ca"}},
                             "provisioning": {"enabled": False, "keys": None}})
        values["preflight"] = {"enabled": True, "sslMode": "verify-ca"}
        docs = documents(render(values))
        spec = pod(docs)
        self.assertNotIn("initContainers", spec)
        self.assertEqual(next(v for v in spec["volumes"] if v["name"] == "database-ca")["secret"]["items"],
                         [{"key": "public-ca", "path": "ca.crt"}])
        for container in spec["containers"] + resource(docs, "Job")["spec"]["template"]["spec"]["containers"]:
            self.assertTrue({"PGUSER", "PGPASSWORD", "ZAQ_READER_PASSWORD"}.isdisjoint(env(container)))

    def test_ca_can_serve_libpq_without_enabling_application_tls(self):
        docs = documents(render({"database": {"tls": {"ca": {"existingSecret": "zaq-dba"}},
                                              "provisioning": {"sslMode": "verify-full"}}}))
        spec = pod(docs)
        self.assertEqual(env(spec["containers"][0])["ZAQ_DATABASE_SSL"]["value"], "false")
        self.assertNotIn("ZAQ_DATABASE_SSL_CA_CERT_FILE", env(spec["containers"][0]))
        self.assertEqual(len(spec["containers"][0]["volumeMounts"]), 1)
        self.assertEqual(env(spec["initContainers"][0])["PGSSLROOTCERT"]["value"], CA_PATH)

    def test_tls_rejects_unsupported_images(self):
        for values in [{"database": {"tls": {"enabled": True}}},
                       {"image": {"databaseTlsSupported": True}, "database": {"tls": {"enabled": True}}}]:
            result = render(values)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("TLS", result.stderr)
        documents(render(self.fixed()))
        self.assertFalse(DEFAULTS["database"]["tls"]["enabled"])

    def test_rejects_projection_of_known_credential_keys(self):
        for name, key in [("zaq-dba", "password"), ("zaq-dba", "username"),
                          ("zaq-runtime", "owner-password"), ("zaq-runtime", "reader-password"),
                          ("zaq-runtime", "secret-key-base"), ("zaq-runtime", "encryption-key")]:
            result = render(self.fixed({"tls": {"enabled": True, "ca": {"existingSecret": name, "key": key}}}))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("credential key", result.stderr)

    def test_schema_types_and_key_requirements(self):
        invalid = [{"tls": {"enabled": "true"}}, {"tls": None}, {"tls": {"ca": None}},
                   {"tls": {"ca": {"key": ""}}}, {"tls": {"ca": {"existingSecret": "bad/name"}}},
                   {"tls": {"ca": {"value": "forbidden"}}}, {"provisioning": {"sslMode": "skip-verify"}}]
        for database in invalid:
            with self.subTest(database=database):
                # Helm also validates merged values, including null-removal cases.
                self.assertNotEqual(render({"database": database}).returncode, 0)
        values = copy.deepcopy(DEFAULTS)
        values["image"]["databaseTlsSupported"] = "true"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(values, SCHEMA)
