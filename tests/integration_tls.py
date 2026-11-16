"""Real chart TLS tests against a disposable SSL-required Kind PostgreSQL.

Set ZAQ_TLS_TEST_IMAGE to a locally built, fixed ZAQ image containing PR #943.
No application source is patched. All credentials/certificates are ephemeral;
only reference names and non-sensitive settings enter Helm values.
"""

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from urllib.parse import quote

import yaml

from integration import CHART, NODE_IMAGE, POSTGRES_IMAGE, ROOT


def main():
    image = os.environ.get("ZAQ_TLS_TEST_IMAGE")
    if not image:
        raise SystemExit("ZAQ_TLS_TEST_IMAGE must select a local fixed image containing PR #943")
    suffix = secrets.token_hex(4)
    cluster = "zaq-tls-" + suffix
    namespace = "chart-tls"
    db_namespace = "database-tls"
    host = "postgres.database-tls.svc.cluster.local"
    trusted_image = "zaq-chart-tls-trust:" + suffix
    sensitive = []

    def run(args, text=None, check=True, timeout=600):
        result = subprocess.run(args, input=text, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        for value in sensitive:
            assert value not in result.stdout + result.stderr and quote(value, safe="") not in result.stdout + result.stderr, "Ephemeral credential in command output"
        if check and result.returncode:
            # Never echo application/client logs, Secret stdin, URLs, or environments.
            raise RuntimeError(f"{args[0]} {args[1]} failed (exit {result.returncode})")
        return result

    with tempfile.TemporaryDirectory(prefix="zaq-chart-tls-") as directory:
        path = Path(directory)
        kubeconfig = str(path / "kubeconfig")
        kubectl = ["kubectl", "--kubeconfig", kubeconfig, "-n", namespace]
        pgctl = ["kubectl", "--kubeconfig", kubeconfig, "-n", db_namespace]
        helm = ["helm", "--kubeconfig", kubeconfig, "-n", namespace]

        def apply(document, target=kubectl):
            run(target + ["apply", "-f", "-"], json.dumps(document))

        def secret(name, entries, target=kubectl):
            apply({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name}, "stringData": entries}, target)

        def get(kind, name):
            return json.loads(run(kubectl + ["get", kind, name, "-o", "json"]).stdout)

        def sql(statement):
            return run(pgctl + ["exec", "-i", "deployment/postgres", "--", "psql", "-XqAt", "-U", "postgres", "-d", "tls_zaq", "-v", "ON_ERROR_STOP=1"], statement).stdout.strip()

        def server_certificate(certificate):
            secret("postgres-tls", {"server.crt": certificate, "server.key": (path / "server.key").read_text(),
                                    "pg_hba.conf": "local all all trust\nhostnossl all all all reject\nhostssl all all all scram-sha-256\n"}, pgctl)
            expected = hashlib.sha256(certificate.encode()).hexdigest()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                actual = run(pgctl + ["exec", "deployment/postgres", "--", "sha256sum", "/tls/server.crt"]).stdout.split()[0]
                if actual == expected:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Test server certificate projection did not update")
            assert sql("SELECT pg_reload_conf();") == "t"

        def install(release, values, failure=False, upgrade=False):
            values_file = path / (release + ".yaml")
            values_file.write_text(yaml.safe_dump(values))
            result = run(helm + (["upgrade", "--install"] if upgrade else ["install"]) +
                         [release, str(CHART), "-f", str(values_file), "--wait", "--timeout", "60s" if failure else "10m"], check=not failure, timeout=720)
            if failure:
                assert result.returncode != 0, "TLS-negative installation unexpectedly became ready"

        def uninstall(release):
            run(helm + ["uninstall", release, "--wait"])
            run(kubectl + ["delete", "job", release + "-zaq-preflight", "--ignore-not-found", "--wait=true"])

        def health(release):
            script = ("import http.client; c=http.client.HTTPConnection('127.0.0.1',4000,timeout=5); "
                      "c.request('GET','/channels/health',headers={'X-Forwarded-Proto':'https'}); "
                      "assert c.getresponse().status==200")
            run(kubectl + ["exec", "deployment/" + release + "-zaq", "-c", "zaq", "--", "python3", "-c", script])

        def tls_failure(release, changes):
            candidate = copy.deepcopy(values)
            candidate["database"]["provisioning"] = {"enabled": False}
            candidate["preflight"] = {"enabled": False}
            for key, value in changes.items():
                if key == "host":
                    candidate["database"]["host"] = value
                else:
                    candidate["database"]["tls"][key] = value
            before = sql("SELECT count(*) FROM schema_migrations;")
            install(release, candidate, failure=True)
            pods = json.loads(run(kubectl + ["get", "pods", "-l", "app.kubernetes.io/instance=" + release, "-o", "json"]).stdout)["items"]
            status = pods[0]["status"]["containerStatuses"][0]
            exited = status.get("lastState", {}).get("terminated", status.get("state", {}).get("terminated", {}))
            assert exited.get("exitCode", 0) != 0, "Expected application/migration failure, not scheduling or image failure"
            logs = run(kubectl + ["logs", pods[0]["metadata"]["name"], "-c", "zaq"], check=False).stdout
            assert any(word in logs.lower() for word in ["ssl", "tls", "certificate", "cacert", "pem", "encryption", "pg_hba"]), "Failure must be TLS-related"
            assert before == sql("SELECT count(*) FROM schema_migrations;"), "TLS failure changed migration ledger"
            uninstall(release)

        # Certificate private keys never enter values or repository files.
        for name in ["ca", "untrusted"]:
            run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=ZAQ ephemeral " + name,
                 "-keyout", str(path / (name + ".key")), "-out", str(path / (name + ".crt"))])
        run(["openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=" + host,
             "-keyout", str(path / "server.key"), "-out", str(path / "server.csr")])
        (path / "server.ext").write_text("subjectAltName=DNS:" + host + "\nextendedKeyUsage=serverAuth\n")
        run(["openssl", "x509", "-req", "-in", str(path / "server.csr"), "-CA", str(path / "ca.crt"),
             "-CAkey", str(path / "ca.key"), "-CAcreateserial", "-days", "1", "-extfile", str(path / "server.ext"), "-out", str(path / "server.crt")])
        (path / "cert-index").write_text("")
        (path / "cert-serial").write_text("1000\n")
        (path / "expired.cnf").write_text(
            "[ca]\ndefault_ca=issuer\n[issuer]\n" +
            f"database={path}/cert-index\nserial={path}/cert-serial\nnew_certs_dir={path}\n" +
            f"certificate={path}/ca.crt\nprivate_key={path}/ca.key\n" +
            "default_md=sha256\npolicy=subject\nx509_extensions=server\n[subject]\ncommonName=supplied\n" +
            f"[server]\nsubjectAltName=DNS:{host}\nextendedKeyUsage=serverAuth\n")
        run(["openssl", "ca", "-batch", "-config", str(path / "expired.cnf"), "-in", str(path / "server.csr"),
             "-out", str(path / "expired-server.crt"), "-notext", "-startdate", "20200101000000Z", "-enddate", "20200102000000Z"])
        ca = (path / "ca.crt").read_text()
        dba = secrets.token_hex(32)
        runtime = {"owner-password": secrets.token_hex(32) + ":@/?#%", "reader-password": secrets.token_hex(32),
                   "secret-key-base": secrets.token_hex(64), "encryption-key": base64.b64encode(secrets.token_bytes(32)).decode()}
        sensitive.extend([dba, *runtime.values()])
        values = {"image": {"repository": image.rsplit(":", 1)[0], "tag": image.rsplit(":", 1)[1], "pullPolicy": "Never",
                            "appVersion": "0.19.0", "databaseTlsSupported": True},
                  "database": {"host": host, "name": "tls_zaq", "owner": "tls_owner", "reader": "tls_reader",
                               "tls": {"enabled": True, "ca": {"existingSecret": "zaq-dba", "key": "ca.crt"}},
                               "provisioning": {"sslMode": "verify-full"}},
                  "preflight": {"enabled": True, "sslMode": "verify-full"},
                  "persistence": {"enabled": False}, "resources": {"requests": {"cpu": "100m", "memory": "512Mi"}}}
        try:
            print("Creating disposable TLS Kind cluster", flush=True)
            run(["kind", "create", "cluster", "--name", cluster, "--image", NODE_IMAGE, "--kubeconfig", kubeconfig, "--wait", "180s"])
            run(["kind", "load", "docker-image", image, "--name", cluster])
            run(kubectl + ["create", "namespace", namespace])
            run(pgctl + ["create", "namespace", db_namespace])
            secret("zaq-dba", {"username": "postgres", "password": dba, "ca.crt": ca,
                                "untrusted.crt": (path / "untrusted.crt").read_text(), "invalid.crt": "not a PEM CA bundle"})
            secret("zaq-runtime", runtime)
            secret("postgres-auth", {"password": dba}, pgctl)
            secret("postgres-tls", {"server.crt": (path / "server.crt").read_text(), "server.key": (path / "server.key").read_text(),
                                    "pg_hba.conf": "local all all trust\nhostnossl all all all reject\nhostssl all all all scram-sha-256\n"}, pgctl)
            apply({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "postgres"}, "spec": {
                "replicas": 1, "selector": {"matchLabels": {"app": "postgres"}}, "template": {"metadata": {"labels": {"app": "postgres"}}, "spec": {
                    "automountServiceAccountToken": False, "containers": [{"name": "postgres", "image": POSTGRES_IMAGE,
                    "env": [{"name": "POSTGRES_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "postgres-auth", "key": "password"}}}],
                    "command": ["sh", "-c", "cp /tls/server.key /var/lib/postgresql/server.key && chown postgres:postgres /var/lib/postgresql/server.key && chmod 600 /var/lib/postgresql/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tls/server.crt -c ssl_key_file=/var/lib/postgresql/server.key -c hba_file=/tls/pg_hba.conf"],
                    "volumeMounts": [{"name": "tls", "mountPath": "/tls", "readOnly": True}],
                    "readinessProbe": {"exec": {"command": ["pg_isready", "-U", "postgres"]}, "periodSeconds": 2}}],
                    "volumes": [{"name": "tls", "secret": {"secretName": "postgres-tls"}}]}}}}, pgctl)
            for service in ["postgres", "wrong-host"]:
                apply({"apiVersion": "v1", "kind": "Service", "metadata": {"name": service},
                       "spec": {"selector": {"app": "postgres"}, "ports": [{"port": 5432}]}}, pgctl)
            run(pgctl + ["rollout", "status", "deployment/postgres", "--timeout=300s"])

            print("Testing verified provisioning, real migrations and application startup with CA from DBA Secret", flush=True)
            install("tls", values)
            health("tls")
            assert sql("SELECT count(*) FROM schema_migrations;") != "0"
            assert sql("SELECT count(*) FROM zaq_bootstrap.receipt;") == "1"
            assert sql("SELECT bool_and(s.ssl) FROM pg_stat_activity a JOIN pg_stat_ssl s USING(pid) WHERE a.usename='tls_owner';") == "t"
            script = ("from pathlib import Path; p=Path('/etc/zaq/database-ca'); "
                      "assert (p/'ca.crt').is_file(); assert not (p/'password').exists(); assert not (p/'username').exists()")
            run(kubectl + ["exec", "deployment/tls-zaq", "-c", "zaq", "--", "python3", "-c", script])
            records = run(helm + ["get", "manifest", "tls"]).stdout + run(helm + ["get", "values", "tls"]).stdout
            assert ca not in records, "CA contents must not enter Helm release records"
            print("Testing receipt validation and enabled/disabled provisioning upgrades over TLS", flush=True)
            run(kubectl + ["rollout", "restart", "deployment/tls-zaq"])
            run(kubectl + ["rollout", "status", "deployment/tls-zaq", "--timeout=300s"])
            values["database"]["provisioning"]["enabled"] = False
            install("tls", values, upgrade=True)
            health("tls")
            uninstall("tls")

            print("Testing independent provisioning and preflight plaintext modes are not overridden", flush=True)
            blocked = copy.deepcopy(values)
            blocked["database"]["provisioning"] = {"enabled": True, "sslMode": "disable"}
            blocked["preflight"]["enabled"] = False
            install("blocked-init", blocked, failure=True)
            pods = json.loads(run(kubectl + ["get", "pods", "-l", "app.kubernetes.io/instance=blocked-init", "-o", "json"]).stdout)["items"]
            status = pods[0]["status"]["initContainerStatuses"][0]
            assert status.get("lastState", {}).get("terminated", status.get("state", {}).get("terminated", {})).get("exitCode", 0) != 0
            uninstall("blocked-init")
            blocked = copy.deepcopy(values)
            blocked["preflight"]["sslMode"] = "disable"
            install("blocked-hook", blocked, failure=True)
            assert any(c["type"] == "Failed" for c in get("job", "blocked-hook-zaq-preflight")["status"]["conditions"])
            assert not run(kubectl + ["get", "deployment", "blocked-hook-zaq", "--ignore-not-found", "-o", "name"]).stdout
            uninstall("blocked-hook")

            for release, changes in [("wrong-ca", {"ca": {"existingSecret": "zaq-dba", "key": "untrusted.crt"}}),
                                     ("wrong-host", {"host": "wrong-host.database-tls.svc.cluster.local"}),
                                     ("no-trust", {"ca": {"existingSecret": "", "key": "ca.crt"}}),
                                     ("bad-pem", {"ca": {"existingSecret": "zaq-dba", "key": "invalid.crt"}}),
                                     ("plaintext", {"enabled": False})]:
                print("Testing rejection: " + release, flush=True)
                tls_failure(release, changes)

            print("Testing missing CA key is bounded by preflight Job deadline", flush=True)
            missing = copy.deepcopy(values)
            missing["database"]["tls"]["ca"]["key"] = "missing.crt"
            missing["preflight"]["activeDeadlineSeconds"] = 15
            install("missing-ca", missing, failure=True)
            assert any(c.get("reason") == "DeadlineExceeded" for c in get("job", "missing-ca-zaq-preflight")["status"]["conditions"])
            uninstall("missing-ca")

            print("Testing rejection of expired server certificates without plaintext fallback", flush=True)
            server_certificate((path / "expired-server.crt").read_text())
            tls_failure("expired", {})
            server_certificate((path / "server.crt").read_text())

            print("Testing system trust with CA installed in a test-only image trust store", flush=True)
            trust = path / "trust-image"
            trust.mkdir()
            (trust / "ca.crt").write_text(ca)
            dockerfile = f"FROM {image}\nUSER root\nCOPY ca.crt /usr/local/share/ca-certificates/zaq-test.crt\nRUN update-ca-certificates\nUSER appuser\n"
            run(["docker", "build", "-t", trusted_image, "-f", "-", str(trust)], dockerfile)
            run(["kind", "load", "docker-image", trusted_image, "--name", cluster])
            system = copy.deepcopy(values)
            system["image"].update(repository=trusted_image.rsplit(":", 1)[0], tag=trusted_image.rsplit(":", 1)[1])
            system["database"]["tls"]["ca"]["existingSecret"] = ""
            install("system", system)
            health("system")
            uninstall("system")
            print("Real TLS Kind integration passed; no existing database or application source changed", flush=True)
        finally:
            print("Deleting disposable TLS Kind cluster", flush=True)
            run(["kind", "delete", "cluster", "--name", cluster], check=False)
            run(["docker", "image", "rm", trusted_image], check=False)


if __name__ == "__main__":
    main()
