#!/bin/bash
# =============================================================================
# IND321 - Build and load the GTP5G kernel module on an AL2023 EKS worker node.
# The Free5GC UPF (free5gc/upf:v4.2.3) requires gtp5g in the range
#   0.9.5 <= version < 0.10.0
# so we pin to tag v0.9.15. Building the default branch yields 0.10.x which the
# UPF rejects with "version mismatch".
#
# IMPORTANT (AL2023 kernel 6.12): the matching headers package is
#   kernel6.12-devel-$(uname -r)   (already shipped on the AL2023 6.12 AMI).
# Run as root on the node (e.g. via SSM).
# =============================================================================
set -uo pipefail
KREL="$(uname -r)"
GTP5G_TAG="${GTP5G_TAG:-v0.9.15}"
echo "Running kernel: ${KREL}  target gtp5g: ${GTP5G_TAG}"

# Unload any previously loaded (possibly wrong-version) module.
if lsmod | grep -q gtp5g; then
  echo "==> Unloading existing gtp5g module"
  rmmod gtp5g 2>&1 || echo "  (rmmod failed - may be in use; continuing)"
fi

echo "==> Ensuring build tools + matching kernel headers"
dnf -y install git make gcc >/dev/null 2>&1 || true
if ! rpm -q "kernel6.12-devel-${KREL}" >/dev/null 2>&1; then
  dnf -y install "kernel6.12-devel-${KREL}" || dnf -y install "kernel-devel-${KREL}" || true
fi
KDIR="/usr/src/kernels/${KREL}"
if [ ! -d "${KDIR}" ]; then
  echo "ERROR: kernel headers dir ${KDIR} missing; cannot build gtp5g."
  exit 1
fi

echo "==> Cloning gtp5g @ ${GTP5G_TAG} and building"
cd /root || exit 1
rm -rf gtp5g
git clone --branch "${GTP5G_TAG}" --depth 1 https://github.com/free5gc/gtp5g.git
cd gtp5g || exit 1
make clean || true
make
make install

echo "==> Loading module"
depmod -a
modprobe gtp5g || insmod ./gtp5g.ko
printf 'udp_tunnel\ngtp5g\n' > /etc/modules-load.d/gtp5g.conf

echo "==> Verify"
if lsmod | grep -q gtp5g; then
  lsmod | grep gtp5g
  # Print module version if available.
  modinfo gtp5g 2>/dev/null | grep -i version || true
  echo "GTP5G_LOADED_OK"
else
  echo "GTP5G_LOAD_FAILED"
  exit 1
fi
