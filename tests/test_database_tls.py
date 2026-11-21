import copy
import unittest

import jsonschema

from test_chart import DEFAULTS, SCHEMA, documents, env, pod, render, resource


CA_PATH = "/etc/zaq/database-ca/ca.crt"


class DatabaseTlsTests(unittest.TestCase):
    def fixed(self, database=None):
        return {"image": {"digest": "sha256:" + "a" * 64, "appVersion": "0.19.1"},
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

    def test_system_trust_no_mount_and_shared_libpq_modes(self):
        for mode in ["require", "verify-ca", "verify-full"]:
            with self.subTest(mode=mode):
                values = self.fixed({"tls": {"enabled": True, "libpqMode": mode}})
                values["preflight"] = {"enabled": True}
                docs = documents(render(values))
                spec = pod(docs)
                hook = resource(docs, "Job")["spec"]["template"]["spec"]
                for container in [spec["initContainers"][0], hook["containers"][0]]:
                    settings = env(container)
                    self.assertEqual(settings["PGSSLMODE"]["value"], mode)
                    if mode == "require":
                        self.assertNotIn("PGSSLROOTCERT", settings)
                    else:
                        expected = "/etc/ssl/certs/ca-certificates.crt" if mode == "verify-ca" else "system"
                        self.assertEqual(settings["PGSSLROOTCERT"]["value"], expected)
                    self.assertNotIn("volumeMounts", container)
                app = env(spec["containers"][0])
                self.assertEqual(app["ZAQ_DATABASE_SSL"]["value"], "true")
                self.assertNotIn("ZAQ_DATABASE_SSL_CA_CERT_FILE", app)
                self.assertNotIn("PGSSLMODE", app)
                self.assertNotIn("volumes", hook)

    def test_app_only_ca_selection_does_not_inject_dba_credentials(self):
        values = self.fixed({"tls": {"enabled": True, "libpqMode": "verify-ca",
                                    "ca": {"existingSecret": "zaq-dba", "key": "public-ca"}},
                             "provisioning": {"enabled": False, "keys": None}})
        values["preflight"] = {"enabled": True}
        docs = documents(render(values))
        spec = pod(docs)
        self.assertNotIn("initContainers", spec)
        self.assertEqual(next(v for v in spec["volumes"] if v["name"] == "database-ca")["secret"]["items"],
                         [{"key": "public-ca", "path": "ca.crt"}])
        for container in spec["containers"] + resource(docs, "Job")["spec"]["template"]["spec"]["containers"]:
            self.assertTrue({"PGUSER", "PGPASSWORD", "ZAQ_READER_PASSWORD"}.isdisjoint(env(container)))

    def test_weaker_libpq_modes_keep_verified_application_tls(self):
        for mode in ["require", "verify-ca"]:
            with self.subTest(mode=mode):
                values = self.fixed({"tls": {"enabled": True, "libpqMode": mode,
                                             "ca": {"existingSecret": "zaq-dba"}}})
                values["preflight"] = {"enabled": True}
                docs = documents(render(values))
                spec = pod(docs)
                app = env(spec["containers"][0])
                self.assertEqual(app["ZAQ_DATABASE_SSL"]["value"], "true")
                self.assertEqual(app["ZAQ_DATABASE_SSL_CA_CERT_FILE"]["value"], CA_PATH)
                self.assertNotIn("PGSSLMODE", app)
                hook = resource(docs, "Job")["spec"]["template"]["spec"]
                for container in [spec["initContainers"][0], hook["containers"][0]]:
                    self.assertEqual(env(container)["PGSSLMODE"]["value"], mode)
                    self.assertEqual(env(container)["PGSSLROOTCERT"]["value"], CA_PATH)

    def test_tls_disabled_ignores_mode_and_ca_for_every_client(self):
        for mode in ["require", "verify-ca", "verify-full"]:
            with self.subTest(mode=mode):
                docs = documents(render({"database": {"tls": {"libpqMode": mode, "ca": {"existingSecret": "missing-ca"}}},
                                         "preflight": {"enabled": True}}))
                spec = pod(docs)
                hook = resource(docs, "Job")["spec"]["template"]["spec"]
                for container in [spec["initContainers"][0], hook["containers"][0]]:
                    settings = env(container)
                    self.assertEqual(settings["PGSSLMODE"]["value"], "disable")
                    self.assertNotIn("PGSSLROOTCERT", settings)
                    self.assertNotIn("volumeMounts", container)
                for container in spec["containers"] + spec["initContainers"]:
                    self.assertEqual(env(container)["ZAQ_DATABASE_SSL"]["value"], "false")
                    self.assertNotIn("ZAQ_DATABASE_SSL_CA_CERT_FILE", env(container))
                self.assertEqual(len(spec["containers"][0]["volumeMounts"]), 1)
                self.assertEqual([v["name"] for v in spec["volumes"]], ["data"])
                self.assertNotIn("volumes", hook)

    def test_tls_rejects_unsupported_images(self):
        for version in ["v0.18.0", "v0.19.0", "v0.19.1-rc.1"]:
            with self.subTest(version=version):
                result = render({"image": {"tag": version}, "database": {"tls": {"enabled": True}}})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("minimum", result.stderr)
        documents(render(self.fixed()))
        self.assertFalse(DEFAULTS["database"]["tls"]["enabled"])

    def test_default_and_minimum_images_render_tls_with_single_switch(self):
        for tag, image in [("v0.19.2", {}), ("v0.19.1", {"tag": "v0.19.1"})]:
            with self.subTest(tag=tag):
                values = {"image": image, "database": {"tls": {"enabled": True}}}
                docs = documents(render(values, fixture="tests/fixtures/rancher-global.yaml"))
                spec = pod(docs)
                app = spec["containers"][0]
                self.assertEqual(app["image"], f"ghcr.io/www-zaq-ai/zaq:{tag}")
                self.assertEqual(env(app)["ZAQ_DATABASE_SSL"]["value"], "true")
                self.assertNotIn("ZAQ_DATABASE_SSL_CA_CERT_FILE", env(app))
                self.assertEqual(env(spec["initContainers"][0])["PGSSLMODE"]["value"], "verify-full")

    def test_old_per_client_mode_keys_are_rejected(self):
        for values in [{"database": {"provisioning": {"sslMode": "require"}}},
                       {"preflight": {"sslMode": "verify-full"}}]:
            with self.subTest(values=values):
                result = render(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sslMode", result.stderr)

    def test_removed_support_confirmation_is_rejected(self):
        self.assertNotIn("databaseTlsSupported", DEFAULTS["image"])
        self.assertNotIn("databaseTlsSupported", SCHEMA["properties"]["image"]["properties"])
        for value in [True, False]:
            with self.subTest(value=value):
                values = copy.deepcopy(DEFAULTS)
                values["image"]["databaseTlsSupported"] = value
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(values, SCHEMA)
                result = render({"image": {"databaseTlsSupported": value}})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("databaseTlsSupported", result.stderr)

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
                   {"tls": {"ca": {"value": "forbidden"}}}]
        invalid += [{"tls": {"libpqMode": value}} for value in ["disable", "allow", "prefer", "invalid", "", None, True, 1]]
        for database in invalid:
            with self.subTest(database=database):
                # Helm also validates merged values, including null-removal cases.
                self.assertNotEqual(render({"database": database}).returncode, 0)
