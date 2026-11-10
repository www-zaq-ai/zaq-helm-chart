from contextlib import redirect_stdout
import io
import os
import subprocess
import unittest
from unittest.mock import patch

from test_chart import documents, env, pod, render, resource


class PreflightTests(unittest.TestCase):
    def job(self, values=None):
        merged = dict(values or {}, preflight={"enabled": True})
        return resource(documents(render(merged)), "Job")

    def test_optional_bounded_hook_and_no_service_selection_or_api_access(self):
        self.assertNotIn("Job", {d["kind"] for d in documents(render())})
        docs = documents(render({"preflight": {"enabled": True}}))
        job = resource(docs, "Job")
        self.assertEqual(job["metadata"]["annotations"]["helm.sh/hook"], "pre-install,pre-upgrade")
        self.assertEqual(job["metadata"]["annotations"]["helm.sh/hook-delete-policy"], "before-hook-creation,hook-succeeded")
        self.assertEqual(job["spec"]["activeDeadlineSeconds"], 120)
        self.assertEqual(job["spec"]["ttlSecondsAfterFinished"], 3600)
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        spec = job["spec"]["template"]["spec"]
        self.assertEqual(spec["restartPolicy"], "Never")
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertNotIn("serviceAccountName", spec)  # Chart SA is not created yet.
        self.assertNotIn("volumes", spec)
        self.assertNotIn("volumeMounts", spec["containers"][0])
        labels = job["spec"]["template"]["metadata"]["labels"]
        selector = resource(docs, "Service")["spec"]["selector"]
        self.assertFalse(all(labels.get(k) == v for k, v in selector.items()))
        self.assertEqual(spec["containers"][0]["image"], pod(docs)["containers"][0]["image"])
        self.assertTrue(spec["containers"][0]["securityContext"]["readOnlyRootFilesystem"])

    def test_checks_dba_maintenance_and_all_required_key_references(self):
        job = self.job({"database": {"host": "postgres.database.svc.cluster.local", "name": "not_created_yet"}})
        container = job["spec"]["template"]["spec"]["containers"][0]
        values = env(container)
        self.assertEqual(values["PGDATABASE"]["value"], "postgres")
        self.assertEqual(values["PGHOST"]["value"], "postgres.database.svc.cluster.local")
        self.assertEqual(values["PGUSER"]["valueFrom"]["secretKeyRef"], {"name": "zaq-dba", "key": "username"})
        self.assertTrue({"ZAQ_OWNER_PASSWORD", "ZAQ_READER_PASSWORD", "SECRET_KEY_BASE", "SYSTEM_CONFIG_ENCRYPTION_KEY"}.issubset(values))
        for item in values.values():
            if "valueFrom" in item:
                self.assertNotIn("optional", item["valueFrom"]["secretKeyRef"])

    def test_app_only_checks_owner_target_without_dba_or_reader_refs(self):
        job = self.job({"database": {"name": "prepared", "owner": "app_owner", "provisioning": {"enabled": False, "existingSecret": ""}}})
        container = job["spec"]["template"]["spec"]["containers"][0]
        values = env(container)
        self.assertEqual(values["PGDATABASE"]["value"], "prepared")
        self.assertEqual(values["ZAQ_OWNER"]["value"], "app_owner")
        self.assertTrue({"PGUSER", "PGPASSWORD", "ZAQ_READER_PASSWORD"}.isdisjoint(values))
        self.assertFalse(any(v.get("valueFrom", {}).get("secretKeyRef", {}).get("name") == "zaq-dba" for v in values.values()))

    def test_custom_secret_key_mappings_and_hook_name(self):
        job = resource(documents(render({"preflight": {"enabled": True}}, fixture="tests/fixtures/custom.yaml")), "Job")
        self.assertEqual(job["metadata"]["name"], "custom-zaq-preflight")
        values = env(job["spec"]["template"]["spec"]["containers"][0])
        for variable, name, key in [("PGUSER", "custom-dba", "dba-login"),
                                    ("PGPASSWORD", "custom-dba", "dba-password"),
                                    ("ZAQ_OWNER_PASSWORD", "custom-runtime", "app"),
                                    ("ZAQ_READER_PASSWORD", "custom-runtime", "reader"),
                                    ("SECRET_KEY_BASE", "custom-runtime", "phoenix"),
                                    ("SYSTEM_CONFIG_ENCRYPTION_KEY", "custom-runtime", "encryption")]:
            self.assertEqual(values[variable]["valueFrom"]["secretKeyRef"], {"name": name, "key": key})

    def test_long_hook_names_preserve_uniqueness(self):
        names = [self.job({"fullnameOverride": "a" * 60 + suffix})["metadata"]["name"] for suffix in ["x", "y"]]
        self.assertNotEqual(*names)
        self.assertTrue(all(len(name) <= 63 and name.endswith("-preflight") for name in names))

    def test_invalid_configuration(self):
        invalid = [{"enabled": "true"}, {"activeDeadlineSeconds": 0}, {"activeDeadlineSeconds": 601},
                   {"connectTimeoutSeconds": 0}, {"ttlSecondsAfterFinished": 59},
                   {"ttlSecondsAfterFinished": 86401}, {"sslMode": "invalid"},
                   {"enabled": True, "activeDeadlineSeconds": 15, "connectTimeoutSeconds": 15},
                   {"password": "forbidden"}]
        for value in invalid:
            with self.subTest(value=value):
                self.assertNotEqual(render({"preflight": value}).returncode, 0)
        self.assertNotEqual(render({"preflight": None}).returncode, 0)

    def test_script_is_read_only_and_never_logs_credentials_or_psql_errors(self):
        script = self.job()["spec"]["template"]["spec"]["containers"][0]["command"][2]
        inputs = {"PATH": os.environ["PATH"], "PGHOST": "remote", "PGPORT": "5432", "PGDATABASE": "postgres",
                  "PGSSLMODE": "prefer", "PGCONNECT_TIMEOUT": "3", "PGUSER": "dba", "PGPASSWORD": "dba-sensitive",
                  "ZAQ_OWNER": "owner", "ZAQ_OWNER_PASSWORD": "owner-sensitive", "SECRET_KEY_BASE": "key-sensitive"}
        for result in [subprocess.CompletedProcess([], 0, "1\n", ""),
                       subprocess.CompletedProcess([], 1, "", "error: dba-sensitive owner-sensitive key-sensitive"),
                       subprocess.TimeoutExpired("psql dba-sensitive", 3)]:
            output = io.StringIO()
            with patch.dict(os.environ, inputs, clear=True), patch("subprocess.run") as run:
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                with redirect_stdout(output), self.assertRaises(SystemExit) as exit:
                    exec(compile(script, "preflight", "exec"), {})
                self.assertEqual(exit.exception.code, 0 if getattr(result, "returncode", 1) == 0 else 1)
                self.assertEqual(run.call_args.args[0][-1], "BEGIN READ ONLY; SELECT 1; ROLLBACK;")
                self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
                self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
                self.assertNotIn("SECRET_KEY_BASE", run.call_args.kwargs["env"])
                self.assertNotIn("ZAQ_OWNER_PASSWORD", run.call_args.kwargs["env"])
                for secret in ["dba-sensitive", "owner-sensitive", "key-sensitive"]:
                    self.assertNotIn(secret, output.getvalue())
