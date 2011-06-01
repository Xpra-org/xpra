#
# rpm spec for xpra
#
%define version 0.0.7.17
%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}


Summary: Xpra gives you "persistent remote applications" for X.
Vendor: http://code.google.com/p/partiwm/wiki/xpra
Name: xpra
Version: %{version}
Release: 1
License: GPL
Requires: pygtk2, xorg-x11-server-utils, xorg-x11-server-Xvfb
Group: Networking
Packager: Antoine Martin <antoine@nagafix.co.uk>
URL: http://xpra.devloop.org.uk/
Source: parti-all-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-root
%if %{defined fedora}
BuildRequires: python, setuptool, Pyrex
%endif

%description
Xpra gives you "persistent remote applications" for X. That is, unlike normal X applications, applications run with xpra are "persistent" -- you can run them remotely, and they don't die if your connection does. You can detach them, and reattach them later -- even from another computer -- with no loss of state. And unlike VNC or RDP, xpra is for remote applications, not remote desktops -- individual applications show up as individual windows on your screen, managed by your window manager. They're not trapped in a box.

So basically it's screen for remote X apps.


%changelog
* Wed Jan 19 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.17-1
- Honour the pulseaudio flag on client

* Thu Aug 25 2010 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.16-1
- Merged upstream changes.

* Thu Jul 01 2010 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.15-1
- Add option to disable Pulseaudio forwarding as this can be a real network hog.
- Use logging rather than print statements.

* Mon May 04 2010 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.13-1
- Ignore minor version differences in the future (must bump to 0.0.8 to cause incompatibility error)

* Tue Apr 13 2010 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.12-1
- bump screen resolution

* Sun Jan 11 2010 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.11-1
- first rpm spec file

%prep
rm -rf $RPM_BUILD_DIR/parti-all-%{version}
zcat $RPM_SOURCE_DIR/parti-all-%{version}.tar.gz | tar -xvf -

%build
cd parti-all-%{version}
./do-rpm-build
 
%install
rm -rf $RPM_BUILD_ROOT
cd parti-all-%{version}
%{__python} setup.py install -O1  --prefix /usr --skip-build --root %{buildroot}
%ifarch x86_64
mv -f "${RPM_BUILD_ROOT}/usr/lib64" "${RPM_BUILD_ROOT}/usr/lib"
%endif
%if %{undefined fedora}
# remove .so (not suitable for a generic RPM)
rm -f "${RPM_BUILD_ROOT}/usr/lib/python2.6/site-packages/wimpiggy/bindings.so"
rm -f "${RPM_BUILD_ROOT}/usr/lib/python2.6/site-packages/xpra/wait_for_x_server.so"
%endif

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%{_bindir}/parti
%{_bindir}/parti-repl
%{_bindir}/xpra
%if %{defined CentOS}
/usr/lib/python2.4/site-packages/xpra
/usr/lib/python2.4/site-packages/parti
/usr/lib/python2.4/site-packages/wimpiggy
%else
%if %{defined fedora}
%{python_sitelib}/xpra
%{python_sitelib}/parti
%{python_sitelib}/wimpiggy
%{python_sitelib}/parti_all-*.egg-info
%else
/usr/lib/python2.6/site-packages/xpra
/usr/lib/python2.6/site-packages/parti
/usr/lib/python2.6/site-packages/wimpiggy
/usr/lib/python2.6/site-packages/parti_all-*.egg-info
%endif
%endif
/usr/share/man/man1/xpra.1*


###
### eof
###
