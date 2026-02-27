#!/bin/bash

# other options: "xpra-lts" and "xpra-beta"
REPO="xpra"
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

dnfinstall() {
  DISTRO=$1
  distro=${DISTRO,,}
  echo "adding rpmfusion"
  sudo dnf install -y "https://mirrors.rpmfusion.org/free/${distro}/rpmfusion-free-release-${MAJOR_VERSION}.noarch.rpm"
  # alternative:
  # sudo dnf install -y "https://download1.rpmfusion.org/free/${distro}/rpmfusion-free-release-${MAJOR_VERSION}.noarch.rpm"
  echo "downloading the repository file"
  sudo curl -o "/etc/yum.repos.d/${REPO}.repo" "${GITHUB_REPOS}/$DISTRO/${REPO}.repo"
  echo "installing 'xpra'"
  sudo dnf install -y xpra
  sudo dnf install -y xpra-html5
  # if an older version was installed, upgrade it:
  sudo dnf update -y
}

if [ "${ID}" == "fedora" ]; then
  echo "installing 'config-manager' plugin"
  sudo dnf install -y dnf-plugins-core --disablerepo='*' --enablerepo='fedora'
  echo "enabling cisco's openh264"
  sudo dnf-3 config-manager --set-enabled fedora-cisco-openh264
  dnfinstall Fedora
  exit 0
fi
if [ "${ID}" == "rhel" ]; then
  sudo dnf config-manager --set-enabled crb
  sudo dnf config-manager --set-enabled epel-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall AlmaLinux
  exit 0
fi
if [ "${ID}" == "centos" ]; then
  sudo dnf config-manager --set-enabled epel-next-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall CentOS
  exit 0
fi
if [ "${ID}" == "almalinux" ]; then
  sudo dnf config-manager --set-enabled crb
  sudo dnf config-manager --set-enabled epel-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall AlmaLinux
  exit 0
fi
if [ "${ID}" == "rockylinux" ]; then
  sudo dnf config-manager --set-enabled crb
  sudo dnf config-manager --set-enabled epel-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall RockyLinux
  exit 0
fi
if [ "${ID}" == "oraclelinux" ]; then
  sudo dnf config-manager --set-enabled "ol${VERSION_ID}_codeready_builder"
  sudo dnf config-manager --set-enabled epel-release
  sudo dnf config-manager --set-enabled powertools
  dnfinstall OracleLinux
  exit 0
fi

############################
# Linux Mint (Ubuntu-based)
############################
if [ "${ID}" == "linuxmint" ]; then
  echo "installing xpra.org gpg key"
  sudo curl -o "/usr/share/keyrings/xpra.asc" "https://xpra.org/xpra.asc"

  echo "determining Ubuntu base codename for Linux Mint"
  VERSION_CODENAME=$(get_ubuntu_codename_from_mint)

  if [ -z "${VERSION_CODENAME}" ]; then
    echo "Linux Mint detected, but unable to determine Ubuntu base codename."
    echo "Checked /etc/apt/sources.list.d/official-package-repositories.list and apt-cache."
    echo "This may be LMDE (Debian-based Mint) or a non-Ubuntu configuration."
    exit 1
  fi

  echo "Linux Mint detected, using Ubuntu codename: ${VERSION_CODENAME}"
  echo "installing xpra.org repository file"
  sudo curl -o "/etc/apt/sources.list.d/${REPO}.sources" "${GITHUB_REPOS}/${VERSION_CODENAME}/${REPO}.sources"
  sudo apt-get update
  sudo apt-get install -y xpra
  exit 0
fi

############################
# Debian / Ubuntu
############################
if [ "${ID}" == "debian" ] || [ "${ID}" == "ubuntu" ]; then
  echo "installing xpra.org gpg key"
  sudo curl -o "/usr/share/keyrings/xpra.asc" "https://xpra.org/xpra.asc"
  echo "installing xpra.org repository file"
  VERSION_CODENAME=$(grep -e "^VERSION_CODENAME=" /etc/os-release | awk -F= '{print $2}' | sed 's/"//g')
  sudo curl -o "/etc/apt/sources.list.d/${REPO}.sources" "${GITHUB_REPOS}/${VERSION_CODENAME}/${REPO}.sources"
  sudo apt-get update
  sudo apt-get install -y xpra
  sudo apt-get install -y xpra-html5
  exit 0
fi

echo "your distribution is not supported by this script:"
echo " ID=${ID}"
echo " VERSION_ID=${VERSION_ID}"
exit 1
