"""Disposable Kind installation tests; never targets the user's current context.

Run from the repository root after installing tests/requirements.txt and tools.
All credentials are ephemeral, passed as Secret JSON over stdin, never printed.
"""

import base64
import copy
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = Path(os.environ.get("ZAQ_CHART_PATH", ROOT / "charts" / "zaq"))
APP_IMAGE = "ghcr.io/www-zaq-ai/zaq@sha256:9bf0f9ae2299e777b56564992691eafb119d0ccba9f6d40696a1efe63a81097a"
POSTGRES_IMAGE = "pgvector/pgvector@sha256:3e8b3adfd27b5707128f60956f62a793c3c9326ea8cfaf0eab7adccb5d700b21"
NODE_IMAGE = "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"
NAMESPACE = "chart-test"
DATABASE_NAMESPACE = "database-test"


def run(command, input_text=None, check=True):
    result = subprocess.run(command, input=input_text, text=True, capture_output=True, cwd=ROOT)
    if check and result.returncode:
        # Do not echo stdin, environments, application logs, or Secret objects.
        raise RuntimeError(f"{command[0]} {command[1]} failed: {result.stderr[-2000:]}")
    return result


def main():
    cluster = "zaq-chart-" + secrets.token_hex(3)
    with tempfile.TemporaryDirectory(prefix="zaq-kind-") as directory:
        kubeconfig = str(Path(directory) / "kubeconfig")
        kubectl = ["kubectl", "--kubeconfig", kubeconfig, "-n", NAMESPACE]
        pgkubectl = ["kubectl", "--kubeconfig", kubeconfig, "-n", DATABASE_NAMESPACE]
        helm = ["helm", "--kubeconfig", kubeconfig, "--namespace", NAMESPACE]

        def apply(document, target=None):
            run((target or kubectl) + ["apply", "-f", "-"], json.dumps(document))

        def get(kind, name=None):
            return json.loads(run(kubectl + ["get", kind] + ([name] if name else []) + ["-o", "json"]).stdout)

        def secret(name, entries, target=None):
            apply({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name},
                   "type": "Opaque", "stringData": entries}, target=target)

        def install(release, values, expect_failure=False, upgrade=False):
            # Values contain references/settings only, never credentials.
            path = Path(directory) / (release + ".yaml")
            path.write_text(yaml.safe_dump(values))
            command = helm + (["upgrade", "--install"] if upgrade else ["install"])
            result = run(command + [release, str(CHART), "-f", str(path), "--wait", "--timeout",
                                    "100s" if expect_failure else "15m"], check=not expect_failure)
            if expect_failure:
                assert result.returncode != 0, "Expected failed installation became ready"

        def sql(text, role="dba", database="postgres", check=True):
            roles = {"dba": ("postgres", "POSTGRES_PASSWORD"),
                     "owner": ("integration_owner", "OWNER_PASSWORD"),
                     "reader": ("integration_reader", "READER_PASSWORD")}
            user, password_env = roles[role]
            script = (f'export PGPASSWORD="${password_env}"; '
                      f'exec psql -X -h 127.0.0.1 -U {user} -d {database} -At -v ON_ERROR_STOP=1')
            return run(pgkubectl + ["exec", "-i", "deployment/postgres", "--", "sh", "-c", script], text, check)

        def database_snapshot(database="postgres"):
            # Includes password hashes only in memory; never print the snapshot.
            return sql("SELECT datname,datdba FROM pg_database ORDER BY datname;").stdout + sql(
                "SELECT rolname,rolpassword,rolsuper,rolcreatedb,rolcreaterole FROM pg_authid ORDER BY rolname;"
                "SELECT extname,extversion,extowner FROM pg_extension ORDER BY extname;"
                "SELECT nspname,nspowner FROM pg_namespace ORDER BY nspname;", database=database).stdout

        def preflight(release, values, failure=False, deadline=False):
            check = copy.deepcopy(values)
            check["preflight"] = {"enabled": True, "activeDeadlineSeconds": 15,
                                  "connectTimeoutSeconds": 3, "ttlSecondsAfterFinished": 600}
            path = Path(directory) / (release + "-preflight.yaml")
            path.write_text(yaml.safe_dump(check))
            manifest = run(helm + ["template", release, str(CHART), "-f", str(path),
                                   "--show-only", "templates/preflight.yaml"]).stdout
            for value in sensitive_values:
                assert value not in manifest, "Preflight rendered a credential"
            job = yaml.safe_load(manifest)
            name = job["metadata"]["name"]
            started = time.monotonic()
            apply(job)
            waited = run(kubectl + ["wait", "--for=condition=" + ("failed" if failure else "complete"),
                                    "job/" + name, "--timeout=60s"], check=False)
            status = get("job", name)["status"]
            if waited.returncode:
                reasons = [c.get("reason", c["type"]) for c in status.get("conditions", [])]
                raise RuntimeError(f"Preflight {release} did not reach expected condition: {reasons}")
            if deadline:
                assert any(c["type"] == "Failed" and c["reason"] == "DeadlineExceeded" for c in status["conditions"])
                assert time.monotonic() - started < 60
            logs = run(kubectl + ["logs", "job/" + name], check=False).stdout
            for value in sensitive_values:
                assert value not in logs, "Preflight leaked a credential"
            if deadline:
                assert "ZAQ prerequisite connectivity check" not in logs
            elif not failure:
                assert "connectivity check passed" in logs
            run(kubectl + ["delete", "job", name, "--wait=true"])

        def health(release):
            # Use Python already bundled in ZAQ; assert 200, never follow redirects.
            script = (
                "import http.client,json; c=http.client.HTTPConnection('127.0.0.1',4000,timeout=5); "
                "c.request('GET','/channels/health',headers={'Host':'zaq.example.com','X-Forwarded-Proto':'https'}); "
                "r=c.getresponse(); assert r.status==200,r.status; "
                "assert json.loads(r.read())['status']=='ok'"
            )
            run(kubectl + ["exec", "deployment/" + release + "-zaq", "-c", "zaq", "--", "python3", "-c", script])

        try:
            print("Creating disposable Kind cluster", flush=True)
            run(["kind", "create", "cluster", "--name", cluster, "--image", NODE_IMAGE,
                 "--kubeconfig", kubeconfig, "--wait", "180s"])
            run(kubectl + ["create", "namespace", NAMESPACE])
            run(kubectl + ["create", "namespace", DATABASE_NAMESPACE])
            dba_password = secrets.token_hex(32)
            runtime = {"owner-password": secrets.token_hex(32) + "!@:/?#%",
                       "reader-password": secrets.token_hex(32) + "!@:/?#%",
                       "secret-key-base": secrets.token_hex(64),
                       "encryption-key": base64.b64encode(secrets.token_bytes(32)).decode()}
            sensitive_values = [dba_password, *runtime.values()]
            secret("zaq-dba", {"username": "postgres", "password": dba_password})
            secret("zaq-runtime", runtime)
            # The external DB's own disposable test Pod needs separate namespace-local refs.
            secret("zaq-dba", {"username": "postgres", "password": dba_password}, target=pgkubectl)
            secret("zaq-runtime", runtime, target=pgkubectl)

            def password_env(name, secret_name, key):
                return {"name": name, "valueFrom": {"secretKeyRef": {"name": secret_name, "key": key}}}

            apply({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "postgres"},
                   "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "postgres"}},
                            "template": {"metadata": {"labels": {"app": "postgres"}}, "spec": {
                                "containers": [{"name": "postgres", "image": POSTGRES_IMAGE,
                                                "env": [password_env("POSTGRES_PASSWORD", "zaq-dba", "password"),
                                                        password_env("OWNER_PASSWORD", "zaq-runtime", "owner-password"),
                                                        password_env("READER_PASSWORD", "zaq-runtime", "reader-password")],
                                                "readinessProbe": {"exec": {"command": ["pg_isready", "-U", "postgres"]},
                                                                   "periodSeconds": 2}}]}}}}, target=pgkubectl)
            apply({"apiVersion": "v1", "kind": "Service", "metadata": {"name": "postgresql"},
                   "spec": {"selector": {"app": "postgres"}, "ports": [{"port": 5432, "targetPort": 5432}]}}, target=pgkubectl)
            run(pgkubectl + ["rollout", "status", "deployment/postgres", "--timeout=300s"])
            assert not get("deployments")["items"]
            assert not get("services")["items"]  # No PostgreSQL workload/service in release namespace.

            print("Testing mock chart installation independently of PostgreSQL", flush=True)
            run(["docker", "build", "-t", "zaq-chart-mock:test", str(ROOT / "tests" / "mock")])
            run(["kind", "load", "docker-image", "zaq-chart-mock:test", "--name", cluster])
            install("mock", {"image": {"repository": "zaq-chart-mock", "tag": "test", "appVersion": "0.18.0", "pullPolicy": "Never"},
                             "persistence": {"retain": False}})
            run(helm + ["uninstall", "mock", "--wait"])
            assert not [p for p in get("pvc")["items"] if p["metadata"]["name"] == "mock-zaq"]

            values = {"image": {"digest": APP_IMAGE.split("@")[1], "appVersion": "0.18.0"},
                      "database": {"host": "postgresql.database-test.svc.cluster.local", "name": "integration_zaq", "owner": "integration_owner", "reader": "integration_reader"},
                      "preflight": {"enabled": True},
                      "resources": {"requests": {"cpu": "100m", "memory": "512Mi"}},
                      "persistence": {"size": "1Gi"}}
            # Separate image download time from the intentionally short deadline cases.
            apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "zaq-image-cache"},
                   "spec": {"restartPolicy": "Never", "automountServiceAccountToken": False,
                            "containers": [{"name": "cache", "image": APP_IMAGE,
                                            "command": ["python3", "-c", "print('Image cached')"]}]}}, target=pgkubectl)
            run(pgkubectl + ["wait", "--for=jsonpath={.status.phase}=Succeeded", "pod/zaq-image-cache", "--timeout=600s"])
            run(pgkubectl + ["delete", "pod", "zaq-image-cache", "--wait=true"])
            print("Testing preflight against cross-namespace DB before target DB/roles exist", flush=True)
            before = database_snapshot()
            preflight("preflight-dba", values)
            assert before == database_snapshot()
            secret("malformed-key", dict(runtime, **{"encryption-key": "not-an-application-key"}))
            malformed = copy.deepcopy(values)
            malformed["secrets"] = {"existingSecret": "malformed-key"}
            preflight("preflight-presence-only", malformed)  # Key contents belong to ZAQ boot validation.
            missing = copy.deepcopy(values)
            missing["database"]["provisioning"] = {"existingSecret": "missing-dba"}
            preflight("preflight-missing-secret", missing, failure=True, deadline=True)
            secret("incomplete-runtime", {k: v for k, v in runtime.items() if k != "encryption-key"})
            missing_key = copy.deepcopy(values)
            missing_key["secrets"] = {"existingSecret": "incomplete-runtime"}
            preflight("preflight-missing-key", missing_key, failure=True, deadline=True)
            secret("incomplete-dba", {"username": "postgres"})
            missing_dba_key = copy.deepcopy(values)
            missing_dba_key["database"]["provisioning"] = {"existingSecret": "incomplete-dba"}
            preflight("preflight-missing-dba-key", missing_dba_key, failure=True, deadline=True)
            wrong_dba_password = secrets.token_hex(32)
            sensitive_values.append(wrong_dba_password)
            secret("wrong-dba", {"username": "postgres", "password": wrong_dba_password})
            bad_dba = copy.deepcopy(values)
            bad_dba["database"]["provisioning"] = {"existingSecret": "wrong-dba"}
            preflight("preflight-bad-dba", bad_dba, failure=True)
            unreachable = copy.deepcopy(values)
            unreachable["database"]["port"] = 1
            preflight("preflight-unreachable", unreachable, failure=True)
            assert before == database_snapshot(), "Preflight mutated database or credentials"
            print("Testing bounded Helm hook failure before workload creation", flush=True)
            missing["preflight"] = {"enabled": True, "activeDeadlineSeconds": 15, "connectTimeoutSeconds": 3}
            install("blocked", missing, expect_failure=True)
            assert not run(kubectl + ["get", "deployment", "blocked-zaq", "--ignore-not-found", "-o", "name"]).stdout
            assert any(c.get("reason") == "DeadlineExceeded" for c in get("job", "blocked-zaq-preflight")["status"]["conditions"])
            run(helm + ["uninstall", "blocked", "--wait"])
            run(kubectl + ["delete", "job", "blocked-zaq-preflight", "--ignore-not-found"])
            print("Testing real ZAQ bootstrap, migrations, probes, PVC and successful Helm hooks", flush=True)
            # Verify API-accepted routing/TLS configuration; no controller or issuer
            # is installed here, so this does not prove HTTPS/certificate issuance.
            values["ingress"] = {"enabled": True, "host": "zaq.example.com", "className": "nginx",
                                 "annotations": {"cert-manager.io/cluster-issuer": "test-issuer"},
                                 "tlsEnabled": True, "tlsSecretName": "externally-managed-tls"}
            install("real", values)
            ingress = get("ingress", "real-zaq")
            assert ingress["metadata"]["annotations"]["cert-manager.io/cluster-issuer"] == "test-issuer"
            for key, value in {"nginx.ingress.kubernetes.io/proxy-body-size": "50M",
                               "nginx.org/client-max-body-size": "50M",
                               "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
                               "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600"}.items():
                assert ingress["metadata"]["annotations"][key] == value
            for container in get("deployment", "real-zaq")["spec"]["template"]["spec"]["containers"]:
                assert {"USER_PORTAL_BASE_URL", "LITELLM_BASE_URL"}.isdisjoint(e["name"] for e in container["env"])
            assert ingress["spec"]["tls"] == [{"secretName": "externally-managed-tls", "hosts": ["zaq.example.com"]}]
            assert get("service", "real-zaq")["spec"]["type"] == "ClusterIP"
            assert not run(kubectl + ["get", "secret", "externally-managed-tls", "--ignore-not-found", "-o", "name"]).stdout
            assert not run(kubectl + ["get", "job", "real-zaq-preflight", "--ignore-not-found", "-o", "name"]).stdout
            health("real")
            assert sql("SELECT count(*) FROM public.schema_migrations;", "owner", "integration_zaq").stdout.strip() != "0"
            assert sql("SELECT count(*) FROM public.users;", "reader", "integration_zaq").returncode == 0
            sql("CREATE TABLE public.chart_acl_test (id integer); INSERT INTO public.chart_acl_test VALUES (1);",
                "owner", "integration_zaq")
            assert sql("SELECT id FROM public.chart_acl_test;", "reader", "integration_zaq").stdout.strip() == "1"
            assert sql("INSERT INTO public.chart_acl_test VALUES (2);", "reader", "integration_zaq", check=False).returncode != 0
            flags = sql("SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname IN ('integration_owner','integration_reader');").stdout.splitlines()
            assert flags == ["f", "f"], flags
            receipt = sql("SELECT count(*) FROM zaq_bootstrap.receipt;", database="integration_zaq").stdout.strip()
            assert receipt == "1"
            app_only_check = copy.deepcopy(values)
            app_only_check["database"]["provisioning"] = {"enabled": False}
            before = database_snapshot("integration_zaq")
            preflight("preflight-owner", app_only_check)
            assert before == database_snapshot("integration_zaq")
            password_state = sql("SELECT rolname, rolpassword FROM pg_authid WHERE rolname IN ('integration_owner','integration_reader') ORDER BY rolname;").stdout
            print("Testing Pod replacement and receipt validation without password changes", flush=True)
            run(kubectl + ["rollout", "restart", "deployment/real-zaq"])
            run(kubectl + ["rollout", "status", "deployment/real-zaq", "--timeout=600s"])
            health("real")
            assert password_state == sql("SELECT rolname, rolpassword FROM pg_authid WHERE rolname IN ('integration_owner','integration_reader') ORDER BY rolname;").stdout

            print("Testing credential mismatch blocks initialization", flush=True)
            wrong = dict(runtime, **{"owner-password": secrets.token_hex(32)})
            sensitive_values.append(wrong["owner-password"])
            secret("wrong-runtime", wrong)
            bad_owner_check = copy.deepcopy(app_only_check)
            bad_owner_check["secrets"] = {"existingSecret": "wrong-runtime"}
            preflight("preflight-bad-owner", bad_owner_check, failure=True)
            bad = copy.deepcopy(values)
            bad["secrets"] = {"existingSecret": "wrong-runtime"}
            bad["persistence"] = {"enabled": False}
            bad["preflight"] = {"enabled": False}  # Test original bootstrap guard, not the hook.
            install("bad", bad, expect_failure=True)
            bad_pods = get("pods")["items"]
            bad_pod = next(p for p in bad_pods if p["metadata"]["labels"].get("app.kubernetes.io/instance") == "bad")
            init = bad_pod["status"]["initContainerStatuses"][0]
            assert init.get("lastState", {}).get("terminated", {}).get("exitCode", 0) != 0 or init.get("state", {}).get("terminated", {}).get("exitCode", 0) != 0
            assert get("deployment", "bad-zaq")["status"].get("availableReplicas", 0) == 0
            run(helm + ["uninstall", "bad", "--wait"])

            print("Testing migration failure blocks application readiness", flush=True)
            sql("CREATE DATABASE broken_migrations OWNER integration_owner;")
            broken = copy.deepcopy(values)
            broken["database"].update({"name": "broken_migrations", "provisioning": {"enabled": False}})
            broken["persistence"] = {"enabled": False}
            broken["preflight"] = {"enabled": False}
            install("broken", broken, expect_failure=True)
            broken_pod = next(p for p in get("pods")["items"] if p["metadata"]["labels"].get("app.kubernetes.io/instance") == "broken")
            status = broken_pod["status"]["containerStatuses"][0]
            assert status.get("lastState", {}).get("terminated", {}).get("exitCode", 0) != 0 or status.get("state", {}).get("terminated", {}).get("exitCode", 0) != 0
            run(helm + ["uninstall", "broken", "--wait"])

            print("Testing app-only upgrade and uninstall retention", flush=True)
            values["database"]["provisioning"] = {"enabled": False}
            values["ingress"]["tlsEnabled"] = False
            values["ingress"]["annotations"]["nginx.ingress.kubernetes.io/proxy-read-timeout"] = "7200"
            install("real", values, upgrade=True)
            assert "tls" not in get("ingress", "real-zaq")["spec"]
            assert get("ingress", "real-zaq")["metadata"]["annotations"]["nginx.ingress.kubernetes.io/proxy-read-timeout"] == "7200"
            health("real")
            run(helm + ["uninstall", "real", "--wait"])
            assert not get("ingresses")["items"]
            get("pvc", "real-zaq")
            get("secret", "zaq-runtime")
            get("secret", "zaq-dba")
            values["persistence"]["existingClaim"] = "real-zaq"
            print("Testing reinstall with existing database and retained PVC", flush=True)
            install("real", values)
            health("real")
            run(helm + ["uninstall", "real", "--wait"])
            get("pvc", "real-zaq")
            assert not [d for d in get("deployments")["items"] if d["metadata"]["name"] != "postgres"]
            print("Kind integration passed: mock and real installations, ACLs, restart, failure gates, upgrade, reuse, uninstall", flush=True)
        except Exception:
            state = run(kubectl + ["get", "pods"], check=False)
            print(state.stdout, flush=True)
            raise
        finally:
            print("Deleting disposable Kind cluster", flush=True)
            run(["kind", "delete", "cluster", "--name", cluster], check=False)


if __name__ == "__main__":
    main()
