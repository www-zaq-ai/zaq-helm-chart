import copy
import unittest

import jsonschema

from test_chart import DEFAULTS, SCHEMA, documents, render, resource


class IngressTests(unittest.TestCase):
    def test_simple_tls_uses_ingress_host_and_preserves_annotations(self):
        docs = documents(render(fixture="tests/fixtures/ingress-form.yaml"))
        ingress = resource(docs, "Ingress")
        self.assertEqual(ingress["metadata"]["annotations"], {"cert-manager.io/cluster-issuer": "letsencrypt-prod"})
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

    def test_invalid_tls_and_annotation_values_fail_schema_and_render(self):
        for ingress in [{"tlsEnabled": "true"}, {"tlsSecretName": 123},
                        {"tlsEnabled": True}, {"tlsEnabled": True, "tlsSecretName": ""},
                        {"tlsEnabled": True, "tlsSecretName": "invalid/name"},
                        {"tlsEnabled": True, "tlsSecretName": "tls", "tls": [{"secretName": "other", "hosts": ["zaq.example.com"]}]},
                        {"annotations": "not-a-map"}, {"annotations": {"some-key": True}}]:
            with self.subTest(ingress=ingress):
                values = copy.deepcopy(DEFAULTS)
                values["ingress"].update(ingress)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(values, SCHEMA)
                self.assertNotEqual(render({"ingress": ingress}).returncode, 0)
