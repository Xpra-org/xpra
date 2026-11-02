#!/bin/bash

# choose the channel with the REPO environment variable:
# "xpra" (stable, the default), "xpra-lts" or "xpra-beta"
# ie: curl https://xpra.org/get-xpra.sh | REPO=xpra-beta bash
# without it, some distributions default to a different channel, see deb_default_repo
REPO_SET="${REPO:+1}"
REPO="${REPO:-xpra}"
case "${REPO}" in
  xpra|xpra-lts|xpra-beta)
    ;;
  *)
    echo "invalid REPO '${REPO}', use 'xpra', 'xpra-lts' or 'xpra-beta'"
    exit 1
    ;;
esac
GITHUB_REPOS="https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos"

# OSNAME=$(grep -e "^NAME=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
# examples:
# MSYS2, Fedora Linux, Debian GNU/Linux, AlmaLinux Kitten, Ubuntu, Linux Mint
ID=$(grep -e "^ID=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
# examples:
# msys2, fedora, debian, almalinux, ubuntu, linuxmint
VERSION_ID=$(grep -e "^VERSION_ID=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
MAJOR_VERSION=${VERSION_ID%.*}

if [ "${ID}" == "msys2" ]; then
  pacman -S "${MINGW_PREFIX}-xpra"
  exit 1
fi

# download a file and install it, so that a failed download
# (ie: no repository file for this distribution)
# cannot leave an invalid file behind:
download() {
  URL=$1
  DST=$2
  TMP=$(mktemp)
  if ! curl -f -L -o "${TMP}" "${URL}"; then
    rm -f "${TMP}"
    echo "failed to download ${URL}"
    exit 1
  fi
  sudo cp "${TMP}" "${DST}"
  sudo chmod 644 "${DST}"
  rm -f "${TMP}"
}

# Helper for Linux Mint → detect the Ubuntu base codename
get_ubuntu_codename_from_mint() {
  local repo_file="/etc/apt/sources.list.d/official-package-repositories.list"
  local codename=""

  # First, try to read from official-package-repositories.list if present
  if [ -r "${repo_file}" ]; then
    codename=$(grep "^deb " "${repo_file}" \
      | grep -E "ubuntu\.com/ubuntu" \
      | head -n1 \
      | awk '{print $3}' \
      | sed 's/-.*$//')
  fi

  # If that failed, fallback to apt-cache policy
  if [ -z "${codename}" ] && command -v apt-cache >/dev/null 2>&1; then
    codename=$(apt-cache policy 2>/dev/null \
      | awk '/ubuntu\.com\/ubuntu/ {print $3; exit}' \
      | sed 's/-.*$//')
  fi

  printf '%s\n' "${codename}"
}

# the default channel for the distributions that do not have stable builds, or should not use them,
# this is the same choice as the download page, see "channels" and "discouraged" in docs/_data/downloads.yml
deb_default_repo() {
  if [ -n "${REPO_SET}" ]; then
    return
  fi
  case "$1" in
    bookworm|jammy)
      echo "version 8 requires Python 3.12 or later and will not be available for '$1': using the LTS channel"
      echo "(use REPO=xpra to install the stable channel anyway)"
      REPO="xpra-lts"
      ;;
    bullseye)
      echo "the stable channel is not available for '$1': using the LTS channel"
      REPO="xpra-lts"
      ;;
    forky|sid)
      echo "'$1' has no stable ABI: using the beta channel"
      REPO="xpra-beta"
      ;;
  esac
}

# the repository files are found in ${GITHUB_REPOS}/${DIR}/
# rpmfusion uses "fedora" for Fedora and "el" for RHEL and its clones
dnfinstall() {
  DIR=$1
  RPMFUSION=$2
  echo "adding rpmfusion"
  sudo dnf install -y "https://mirrors.rpmfusion.org/free/${RPMFUSION}/rpmfusion-free-release-${MAJOR_VERSION}.noarch.rpm"
  # alternative:
  # sudo dnf install -y "https://download1.rpmfusion.org/free/${RPMFUSION}/rpmfusion-free-release-${MAJOR_VERSION}.noarch.rpm"
  echo "downloading the repository file"
  download "${GITHUB_REPOS}/${DIR}/${REPO}.repo" "/etc/yum.repos.d/${REPO}.repo"
  echo "installing 'xpra'"
  sudo dnf install -y xpra
  sudo dnf install -y xpra-html5
  # if an older version was installed, upgrade it:
  sudo dnf update -y
}

# RHEL clones: enable 'crb' (called 'powertools' in version 8) and install EPEL
elprepare() {
  if [ "${MAJOR_VERSION}" == "8" ]; then
    sudo dnf config-manager --set-enabled powertools
  else
    sudo dnf config-manager --set-enabled crb
  fi
  sudo dnf install -y epel-release
}

if [ "${ID}" == "fedora" ]; then
  echo "installing 'config-manager' plugin"
  sudo dnf install -y dnf-plugins-core --disablerepo='*' --enablerepo='fedora'
  echo "enabling cisco's openh264"
  sudo dnf-3 config-manager --set-enabled fedora-cisco-openh264
  dnfinstall Fedora fedora
  exit 0
fi
if [ "${ID}" == "rhel" ]; then
  sudo subscription-manager repos --enable "codeready-builder-for-rhel-${MAJOR_VERSION}-$(arch)-rpms"
  sudo dnf install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${MAJOR_VERSION}.noarch.rpm"
  dnfinstall almalinux el
  exit 0
fi
if [ "${ID}" == "centos" ]; then
  # only CentOS Stream is still supported:
  elprepare
  dnfinstall CentOS-Stream el
  exit 0
fi
if [ "${ID}" == "almalinux" ]; then
  elprepare
  dnfinstall almalinux el
  exit 0
fi
if [ "${ID}" == "rocky" ]; then
  elprepare
  dnfinstall rockylinux el
  exit 0
fi
if [ "${ID}" == "ol" ]; then
  sudo dnf config-manager --set-enabled "ol${MAJOR_VERSION}_codeready_builder"
  sudo dnf install -y "oracle-epel-release-el${MAJOR_VERSION}"
  dnfinstall oraclelinux el
  exit 0
fi

############################
# Linux Mint (Ubuntu-based)
############################
if [ "${ID}" == "linuxmint" ]; then
  echo "installing xpra.org gpg key"
  download "https://xpra.org/xpra.asc" "/usr/share/keyrings/xpra.asc"

  echo "determining Ubuntu base codename for Linux Mint"
  VERSION_CODENAME=$(get_ubuntu_codename_from_mint)

  if [ -z "${VERSION_CODENAME}" ]; then
    echo "Linux Mint detected, but unable to determine Ubuntu base codename."
    echo "Checked /etc/apt/sources.list.d/official-package-repositories.list and apt-cache."
    echo "This may be LMDE (Debian-based Mint) or a non-Ubuntu configuration."
    exit 1
  fi

  echo "Linux Mint detected, using Ubuntu codename: ${VERSION_CODENAME}"
  deb_default_repo "${VERSION_CODENAME}"
  echo "installing xpra.org repository file"
  download "${GITHUB_REPOS}/${VERSION_CODENAME}/${REPO}.sources" "/etc/apt/sources.list.d/${REPO}.sources"
  sudo apt-get update
  sudo apt-get install -y xpra
  exit 0
fi

############################
# Debian / Ubuntu
############################
if [ "${ID}" == "debian" ] || [ "${ID}" == "ubuntu" ]; then
  echo "installing xpra.org gpg key"
  download "https://xpra.org/xpra.asc" "/usr/share/keyrings/xpra.asc"
  echo "installing xpra.org repository file"
  VERSION_CODENAME=$(grep -e "^VERSION_CODENAME=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
  deb_default_repo "${VERSION_CODENAME}"
  download "${GITHUB_REPOS}/${VERSION_CODENAME}/${REPO}.sources" "/etc/apt/sources.list.d/${REPO}.sources"
  sudo apt-get update
  sudo apt-get install -y xpra
  sudo apt-get install -y xpra-html5
  exit 0
fi

echo "your distribution is not supported by this script:"
echo " ID=${ID}"
echo " VERSION_ID=${VERSION_ID}"
exit 1
