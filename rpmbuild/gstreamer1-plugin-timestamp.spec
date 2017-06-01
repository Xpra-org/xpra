Summary: GStreamer plugin for extracting monotonic timestamps
Name: gstreamer1-plugin-timestamp
Version: 0.1.0
Release: 1%{?dist}
License: LGPL
Group: Applications/Multimedia

Source: http://xpra.org/src/gst-plugin-timestamp-%{version}.tar.xz
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root

BuildRequires: gstreamer1-devel
BuildRequires: gstreamer1-plugins-base-devel
Requires: gstreamer1

BuildRequires: gcc

%description
This GStreamer plugin allows xpra to extract monotonic timestamps from the sound buffers.

%prep
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
* Thu Jun 01 2017 Antoine Martin <antoine@devloop.org.uk> 0.1.0-1
- Initial packaging
