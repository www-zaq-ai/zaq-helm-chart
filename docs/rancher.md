# Installing with Rancher

The chart uses standard Kubernetes resources and does not depend on Rancher APIs.
Review [deployment prerequisites](deployment.md#prerequisites) first.

## Prepare the namespace and dependencies

1. Select the target cluster/project in Rancher and create a namespace, for
   example `customer-a`.
2. Create/import the [DBA and deployment Secrets](deployment.md#pre-existing-secrets)
   in that namespace using Rancher or external API/secret-management automation.
   The DBA Secret is unnecessary when provisioning is disabled.
3. Verify PostgreSQL reachability and provisioning privileges, and select an
   [existing StorageClass or PVC](storage.md).
4. Prepare your Ingress controller, hostname/DNS, and TLS Secret or certificate
   integration. See [networking](operations.md#networking).

Rancher's install UI can create a namespace. Creating it beforehand is recommended
here because the required Secrets must already exist in it before ZAQ starts.
Creating Secrets after installation can leave Pods blocked and Helm waiting until
its timeout. The chart does not include a Namespace or credential Secret template.

## Configure values

Adapt [`examples/production.yaml`](../examples/production.yaml), using the
[values reference](values.md). Select your database endpoint/identities, existing
Secret names, hostname, Ingress class/TLS Secret, and StorageClass or PVC.
The example names `longhorn` and `nginx` are not assumed to exist in every cluster.
Never enter passwords or application keys into Helm values.

**ZAQ v0.19.0 requires cluster-wide `CREATEROLE` for its application owner.**
Review the [shared-server trust implications](deployment.md#owner-privilege-scope)
with your DBA. For existing v0.18.0 deployments, arrange the documented external
DBA maintenance before upgrading; Rancher's form and preflight do not repair
that privilege contract automatically.

The packaged chart includes a README for chart details and `questions.yaml` for
Rancher's form. It offers namespace-local **existing Secret name** selectors and
key-name mappings, not credential inputs; Secret creation remains external.
Database hostnames may point outside the namespace/cluster. Optional preflight
is available in the form; see [its failure behavior](operations.md#optional-prerequisite-preflight).

Use Values YAML for advanced settings and review it before installing. In
particular, when switching from a selected StorageClass to an existing PVC,
clear `persistence.storageClass` to `null`/unset: hiding a field does not clear
its previous answer. To clear an existing PVC answer, use `existingClaim: ""`.

### Additional application environment variables

The **Application → Additional application environment variables** key/value
editor sets `app.extraEnv`. Enter non-sensitive strings, for example
`REQ_LLM_POOL_SIZE` → `8` (a supported v0.19.0 setting). Do not enter passwords,
API tokens, or application keys here: form values are stored in Helm release
records. Variables only affect behavior when the selected ZAQ image supports
them; arbitrary names are not new ZAQ configuration features.

For sensitive variables, use **Values YAML** with existing namespace-local
Secret-key references, never credential values:

```yaml
app:
  extraEnv:
    REQ_LLM_POOL_SIZE: "8"
  extraEnvSecrets:
    - name: MY_API_TOKEN
      secretKeyRef:
        name: integration-secrets
        key: api-token
```

Both sources reach only the ZAQ application container. Reserved database,
startup, credentials, and storage names and duplicate custom names are rejected;
see [rules and lifecycle](values.md#custom-environment-variables). Changing these
settings rolls out the Pod; changing Secret contents alone requires a restart.

### Ingress annotations and TLS

Enabling Ingress creates routing to the chart's internal ClusterIP Service;
the Ingress hostname must match `app.host`. In the form:

- **Ingress annotations** prefills the two NGINX body-size defaults (`50M`)
  and ingress-nginx read/send timeouts (`"3600"` seconds). Edit individual values
  and add other key/value pairs, for example
  `cert-manager.io/cluster-issuer` → `letsencrypt-prod`. Additional entries merge
  with the chart defaults. Each controller applies the annotations it supports.
- **Enable TLS** adds a TLS entry using the Ingress hostname.
- **TLS Secret name** appears when TLS is enabled. Enter the name of an existing
  TLS Secret in the release namespace, or a Secret that cert-manager will create.
  This is a text field so the Secret need not already exist; never enter
  certificate/private-key values.

The chart does not issue certificates or install cert-manager. Automatic issuance
and renewal require an installed cert-manager, a configured Issuer/ClusterIssuer,
and working DNS/ACME challenges. Alternatively, supply the TLS Secret externally.
The Ingress controller terminates HTTPS; backend traffic to ZAQ remains HTTP.

Equivalent non-sensitive values, assuming a configured `letsencrypt-prod`
ClusterIssuer and an `nginx` Ingress controller:

```yaml
app:
  host: zaq.example.org
ingress:
  enabled: true
  className: nginx
  host: zaq.example.org
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  tlsEnabled: true
  tlsSecretName: zaq-tls
```

For advanced TLS configuration, keep `ingress.tlsEnabled: false` and configure
the existing `ingress.tls` list in **Values YAML**. Using the checkbox and a
nonempty advanced list together is rejected. Clear that list before enabling
the checkbox; unchecking it does not disable TLS supplied by the advanced list.
Hidden fields retain their answers: a Secret name alone is ignored with the
checkbox off, and disabling Ingress suppresses the entire Ingress resource.

In **Rancher 2.10.3**, test charts appear after enabling **Avatar → Preferences →
Helm Charts → Include Prerelease Versions**. Select the intended test version
explicitly; it remains a temporary prerelease, not a production release.

## Install

Use Rancher's supported OCI chart installation workflow if your version provides
one. The intended published chart is `oci://ghcr.io/www-zaq-ai/charts/zaq`.
This repository publishes OCI artifacts, not a traditional `index.yaml` Helm
repository; do not add the GitHub source URL as an ordinary chart repository.

Alternatively, download the cluster's kubeconfig from Rancher and use Helm from
the repository root, explicitly selecting that kubeconfig:

```sh
helm upgrade --install customer-a ./charts/zaq \
  --kubeconfig "$HOME/.kube/customer-cluster.yaml" \
  --namespace customer-a --values your-values.yaml \
  --wait --timeout 20m
```

For a published chart, replace `./charts/zaq` with the OCI reference and add an
explicit `--version`. See [GHCR installation](deployment.md#install-from-ghcr).
Keep your kubeconfig protected; the chart does not require committing it.

## Verify the installation

In Rancher's workload view, verify that the provisioning init container completes,
the Deployment becomes available, and the PVC is bound. The default resource name
for this example is `customer-a-zaq`.

Open `https://your-hostname/bo/login` and complete
[first-login setup](deployment.md#first-login) before allowing public access.
The workloads remain inspectable in Rancher even when installed through the CLI.
See [operations and troubleshooting](operations.md) for failures and upgrades.
