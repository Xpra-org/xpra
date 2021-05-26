%define _disable_source_fetch 0

Name:           python2-pyxdg
Version:        0.27
Release:        1%{?dist}
Summary:		Python2 library to access freedesktop.org standards
License:        LGPLv2
URL:            http://freedesktop.org/Software/pyxdg
Source0:        https://files.pythonhosted.org/packages/6f/2e/2251b5ae2f003d865beef79c8fcd517e907ed6a69f58c32403cec3eba9b2/pyxdg-%{version}.tar.gz
# https://gitlab.freedesktop.org/xdg/pyxdg/merge_requests/2
BuildArch:      noarch
BuildRequires:	hicolor-icon-theme
BuildRequires:	shared-mime-info
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools
%{?python_provide:%python_provide python2-pyxdg}
Provides:       pyxdg = %{version}-%{release}
Obsoletes:      pyxdg < 0.25-10

%description
PyXDG is a python library to access freedesktop.org standards. This
package contains a Python 2 version of PyXDG.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "80bd93aae5ed82435f20462ea0208fb198d8eec262e831ee06ce9ddb6b91c5a5" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n pyxdg-%{version}

%build
%{__python2} setup.py build

%install
%{__python2} setup.py install --skip-build --root %{buildroot}

%files
%license COPYING
%doc AUTHORS ChangeLog README TODO
%{python2_sitelib}/xdg
%{python2_sitelib}/pyxdg-*.egg-info

%changelog
* Tue May 25 2021 Antoine Martin <antoine@nagafix.co.uk> - 0.27-1
- new upstream release

* Fri Sep 27 2019 Antoine Martin <antoine@nagafix.co.uk> - 0.26-4
- adapt spec file to build only for python2

* Sat Feb 02 2019 Fedora Release Engineering <releng@fedoraproject.org> - 0.26-5
- Rebuilt for https://fedoraproject.org/wiki/Fedora_30_Mass_Rebuild

* Fri Nov 30 2018 Tom Callaway <spot@fedoraproject.org> - 0.26-3
- fix incorrect use of Type attribute (bz 1654857)

* Thu Nov  1 2018 Tom Callaway <spot@fedoraproject.org> - 0.26-2
- fix OnlyShowIn (bz 1624651)

* Mon Jul 23 2018 Tom Callaway <spot@fedoraproject.org> - 0.26-1
- update to 0.26

* Sat Jul 14 2018 Fedora Release Engineering <releng@fedoraproject.org> - 0.25-17
- Rebuilt for https://fedoraproject.org/wiki/Fedora_29_Mass_Rebuild

* Mon Jun 18 2018 Miro Hrončok <mhroncok@redhat.com> - 0.25-16
- Rebuilt for Python 3.7

* Fri Feb 09 2018 Fedora Release Engineering <releng@fedoraproject.org> - 0.25-15
- Rebuilt for https://fedoraproject.org/wiki/Fedora_28_Mass_Rebuild

* Wed Jan 31 2018 Iryna Shcherbina <ishcherb@redhat.com> - 0.25-14
- Update Python 2 dependency declarations to new packaging standards
  (See https://fedoraproject.org/wiki/FinalizingFedoraSwitchtoPython3)

* Thu Jul 27 2017 Fedora Release Engineering <releng@fedoraproject.org> - 0.25-13
- Rebuilt for https://fedoraproject.org/wiki/Fedora_27_Mass_Rebuild

* Sat Feb 11 2017 Fedora Release Engineering <releng@fedoraproject.org> - 0.25-12
- Rebuilt for https://fedoraproject.org/wiki/Fedora_26_Mass_Rebuild

* Mon Dec 12 2016 Charalampos Stratakis <cstratak@redhat.com> - 0.25-11
- Rebuild for Python 3.6

* Mon Nov 21 2016 Orion Poplawski <orion@cora.nwra.com> - 0.25-10
- Ship python2-pyxdg
- Enable python 3 builds for EPEL
- Use %%license
- Modernize spec

* Tue Jul 19 2016 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.25-9
- https://fedoraproject.org/wiki/Changes/Automatic_Provides_for_Python_RPM_Packages

* Thu Feb 04 2016 Fedora Release Engineering <releng@fedoraproject.org> - 0.25-8
- Rebuilt for https://fedoraproject.org/wiki/Fedora_24_Mass_Rebuild

* Tue Nov 10 2015 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.25-7
- Rebuilt for https://fedoraproject.org/wiki/Changes/python3.5

* Thu Jun 18 2015 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.25-6
- Rebuilt for https://fedoraproject.org/wiki/Fedora_23_Mass_Rebuild

* Thu Dec  4 2014 Tom Callaway <spot@fedoraproject.org> - 0.25-5
- fix CVE-2014-1624

* Sun Jun 08 2014 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.25-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_21_Mass_Rebuild

* Tue May 27 2014 Kalev Lember <kalevlember@gmail.com> - 0.25-3
- Rebuilt for https://fedoraproject.org/wiki/Changes/Python_3.4

* Sun Aug 04 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.25-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_20_Mass_Rebuild

* Thu Feb 28 2013 Tom Callaway <spot@fedoraproject.org> - 0.25-1
- update to 0.25

* Thu Feb 14 2013 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.24-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_19_Mass_Rebuild

* Wed Nov  7 2012 Tomas Bzatek <tbzatek@redhat.com> - 0.24-1
- update to 0.24

* Fri Oct 26 2012 Tom Callaway <spot@fedoraproject.org> - 0.23-2
- gracefully handle kde-config fails

* Mon Oct  8 2012 Tom Callaway <spot@fedoraproject.org> - 0.23-1
- update to 0.23
- enable python3

* Sat Jul 21 2012 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.19-5
- Rebuilt for https://fedoraproject.org/wiki/Fedora_18_Mass_Rebuild

* Sat Jan 14 2012 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.19-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_17_Mass_Rebuild

* Wed Feb 09 2011 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.19-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_15_Mass_Rebuild

* Thu Jul 22 2010 David Malcolm <dmalcolm@redhat.com> - 0.19-2
- Rebuilt for https://fedoraproject.org/wiki/Features/Python_2.7/MassRebuild

* Wed Apr 28 2010 Tom "spot" Callaway <tcallawa@redhat.com> - 0.19-1
- update to 0.19

* Wed Aug 19 2009 Tom "spot" Callaway <tcallawa@redhat.com> - 0.17-1
- update to 0.17

* Sun Jul 26 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.16-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_12_Mass_Rebuild

* Thu Feb 26 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.16-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_11_Mass_Rebuild

* Sat Nov 29 2008 Ignacio Vazquez-Abrams <ivazqueznet+rpm@gmail.com> - 0.16-2
- Rebuild for Python 2.6

* Thu Oct 30 2008 Tom "spot" Callaway <tcallawa@redhat.com> - 0.16-1
- update to 0.16
- fix indent bug in DesktopEntry.py (bz 469229)

* Sat Apr  5 2008 Tom "spot" Callaway <tcallawa@redhat.com> - 0.15-6
- add egg-info (fixes FTBFS bz 440813)

* Wed Jan  3 2007 Patrice Dumas <pertusus@free.fr> - 0.15-5
- remove requires for python-abi (automatic now) and python directory
- remove package name from summary
- change tabs to spaces

* Thu Dec 21 2006 Patrice Dumas <pertusus@free.fr> - 0.15-4
- rebuild for python 2.5

* Sat Sep 23 2006 Tom "spot" Callaway <tcallawa@redhat.com> - 0.15-3
- rebuild for fc6

* Wed Feb 15 2006 John Mahowald <jpmahowald@gmail.com> - 0.15.2
- Rebuild for Fedora Extras 5

* Fri Oct 14 2005 John Mahowald <jpmahowald@gmail.com> - 0.15-1
- Rebuilt for 0.15

* Sun Jul 03 2005 Sindre Pedersen Bjordal <foolish[AT]fedoraforum.org> - 0.14-2
- Added %%{?dist} tag to release
- BuildArch: noarch
- Removed unneccesary CLFAGS

* Sun Jun 05 2005 Sindre Pedersen Bjordal <foolish[AT]fedoraforum.org> - 0.14-1
- Rebuilt for 0.14

* Wed Jun 01 2005 Sindre Pedersen Bjordal <foolish[AT]fedoraforum.org> - 0.13-1
- Rebuilt for 0.13

* Tue May 31 2005 Sindre Pedersen Bjordal <foolish[AT]fedoraforum.org> - 0.12-1
- Rebuilt for 0.12

* Sat May 28 2005 Sindre Pedersen Bjordal <foolish[AT]fedoraforum.org> - 0.11-1
- Rebuilt for 0.11

* Mon May 23 2005 Sindre Pedersen Bjordal <foolish[AT]fedoraforum.org> - 0.10-1
- Adapt to Fedora Extras template, based on spec from NewRPMs

* Tue Dec 14 2004 Che
- initial rpm release
