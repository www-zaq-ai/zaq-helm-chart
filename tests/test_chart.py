"""Offline chart contract tests. No Kubernetes access or real credentials."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "zaq"
DEFAULTS = yaml.safe_load((CHART / "values.yaml").read_text())
SCHEMA = json.loads((CHART / "values.schema.json").read_text())
HELM = os.environ.get("HELM", "helm")


def render(values=None, release="sample", namespace="customer-a", fixture=None):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "values.yaml"
        path.write_text(yaml.safe_dump(values or {}))
        command = [HELM, "template", release, str(CHART), "--namespace", namespace,
                   "--kube-version", "1.31.0", "-f", str(path)]
        if fixture:
            command += ["-f", str(ROOT / fixture)]
        return subprocess.run(command, capture_output=True, text=True, check=False)


def documents(result):
    if result.returncode:
        raise AssertionError(result.stderr)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def resource(docs, kind):
    return next(doc for doc in docs if doc["kind"] == kind)


def pod(docs):
    return resource(docs, "Deployment")["spec"]["template"]["spec"]


def env(container):
    return {item["name"]: item for item in container["env"]}


class ChartTests(unittest.TestCase):
    def test_url_overrides_are_removed_and_image_defaults_are_preserved(self):
        for key in ["userPortalBaseUrl", "litellmBaseUrl"]:
            self.assertNotIn(key, DEFAULTS["app"])
            self.assertNotIn(key, SCHEMA["properties"]["app"]["properties"])
            for value in ["", "https://override.example.org"]:
                with self.subTest(key=key, value=value), self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(dict(DEFAULTS, app=dict(DEFAULTS["app"], **{key: value})), SCHEMA)
                self.assertNotEqual(render({"app": {key: value}}).returncode, 0)
        spec = pod(documents(render()))
        for container in spec.get("initContainers", []) + spec["containers"]:
            self.assertTrue({"USER_PORTAL_BASE_URL", "LITELLM_BASE_URL"}.isdisjoint(env(container)))

    def test_values_schema(self):
        jsonschema.Draft7Validator.check_schema(SCHEMA)
        jsonschema.validate(DEFAULTS, SCHEMA)
        for key in ["unknown", "password"]:
            with self.subTest(key=key), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(dict(DEFAULTS, **{key: "not-allowed"}), SCHEMA)

    def test_defaults(self):
        docs = documents(render())
        self.assertEqual({d["kind"] for d in docs},
                         {"Deployment", "Service", "ServiceAccount", "PersistentVolumeClaim"})
        deployment = resource(docs, "Deployment")
        self.assertEqual(deployment["spec"]["strategy"], {"type": "Recreate"})
        self.assertEqual(deployment["spec"]["replicas"], 1)
        self.assertEqual(resource(docs, "Service")["spec"]["type"], "ClusterIP")
        self.assertEqual(pod(docs)["containers"][0]["ports"][0]["containerPort"], 4000)
        for doc in docs:
            self.assertEqual(doc["metadata"]["namespace"], "customer-a")

    def test_credential_isolation(self):
        docs = documents(render(fixture="tests/fixtures/custom.yaml"))
        spec = pod(docs)
        app, init = spec["containers"][0], spec["initContainers"][0]
        app_env, init_env = env(app), env(init)
        self.assertEqual(app["image"], init["image"])
        self.assertNotIn("command", app)
        self.assertNotIn("command", init)
        self.assertNotIn("volumeMounts", init)
        self.assertNotIn("envFrom", app)
        self.assertNotIn("envFrom", init)
        self.assertTrue({"PGUSER", "PGPASSWORD", "ZAQ_READER_PASSWORD"}.isdisjoint(app_env))
        self.assertNotIn("SECRET_KEY_BASE", init_env)
        self.assertNotIn("SYSTEM_CONFIG_ENCRYPTION_KEY", init_env)
        self.assertNotIn("DATABASE_URL", app_env)  # Upstream entrypoint constructs it.
        self.assertEqual(app_env["ZAQ_OWNER_PASSWORD"]["valueFrom"]["secretKeyRef"],
                         {"name": "custom-runtime", "key": "app"})
        self.assertEqual(init_env["PGPASSWORD"]["valueFrom"]["secretKeyRef"],
                         {"name": "custom-dba", "key": "dba-password"})
        self.assertEqual(init_env["ZAQ_READER_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"], "reader")

    def test_custom_release_and_names(self):
        docs = documents(render(release="another", namespace="tenant-b"))
        self.assertEqual(resource(docs, "Deployment")["metadata"]["name"], "another-zaq")
        first = env(pod(docs)["containers"][0])["ZAQ_DATABASE"]["value"]
        other = env(pod(documents(render(namespace="tenant-b")))["containers"][0])["ZAQ_DATABASE"]["value"]
        self.assertNotEqual(first, other)
        self.assertLessEqual(len(first), 63)
        self.assertRegex(first, r"^[a-z_][a-z0-9_]*$")
        long_docs = documents(render(release="a" * 53, namespace="b" * 63))
        for key in ["ZAQ_DATABASE", "ZAQ_OWNER"]:
            self.assertLessEqual(len(env(pod(long_docs)["containers"][0])[key]["value"]), 63)

    def test_ingress_tls(self):
        docs = documents(render(fixture="examples/production.yaml"))
        spec = resource(docs, "Ingress")["spec"]
        self.assertEqual(spec["ingressClassName"], "nginx")
        self.assertEqual(spec["tls"][0]["secretName"], "customer-a-tls")
        self.assertEqual(spec["rules"][0]["host"], "zaq.example.org")

    def test_numeric_names_and_keys_remain_strings(self):
        docs = documents(render({"secrets": {"existingSecret": "123", "keys": {"ownerPassword": "456"}},
                                 "fullnameOverride": "789"}, namespace="123"))
        self.assertEqual(resource(docs, "Deployment")["metadata"]["namespace"], "123")
        self.assertEqual(resource(docs, "Deployment")["metadata"]["name"], "789")
        ref = env(pod(docs)["containers"][0])["ZAQ_OWNER_PASSWORD"]["valueFrom"]["secretKeyRef"]
        self.assertEqual(ref, {"name": "123", "key": "456"})

    def test_storage_class_states(self):
        for value in [None, "", "longhorn"]:
            with self.subTest(value=value):
                docs = documents(render({"persistence": {"storageClass": value}}))
                spec = resource(docs, "PersistentVolumeClaim")["spec"]
                if value is None:
                    self.assertNotIn("storageClassName", spec)
                else:
                    self.assertEqual(spec["storageClassName"], value)

    def test_existing_pvc_and_database(self):
        docs = documents(render(fixture="examples/existing-database-pvc.yaml"))
        self.assertNotIn("PersistentVolumeClaim", {d["kind"] for d in docs})
        spec = pod(docs)
        self.assertNotIn("initContainers", spec)
        self.assertEqual(spec["volumes"][0]["persistentVolumeClaim"]["claimName"], "customer-a-data")
        self.assertEqual(spec["containers"][0]["volumeMounts"][0]["mountPath"], "/zaq/volumes")

    def test_retention_and_ephemeral_storage(self):
        pvc = resource(documents(render()), "PersistentVolumeClaim")
        self.assertEqual(pvc["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
        pvc = resource(documents(render({"persistence": {"retain": False}})), "PersistentVolumeClaim")
        self.assertNotIn("annotations", pvc["metadata"])
        docs = documents(render({"persistence": {"enabled": False}}))
        self.assertNotIn("PersistentVolumeClaim", {d["kind"] for d in docs})
        self.assertEqual(pod(docs)["volumes"][0]["emptyDir"], {})

    def test_security_resources_scheduling(self):
        spec = pod(documents(render(fixture="tests/fixtures/custom.yaml")))
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertTrue(spec["securityContext"]["runAsNonRoot"])
        app = spec["containers"][0]
        self.assertFalse(app["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(app["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertEqual(app["resources"]["limits"]["memory"], "3Gi")
        self.assertEqual(spec["nodeSelector"], {"workload": "zaq"})
        self.assertEqual(spec["imagePullSecrets"], [{"name": "registry-auth"}])
        self.assertIn("affinity", spec)
        self.assertEqual(spec["tolerations"][0]["key"], "dedicated")

    def test_native_security_context_overrides(self):
        spec = pod(documents(render({"podSecurityContext": {"fsGroup": 2000},
                                     "securityContext": {"runAsGroup": 996},
                                     "database": {"provisioning": {"securityContext": {"runAsGroup": 996}}}})))
        self.assertEqual(spec["securityContext"]["fsGroup"], 2000)
        self.assertEqual(spec["containers"][0]["securityContext"]["runAsGroup"], 996)
        self.assertEqual(spec["initContainers"][0]["securityContext"]["runAsGroup"], 996)

    def test_probes_and_overrides(self):
        app = pod(documents(render()))["containers"][0]
        for name in ["startupProbe", "readinessProbe", "livenessProbe"]:
            self.assertEqual(app[name]["httpGet"]["httpHeaders"],
                             [{"name": "X-Forwarded-Proto", "value": "https"}])
            self.assertEqual(app[name]["httpGet"]["path"], "/channels/health")
        app = pod(documents(render({"probes": {"liveness": {"enabled": False},
                                               "startup": {"failureThreshold": 120}}})))["containers"][0]
        self.assertNotIn("livenessProbe", app)
        self.assertEqual(app["startupProbe"]["failureThreshold"], 120)

    def test_version_compatibility(self):
        for version in ["v0.18.0", "0.18.0", "v0.19.0", "v1.0.0", "v0.19.0-rc.1", "v0.18.0+build.1"]:
            with self.subTest(version=version):
                documents(render({"image": {"tag": version}}))
        for version in ["v0.17.9", "0.12.0", "v0.18.0-rc.1", "v0.9.0", "v0.18", "latest", "v0.19.0-01"]:
            with self.subTest(version=version):
                self.assertNotEqual(render({"image": {"tag": version}}).returncode, 0)
        documents(render({"image": {"tag": "custom", "appVersion": "v0.18.0"}}))
        digest = "sha256:" + "a" * 64
        self.assertNotEqual(render({"image": {"digest": digest}}).returncode, 0)
        docs = documents(render({"image": {"digest": digest, "appVersion": "0.18.0"}}))
        self.assertTrue(pod(docs)["containers"][0]["image"].endswith("@" + digest))
        for image in [{"appVersion": "0.19.0"}, {"tag": "custom", "appVersion": "0.17.0"},
                      {"tag": "custom", "appVersion": "banana"}]:
            with self.subTest(image=image):
                self.assertNotEqual(render({"image": image}).returncode, 0)

    def test_invalid_configuration(self):
        invalid = [
            {"secrets": {"existingSecret": ""}},
            {"secrets": {"keys": {"readerPassword": ""}}},
            {"database": {"provisioning": {"existingSecret": ""}}},
            {"database": {"port": 0}},
            {"database": {"owner": "same", "reader": "same"}},
            {"database": {"name": "postgres"}},
            {"database": {"owner": "pg_reserved"}},
            {"database": {"host": "host?ssl=false"}},
            {"database": {"name": "bad-name"}},
            {"persistence": {"size": "0Gi"}},
            {"persistence": {"enabled": False, "existingClaim": "data"}},
            {"persistence": {"existingClaim": "data", "storageClass": "longhorn"}},
            {"persistence": {"annotations": {"helm.sh/resource-policy": "keep"}}},
            {"replicaCount": 2},
            {"strategy": {"type": "RollingUpdate"}},
            {"strategy": {"rollingUpdate": {"maxSurge": 1}}},
            {"serviceAccount": {"create": False}},
            {"ingress": {"enabled": True, "host": "different.example.org"}},
            {"database": {"password": "forbidden"}},
        ]
        for values in invalid:
            with self.subTest(values=values):
                self.assertNotEqual(render(values).returncode, 0)

    def test_app_only_and_existing_service_account(self):
        docs = documents(render({"database": {"provisioning": {"enabled": False, "existingSecret": ""}},
                                 "secrets": {"keys": {"readerPassword": ""}},
                                 "serviceAccount": {"create": False, "name": "existing-sa"}}))
        self.assertEqual(pod(docs)["serviceAccountName"], "existing-sa")
        self.assertNotIn("ServiceAccount", {doc["kind"] for doc in docs})

    def test_no_secret_resources_or_hooks(self):
        docs = documents(render())
        for doc in docs:
            self.assertNotEqual(doc["kind"], "Secret")
            self.assertNotIn("helm.sh/hook", doc["metadata"].get("annotations", {}))


if __name__ == "__main__":
    unittest.main()
