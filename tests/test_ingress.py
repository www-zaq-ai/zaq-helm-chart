import copy
import unittest

import jsonschema

from test_chart import DEFAULTS, SCHEMA, documents, pod, render, resource


class IngressTests(unittest.TestCase):
    def test_default_service_targets_numeric_application_port(self):
        docs = documents(render())
        self.assertEqual(resource(docs, "Service")["spec"]["ports"],
                         [{"name": "http", "port": 4000, "targetPort": 4000, "protocol": "TCP"}])
        self.assertEqual(pod(docs)["containers"][0]["ports"],
                         [{"name": "http", "containerPort": 4000, "protocol": "TCP"}])

    def test_numeric_ingress_backend_follows_service_port_not_container_port(self):
        for port in [4000, 80, 8080]:
            with self.subTest(port=port):
                values = {"ingress": {"enabled": True}}
                if port != 4000:
                    values["service"] = {"port": port}
                docs = documents(render(values))
                service = resource(docs, "Service")
                self.assertEqual(service["spec"]["ports"],
                                 [{"name": "http", "port": port, "targetPort": 4000, "protocol": "TCP"}])
                backend = resource(docs, "Ingress")["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
                self.assertEqual(backend, {"name": service["metadata"]["name"], "port": {"number": port}})

    def test_simple_tls_uses_ingress_host_and_preserves_annotations(self):
        docs = documents(render(fixture="tests/fixtures/ingress-form.yaml"))
        ingress = resource(docs, "Ingress")
        self.assertEqual(ingress["metadata"]["annotations"], dict(DEFAULTS["ingress"]["annotations"],
                                                               **{"cert-manager.io/cluster-issuer": "letsencrypt-prod"}))
        self.assertEqual(ingress["spec"]["tls"], [{"secretName": "form-tls", "hosts": ["form.example.org"]}])
        service = resource(docs, "Service")
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        self.assertEqual(ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"], service["metadata"]["name"])
        self.assertTrue({"Secret", "Certificate", "Issuer", "ClusterIssuer"}.isdisjoint(d["kind"] for d in docs))

    def test_unchecked_tls_ignores_retained_secret_name(self):
        docs = documents(render({"ingress": {"enabled": True, "tlsSecretName": "retained-tls"}}))
        self.assertNotIn("tls", resource(docs, "Ingress")["spec"])
        docs = documents(render({"ingress": {"tlsEnabled": True, "tlsSecretName": "retained-tls"}}))
        self.assertNotIn("Ingress", [d["kind"] for d in docs])

    def test_advanced_list_remains_unchanged(self):
        tls = [{"secretName": "advanced-tls", "hosts": ["zaq.example.com", "other.example.com"]},
               {"secretName": "second-tls", "hosts": ["another.example.com"]}]
        docs = documents(render({"ingress": {"enabled": True, "tls": tls, "tlsSecretName": "ignored"}}))
        self.assertEqual(resource(docs, "Ingress")["spec"]["tls"], tls)

    def test_default_annotations_are_strings_and_remain_overridable(self):
        expected = {"nginx.ingress.kubernetes.io/proxy-body-size": "50M",
                    "nginx.org/client-max-body-size": "50M",
                    "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
                    "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600"}
        docs = documents(render({"ingress": {"enabled": True}}))
        self.assertEqual(resource(docs, "Ingress")["metadata"]["annotations"], expected)
        overrides = {"nginx.ingress.kubernetes.io/proxy-body-size": "100M",
                     "nginx.ingress.kubernetes.io/proxy-read-timeout": "7200",
                     "example.org/custom": "enabled"}
        docs = documents(render({"ingress": {"enabled": True, "annotations": overrides}}))
        expected.update(overrides)
        self.assertEqual(resource(docs, "Ingress")["metadata"]["annotations"], expected)

    def test_invalid_tls_and_annotation_values_fail_schema_and_render(self):
        for ingress in [{"tlsEnabled": "true"}, {"tlsSecretName": 123},
                        {"tlsEnabled": True}, {"tlsEnabled": True, "tlsSecretName": ""},
                        {"tlsEnabled": True, "tlsSecretName": "invalid/name"},
                        {"tlsEnabled": True, "tlsSecretName": "tls", "tls": [{"secretName": "other", "hosts": ["zaq.example.com"]}]},
                        {"annotations": "not-a-map"}, {"annotations": {"some-key": True}},
                        {"annotations": {"nginx.ingress.kubernetes.io/proxy-read-timeout": 3600}}]:
            with self.subTest(ingress=ingress):
                values = copy.deepcopy(DEFAULTS)
                values["ingress"].update(ingress)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(values, SCHEMA)
                self.assertNotEqual(render({"ingress": ingress}).returncode, 0)
