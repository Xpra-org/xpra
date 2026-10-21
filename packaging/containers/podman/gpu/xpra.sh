#!/bin/bash
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

set -e

# the 'xpra' image from the 'split' pod, with the codecs and drivers for hardware accelerated video encoding:
BASE_IMAGE="${BASE_IMAGE:-xpra}"
IMAGE_NAME="${IMAGE_NAME:-xpra-gpu}"
CONTAINER="${IMAGE_NAME}-build"
# the GPU codecs to install:
# * `nvidia`: NVENC, the driver libraries are injected by the NVIDIA Container Toolkit when the container starts
# * `intel`: VA-API and oneVPL drivers for Intel GPUs, with H.264 and HEVC support from RPM Fusion nonfree
# * `mesa`: VA-API drivers for AMD (and other) GPUs, with H.264 and HEVC support from RPM Fusion
# * `amd`: AMF, which requires AMD's proprietary encoder library (`libamdenc-amdgpu-pro`),
#   and a custom xpra build with AMF support: `xpra-codecs-amd` is not available from the xpra repositories
GPU_CODECS="${GPU_CODECS:-nvidia intel mesa}"

run () {
  buildah run "$CONTAINER" "$@"
}

install () {
  run dnf install -y --setopt=install_weak_deps=False "$@"
}

if ! buildah inspect -t image "${BASE_IMAGE}" &> /dev/null; then
  (cd "$(dirname "$0")/../split" && bash ./xpra.sh)
fi
buildah rm "$CONTAINER" &> /dev/null || true
buildah rmi -f "${IMAGE_NAME}" &> /dev/null || true
buildah from --name "$CONTAINER" "${BASE_IMAGE}"
# the GPU codecs must be the same version as the other codecs already installed,
# the repository may already have newer builds:
XPRA_EVR=$(run rpm -q --qf '%{epoch}:%{version}-%{release}' xpra-codecs)
# the base image already has the RPM Fusion free repositories:
RPMFUSION_DIR=$(run sh -c '. /etc/os-release; if [ "${ID}" == "fedora" ]; then echo fedora; else echo el; fi')
VERSION_ID=$(run sh -c '. /etc/os-release; echo ${VERSION_ID%%.*}')

for codec in ${GPU_CODECS}; do
  case "${codec}" in
    nvidia)
      # `python3-pycuda` builds older than 2026.1-2 are missing their dependencies:
      install "xpra-codecs-nvidia-${XPRA_EVR}" python3-numpy
      ;;
    intel)
      # Fedora's 'libva-intel-media-driver' is built without the H.264 and HEVC codecs, which oneVPL also uses,
      # RPM Fusion's build is installed in 'dri-nonfree', which libva searches first:
      install "https://download1.rpmfusion.org/nonfree/${RPMFUSION_DIR}/rpmfusion-nonfree-release-${VERSION_ID}.noarch.rpm"
      install intel-media-driver intel-vpl-gpu-rt
      ;;
    mesa)
      # Fedora's mesa does not include the patent encumbered codecs,
      # RPM Fusion's 'mesa-va-drivers-freeworld' must be the same version as mesa,
      # and it is sometimes built before Fedora's mesa update is released:
      # only install it if this does not downgrade mesa, and if this mesa version is available
      MESA_VERSION=$(run sh -c "rpm -q mesa-filesystem > /dev/null && rpm -q --qf '%{version}\n' mesa-filesystem || true" | head -n 1)
      FREEWORLD_VERSION=$(run dnf repoquery -q --latest-limit=1 --qf '%{version}\n' mesa-va-drivers-freeworld | head -n 1)
      if [ -n "${MESA_VERSION}" ] && [ "$(printf '%s\n' "${MESA_VERSION}" "${FREEWORLD_VERSION}" | sort -V | head -n 1)" != "${MESA_VERSION}" ]; then
        echo "Warning: 'mesa-va-drivers-freeworld' ${FREEWORLD_VERSION} would downgrade mesa ${MESA_VERSION}" >&2
        echo " the VA-API drivers will not support H.264 and HEVC" >&2
      elif ! install "mesa-va-drivers-freeworld-${FREEWORLD_VERSION}"; then
        echo "Warning: 'mesa-va-drivers-freeworld' ${FREEWORLD_VERSION} cannot be installed, mesa ${FREEWORLD_VERSION} may not be released yet" >&2
        echo " the VA-API drivers will not support H.264 and HEVC" >&2
      fi
      ;;
    amd)
      # this requires a custom xpra build with AMF support,
      # `xpra-codecs-amd` is not available from the xpra repositories:
      install "xpra-codecs-amd-${XPRA_EVR}"
      ;;
    *)
      echo "unknown GPU codec '${codec}'" >&2
      exit 1
      ;;
  esac
done
run sh -c "rm -fr /var/cache/*dnf* /var/log/dnf*.log*"

buildah commit "$CONTAINER" "${IMAGE_NAME}"
buildah rm "$CONTAINER"
