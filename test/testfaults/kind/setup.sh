#!/usr/bin/env bash
# A kind cluster with Chaos Mesh, for test/testfaults/test_chaosmesh_on_kind.py (CI's `chaos-mesh` job).
# Every pin below is registered in docs/security/components.md; test_chaosmesh.py checks they agree.
set -euo pipefail

KIND_VERSION=v0.33.0
KIND_MODULE_HASH='h1:AjvDv3vOygb/VKLVQW87lfktIBzkxR8Ump9DjxC8+Lk='
CHART_VERSION=2.8.6
CHART_SHA256=1a3947427e1fab911372f869a70badc495a88b4d7a86f19a16b4c957b13859b1
CONTROLLER_DIGEST=sha256:ccdb92ca6d8e0f477cc87f86925442b65956be21a5118fadbd28e19836e8ce04
DAEMON_DIGEST=sha256:5e735d875fe7cdfbb7366d7826ab67d39a36c4ba26632cc928207abab7e5257d
CLUSTER=ipandora

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${RUNNER_TEMP:-$(mktemp -d)}/chaos-mesh"
mkdir -p "$WORK/bin"

# kind from source through the Go module proxy: `go install` checks it against the
# public checksum database (sum.golang.org), and the build info must name the admitted module hash.
GO="$(command -v go || ls -d /opt/hostedtoolcache/go/*/x64/bin/go 2>/dev/null | sort -V | tail -1)"
GOBIN="$WORK/bin" "$GO" install "sigs.k8s.io/kind@$KIND_VERSION"
if ! "$GO" version -m "$WORK/bin/kind" | grep -qP "^\tmod\tsigs\.k8s\.io/kind\t${KIND_VERSION}\t\Q${KIND_MODULE_HASH}\E$"; then
  echo "kind is not the admitted build ($KIND_VERSION $KIND_MODULE_HASH)" >&2
  exit 1
fi
"$WORK/bin/kind" create cluster --name "$CLUSTER" --config "$HERE/kind.yaml" --wait 180s

# the chart, checked against the digest its index publishes
curl -fsSLo "$WORK/chaos-mesh.tgz" "https://charts.chaos-mesh.org/chaos-mesh-${CHART_VERSION}.tgz"
echo "${CHART_SHA256}  $WORK/chaos-mesh.tgz" | sha256sum -c -
# only the controller and the daemon: no dashboard, no DNS server; their images by digest
helm install chaos-mesh "$WORK/chaos-mesh.tgz" --kube-context "kind-$CLUSTER" -n chaos-mesh --create-namespace \
  --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
  --set dashboard.create=false --set dnsServer.create=false --set controllerManager.replicaCount=1 \
  --set "controllerManager.image.tag=v${CHART_VERSION}@${CONTROLLER_DIGEST}" \
  --set "chaosDaemon.image.tag=v${CHART_VERSION}@${DAEMON_DIGEST}" \
  --wait --timeout 10m

kubectl --context "kind-$CLUSTER" apply -f "$HERE/web.yaml"
kubectl --context "kind-$CLUSTER" -n shop rollout status deploy/web --timeout=180s
kubectl --context "kind-$CLUSTER" get pods -A -o wide
