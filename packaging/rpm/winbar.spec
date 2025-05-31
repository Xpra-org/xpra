%define _disable_source_fetch 0
%define commit 3490cca97d3e5305b58f13aef42bd3b2b64f4be6

Name:           winbar
Version:        0.2
Release:        1
Summary:        A familiar X11 panel/dock to ease new linux users transition
License:        GPL-3
URL:            https://github.com/jmanc3/winbar
Source0:        https://github.com/jmanc3/winbar/archive/%{commit}.zip

BuildRequires:  git
BuildRequires:  cmake
BuildRequires:  g++
BuildRequires:  cairo-devel
BuildRequires:  pango-devel
BuildRequires:  librsvg2-devel
BuildRequires:  xcb-util-devel
BuildRequires:  pulseaudio-libs-devel
BuildRequires:  xcb-util-wm-devel
BuildRequires:  libxkbcommon-x11-devel
BuildRequires:  libconfig-devel
BuildRequires:  xcb-util-cursor-devel
BuildRequires:  dbus-devel
BuildRequires:  fontconfig-devel
BuildRequires:  xcb-util-keysyms-devel
BuildRequires:  libXi-devel
BuildRequires:  alsa-lib-devel
BuildRequires:  glm-devel
BuildRequires:  glew-devel

%description
A familiar X11 panel/dock to ease new linux users transition


%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "4f51d3b9c86fed794affbbdf2a277f46170667059cfccd5251619b4ef52df94e" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n %{name}-%{commit}

%build
mkdir -p build
cd build
%cmake -DCMAKE_BUILD_TYPE=Release ../
pushd %{__cmake_builddir}
make
popd
# unzip assets
unzip ../winbar.zip

%install
mkdir -p %{buildroot}%{_sysconfdir} %{buildroot}%{_bindir} %{buildroot}%{_datadir}/winbar >& /dev/null
cd build
pushd %{__cmake_builddir}
cp ./winbar %{buildroot}%{_bindir}
popd
cp -R ./winbar/fonts ./winbar/resources ./winbar/plugins ./winbar/tofix.csv ./winbar/items_custom.ini %{buildroot}%{_datadir}/winbar
cp ./winbar/winbar.cfg %{buildroot}%{_sysconfdir}

%files
%license LICENSE.md
%doc README.md
%{_bindir}/winbar
%{_datadir}/winbar
%{_sysconfdir}/winbar.cfg

%changelog
* Thu May 29 2025 Antoine Martin <antoine@xpra.org> - 0.2-1
- new snapshot

* Sun May 18 2025 Antoine Martin <antoine@xpra.org> - 0.1-1
- initial packaging for xpra