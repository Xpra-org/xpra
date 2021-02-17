#
# spec file for our timestamp insertion element
#
# Copyright (c) 2021 Antoine Martin <antoine@xpra.org>
#

%define _disable_source_fetch 0

Summary: GStreamer plugin for extracting monotonic timestamps
Name: gstreamer1-plugin-timestamp
Version: 0.1.0
Release: 2%{?dist}
License: LGPL
Group: Applications/Multimedia

Source0: https://xpra.org/src/gst-plugin-timestamp-%{version}.tar.xz
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root

BuildRequires: gstreamer1-devel
BuildRequires: gstreamer1-plugins-base-devel
Requires: gstreamer1

BuildRequires: gcc

%global debug_package %{nil}

%description
This GStreamer plugin allows xpra to extract monotonic timestamps from the sound buffers.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "02f1226a930a19a8bfdbedd1fc57c53ad9bdbf708c6694c0c662d1b5c198d972" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi 
%setup -n gst-plugin-timestamp-%{version}

%build
gcc -I. `pkg-config --cflags gstreamer-1.0` \
    -Wall -fPIC -DPIC -O2 -c gsttimestamp.c -o gsttimestamp.o
gcc -shared -fPIC -DPIC `pkg-config --libs gstreamer-1.0` \
	-Wl,-soname -Wl,libgsttimestamp.so gsttimestamp.o -o libgsttimestamp.so

%install
mkdir -p %{buildroot}%{_libdir}/gstreamer-1.0/
cp libgsttimestamp.so %{buildroot}%{_libdir}/gstreamer-1.0/

%clean
%{__rm} -rf %{buildroot}

%files
%defattr(-,root,root,-)
%{_libdir}/gstreamer-1.0/libgsttimestamp.so

%changelog
* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> 0.1.0-2
- verify source checksum

* Thu Jun 01 2017 Antoine Martin <antoine@xpra.org> 0.1.0-1
- Initial packaging
