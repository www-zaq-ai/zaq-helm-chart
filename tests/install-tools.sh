#!/usr/bin/env bash
# Pinned tools, with publisher checksums. Installs outside the source tree.
set -euo pipefail
dest="${INSTALL_DIR:?Set INSTALL_DIR to a dedicated tools directory}"
mkdir -p "$dest"
dest="$(cd "$dest" && pwd)"
os="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in arm64|aarch64) arch=arm64 ;; x86_64) arch=amd64 ;; *) exit 1 ;; esac
work="$(mktemp -d "${TMPDIR:-/tmp}/zaq-tools.XXXXXX")"
trap 'rm -rf "$work"' EXIT
cd "$work"
verify() {
  if command -v sha256sum >/dev/null; then sha256sum -c "$1"; else shasum -a 256 -c "$1"; fi
}
helm_archive="helm-v3.18.6-${os}-${arch}.tar.gz"
curl -fsSLO "https://get.helm.sh/$helm_archive"
curl -fsSLO "https://get.helm.sh/$helm_archive.sha256sum"
verify "$helm_archive.sha256sum"
tar -xzf "$helm_archive"
install -m 755 "$os-$arch/helm" "$dest/helm"
kind_binary="kind-${os}-${arch}"
curl -fsSLO "https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/$kind_binary"
curl -fsSLO "https://github.com/kubernetes-sigs/kind/releases/download/v0.30.0/$kind_binary.sha256sum"
verify "$kind_binary.sha256sum"
install -m 755 "$kind_binary" "$dest/kind"
curl -fsSL "https://dl.k8s.io/release/v1.34.0/bin/$os/$arch/kubectl" -o kubectl
curl -fsSL "https://dl.k8s.io/release/v1.34.0/bin/$os/$arch/kubectl.sha256" -o kubectl.hash
printf '%s  kubectl\n' "$(cat kubectl.hash)" > kubectl.sha256
verify kubectl.sha256
install -m 755 kubectl "$dest/kubectl"
archive="kubeconform-${os}-${arch}.tar.gz"
curl -fsSLO "https://github.com/yannh/kubeconform/releases/download/v0.7.0/$archive"
curl -fsSL "https://github.com/yannh/kubeconform/releases/download/v0.7.0/CHECKSUMS" | grep "  $archive\$" > kubeconform.sha256
verify kubeconform.sha256
tar -xzf "$archive" kubeconform
install -m 755 kubeconform "$dest/kubeconform"
archive="actionlint_1.7.7_${os}_${arch}.tar.gz"
curl -fsSLO "https://github.com/rhysd/actionlint/releases/download/v1.7.7/$archive"
curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_checksums.txt" | grep "  $archive\$" > actionlint.sha256
verify actionlint.sha256
tar -xzf "$archive" actionlint
install -m 755 actionlint "$dest/actionlint"
printf 'Installed Helm 3.18.6, Kind 0.30.0, kubectl 1.34.0, kubeconform 0.7.0, actionlint 1.7.7 in %s\n' "$dest"
