#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION="3.12.9"
INSTALL_DIR="C:\\Program Files\\Python"
BASE_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}"

# Detect architecture
case "$(uname -m)" in
    x86_64)  ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

INSTALLER="python-${PYTHON_VERSION}-${ARCH}.exe"
DOWNLOAD_URL="${BASE_URL}/${INSTALLER}"

# Download if not already present
if [[ ! -f "$INSTALLER" ]]; then
    echo "Downloading Python ${PYTHON_VERSION} (${ARCH})..."
    curl -fL -o "$INSTALLER" "$DOWNLOAD_URL"
fi

echo "Installing Python ${PYTHON_VERSION} (${ARCH}) to ${INSTALL_DIR}..."
./"$INSTALLER" \
    /quiet \
    InstallAllUsers=1 \
    TargetDir="${INSTALL_DIR}" \
    DefaultAllUsersTargetDir="${INSTALL_DIR}" \
    PrependPath=0 \
    Shortcuts=0 \
    Include_doc=0 \
    Include_test=0 \
    Include_pip=1 \
    Include_launcher=0

echo "Done."
