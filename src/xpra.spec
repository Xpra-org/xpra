#
# rpm spec for xpra
#
%define version 0.0.7.27
%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%define is_suse %(test -e /etc/SuSE-release && echo 1 || echo 0)

%define requires pygtk2, xorg-x11-server-utils, xorg-x11-server-Xvfb
%if %is_suse
%define requires python-gtk, xorg-x11-server, xorg-x11-server-extra, libpng12-0
%endif


Summary: Xpra gives you "persistent remote applications" for X.
Vendor: http://code.google.com/p/partiwm/wiki/xpra
Name: xpra
Version: %{version}
Release: %{build_no}
License: GPL
Requires: %{requires}
Group: Networking
Packager: Antoine Martin <antoine@nagafix.co.uk>
URL: http://xpra.devloop.org.uk/
Source: parti-all-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-root
%if %{defined fedora}
BuildRequires: python, setuptool
%endif

### Patches ###
# if building a generic rpm (without .so) which works as client only
Patch0: disable-posix-server.patch

%description
Xpra gives you "persistent remote applications" for X. That is, unlike normal X applications, applications run with xpra are "persistent" -- you can run them remotely, and they don't die if your connection does. You can detach them, and reattach them later -- even from another computer -- with no loss of state. And unlike VNC or RDP, xpra is for remote applications, not remote desktops -- individual applications show up as individual windows on your screen, managed by your window manager. They're not trapped in a box.

So basically it's screen for remote X apps.


%changelog
* Fri Sep 22 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.27-1
- compatibility fix for python 2.4 (remove "with" statement)
- slow down updates from windows that refresh continuously

* Wed Sep 20 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.26-1
- minor changes to support the Android client (work in progress)
- allow keyboard shortcuts to be specified, default is meta+shift+F4 to quit (disconnects client)
- clear modifiers when applying new keymaps to prevent timeouts
- reduce context switching in the network read loop code
- try harder to close connections cleanly
- removed some unused code, fixed some old test code

* Wed Aug 31 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.25-1
- Use xmodmap to grab the exact keymap, this should ensure all keys are mapped correctly
- Reset modifiers whenever we gain or lose focus, or when the keymap changes

* Mon Aug 15 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.24-1
- Use raw keycodes whenever possible, should fix keymapping issues for all Unix-like clients
- Keyboard fixes for AltGr and special keys for non Unix-like clients

* Fri Jul 27 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.23-1
- More keymap fixes..

* Wed Jul 20 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.23-1
- Try to use setxkbmap before xkbcomp to setup the matching keyboard layout
- Handle keyval level (shifted keys) explicitly, should fix missing key mappings
- More generic option for setting window titles
- Exit if the server dies

* Thu Jun 02 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.22-1
- minor fixes: jpeg, man page, etc

* Fri May 20 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.21-1
- ability to bind to an existing display with --use-display
- --xvfb now specifies the full command used. The default is unchanged
- --auto-refresh-delay does automatic refresh of idle displays in a lossless fashion

* Wed May 04 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.20-1
- more reliable fix for keyboard mapping issues

* Mon Apr 25 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.19-1
- xrandr support when running against Xdummy, screen resizes on demand
- fixes for keyboard mapping issues: multiple keycodes for the same key

* Mon Apr 4 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.18-2
- Fix for older distros (like CentOS) with old versions of pycairo

* Sat Mar 28 2011 Antoine Martin <antoine@nagafix.co.uk> 0.0.7.18-1
- Fix jpeg compression on MS Windows
- Add ability to disable clipboard code
- Updated man page

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
%if %{defined generic_rpm}
cd parti-all-%{version}
%patch0 -p0
%endif

%build
cd parti-all-%{version}
./do-rpm-build

%install
rm -rf $RPM_BUILD_ROOT
cd parti-all-%{version}
%{__python} setup.py install -O1  --prefix /usr --skip-build --root %{buildroot}
%if %{defined generic_rpm}
# remove .so (not suitable for a generic RPM)
rm -f "${RPM_BUILD_ROOT}/usr/lib/python2.6/site-packages/wimpiggy/bindings.so"
rm -f "${RPM_BUILD_ROOT}/usr/lib/python2.6/site-packages/xpra/wait_for_x_server.so"
%else
%ifarch x86_64
mv -f "${RPM_BUILD_ROOT}/usr/lib64" "${RPM_BUILD_ROOT}/usr/lib"
%endif
%endif

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%{_bindir}/parti
%{_bindir}/parti-repl
%{_bindir}/xpra
%{python_sitelib}/xpra
%{python_sitelib}/parti
%{python_sitelib}/wimpiggy
%if %{defined include_egg}
%{python_sitelib}/parti_all-*.egg-info
%endif
/usr/share/man/man1/xpra.1*


###
### eof
###
