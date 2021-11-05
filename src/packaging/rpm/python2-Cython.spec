%{!?__python2: %global __python2 python2}
%{!?python2_sitearch: %global python2_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}

%define _disable_source_fetch 0

Name:		python2-Cython
Version:	0.29.24
Release:	1%{?dist}
Summary:	A language for writing Python extension modules
Group:		Development/Tools
License:	Python
URL:		http://www.cython.org
Source0:    https://files.pythonhosted.org/packages/59/e3/78c921adf4423fff68da327cc91b73a16c63f29752efe7beb6b88b6dd79d/Cython-%{version}.tar.gz
BuildRoot:	%{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Requires:   python2

BuildRequires:	python2-devel python2-setuptools

%description
This is a development version of Pyrex, a language
for writing Python extension modules.

%prep
sha256=`sha256sum %{SOURCE0} | awk '{print $1}'`
if [ "${sha256}" != "cdf04d07c3600860e8c2ebaad4e8f52ac3feb212453c1764a49ac08c827e8443" ]; then
	echo "invalid checksum for %{SOURCE0}"
	exit 1
fi
%setup -q -n Cython-%{version}
find -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python2}|'

%build
CFLAGS="$RPM_OPT_FLAGS" %{__python2} setup.py build

%install
rm -rf %{buildroot}
%{__python2} setup.py install -O1 --skip-build --root %{buildroot}
rm -rf %{buildroot}%{python2_sitelib}/setuptools/tests
#rename the binaries to avoid conflicting with the ones
#from the newer python3-Cython packages
pushd "%{buildroot}/usr/bin/"
for x in cygdb cython cythonize; do
	mv $x python2-$x;
done
popd

%clean
rm -rf %{buildroot}

##%%check
##%%{__python2} runtests.py -x numpy

%files
%defattr(-,root,root,-)
%{python2_sitearch}/*
%{_bindir}/python2-cy*
%doc *.txt Demos Tools

%changelog
* Thu Nov 04 2021 Antoine Martin <antoine@xpra.org> 0.29.24-1
- CentOS Stream 9 (temporary?) replacement package

* Tue May 25 2021 Antoine Martin <antoine@xpra.org> 0.29.23-1
- new upstream release

* Wed Feb 17 2021 Antoine Martin <antoine@xpra.org> 0.29.21-3
- verify source checksum

* Sun Jan 03 2021 Antoine Martin <antoine@xpra.org> - 0.29.21-2
- make it installable together with newer python3-Cython packages

* Tue Nov 17 2020 Antoine Martin <antoine@xpra.org> - 0.29.21-1
- new upstream release

* Fri Jun 19 2020 Antoine Martin <antoine@xpra.org> - 0.29.20-1
- new upstream release

* Fri Sep 27 2019 Antoine Martin <antoine@xpra.org> - 0.29.13-1
- new upstream release

* Mon Apr 15 2019 Antoine Martin <antoine@xpra.org> - 0.29.7-1
- new upstream release

* Mon Mar 04 2019 Antoine Martin <antoine@xpra.org> - 0.29.6-1
- new upstream release

* Sat Feb 09 2019 Antoine Martin <antoine@xpra.org> - 0.29.5-1
- new upstream release

* Thu Jan 24 2019 Antoine Martin <antoine@xpra.org> - 0.29.3-1
- new upstream release

* Thu Jan 10 2019 Antoine Martin <antoine@xpra.org> - 0.29.2-1
- new upstream release

* Wed Nov 28 2018 Antoine Martin <antoine@xpra.org> - 0.29.1-1
- new upstream release

* Sun Oct 14 2018 Antoine Martin <antoine@xpra.org> - 0.29-1
- new upstream release

* Fri Aug 03 2018 Antoine Martin <antoine@xpra.org> - 0.28.5-1
- new upstream release

* Fri Aug 03 2018 Antoine Martin <antoine@xpra.org> - 0.28.4-1
- new upstream release

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 0.28.3-3
- use python2 explicitly

* Tue Jul 03 2018 Antoine Martin <antoine@xpra.org> - 0.28.3-2
- try harder to prevent rpm db conflicts

* Wed May 30 2018 Antoine Martin <antoine@xpra.org> - 0.28.3-1
- new upstream release

* Mon Mar 19 2018 Antoine Martin <antoine@xpra.org> - 0.28.1-1
- new upstream release

* Wed Mar 14 2018 Antoine Martin <antoine@xpra.org> - 0.28-1
- new upstream release

* Thu Nov 09 2017 Antoine Martin <antoine@xpra.org> - 0.27.3-1
- new upstream release

* Mon Oct 23 2017 Antoine Martin <antoine@xpra.org> - 0.27.2-1
- new upstream release

* Mon Oct 02 2017 Antoine Martin <antoine@xpra.org> - 0.27.1-1
- new upstream release

* Sat Sep 23 2017 Antoine Martin <antoine@xpra.org> - 0.27-1
- new upstream release

* Wed Aug 30 2017 Antoine Martin <antoine@xpra.org> - 0.26.1-1
- new upstream release

* Thu Jul 20 2017 Antoine Martin <antoine@xpra.org> - 0.26-1
- new upstream release

* Wed Jul 19 2017 Antoine Martin <antoine@xpra.org> - 0.26-0rc2
- new release candidate

* Sat Jul 15 2017 Antoine Martin <antoine@xpra.org> - 0.26-0rc0
- release candidate

* Tue Jul 11 2017 Antoine Martin <antoine@xpra.org> - 0.26-0b2p1
- add fallthrough fix

* Tue Jul 11 2017 Antoine Martin <antoine@xpra.org> - 0.26-0b2
- new beta release

* Tue Jul 04 2017 Antoine Martin <antoine@xpra.org> - 0.26-0b0
- new beta release

* Sun Dec 25 2016 Antoine Martin <antoine@xpra.org> - 0.25.2-2
- add provides for python2 package naming

* Fri Dec 09 2016 Antoine Martin <antoine@xpra.org> - 0.25.2-1
- new upstream release

* Fri Nov 04 2016 Antoine Martin <antoine@xpra.org> - 0.25.1-1
- new upstream release

* Wed Oct 26 2016 Antoine Martin <antoine@xpra.org> - 0.25-1
- new upstream release

* Fri Jul 15 2016 Antoine Martin <antoine@xpra.org> - 0.24.1-1
- new upstream release

* Tue Apr 05 2016 Antoine Martin <antoine@xpra.org> - 0.24-1
- new upstream release

* Sat Mar 26 2016 Antoine Martin <antoine@xpra.org> - 0.23.5-1
- new upstream release

* Sun Oct 11 2015 Antoine Martin <antoine@xpra.org> - 0.23.4-1
- new upstream release

* Tue Sep 29 2015 Antoine Martin <antoine@xpra.org> - 0.23.3-1
- new upstream release

* Fri Sep 11 2015 Antoine Martin <antoine@xpra.org> - 0.23.2-1
- new upstream release

* Sun Aug 23 2015 Antoine Martin <antoine@xpra.org> - 0.23.1-2
- build python3 package

* Sun Aug 23 2015 Antoine Martin <antoine@xpra.org> - 0.23.1-1
- new upstream release

* Wed Aug 19 2015 Antoine Martin <antoine@xpra.org> - 0.23-2
- add upstream patch for infinite deepcopy loop

* Sun Aug 09 2015 Antoine Martin <antoine@xpra.org> - 0.23-1
- new upstream release

* Mon Jun 22 2015 Antoine Martin <antoine@xpra.org> - 0.22.1-1
- Crash when returning values on generator termination.
- In some cases, exceptions raised during internal isinstance() checks were not propagated.
- Runtime reported file paths of source files (e.g for profiling and tracing) are now relative to the build root directory instead of the main source file.
- Tracing exception handling code could enter the trace function with an active exception set.
- The internal generator function type was not shared across modules.
- Comparisons of (inferred) ctuples failed to compile.
- Closures inside of cdef functions returning void failed to compile.
- Using const C++ references in intermediate parts of longer expressions could fail to compile.
- C++ exception declarations with mapping functions could fail to compile when pre-declared in .pxd files.
- C++ compilation could fail with an ambiguity error in recent MacOS-X Xcode versions.
- C compilation could fail in pypy3.
- Fixed a memory leak in the compiler when compiling multiple modules.
- When compiling multiple modules, external library dependencies could leak into later compiler runs. Fix by Jeroen Demeyer. This fixes ticket 845.

* Thu Feb 12 2015 Antoine Martin <antoine@xpra.org> - 0.22-1
- new upstream release

* Thu Jan 22 2015 Antoine Martin <antoine@xpra.org> - 0.22.beta0-0
- new beta

* Sun Dec 28 2014 Antoine Martin <antoine@xpra.org> - 0.21.2-1
- new upstream release

* Sun Oct 19 2014 Antoine Martin <antoine@xpra.org> - 0.21.1-1
- Update to 0.21.1

* Thu Sep 11 2014 Antoine Martin <antoine@xpra.org> - 0.21-1
- Update to 0.21

* Thu Jul 31 2014 Antoine Martin <antoine@xpra.org> - 0.20.2-2
- Removed EPEL bits that get in the way, fix (guess) date in changelog

* Tue Jun 17 2014 Matthew Gyurgyik <pyther@pyther.net> - 0.20.2-1
- Updated to 0.20.2

* Fri Jun 13 2014 Matthew Gyurgyik <pyther@pyther.net> - 0.20.1-1
- Updated to 0.20.1

* Tue Apr 03 2012 Steve Traylen <steve.traylen@cern.ch> - 0.14.1-3
- Adapt SPEC file for python3 and python26 on EPEL5.

* Mon Feb 07 2011 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.14.1-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_15_Mass_Rebuild

* Sat Feb  5 2011 Neal Becker <ndbecker2@gmail.com> - 0.14.1-1
- Update to 0.14.1

* Wed Dec 15 2010 Neal Becker <ndbecker2@gmail.com> - 0.14-2
- Add cygdb

* Wed Dec 15 2010 Neal Becker <ndbecker2@gmail.com> - 0.14-1
- Update to 0.14

* Wed Aug 25 2010 Neal Becker <ndbecker2@gmail.com> - 0.13-1
- Update to 0.13

* Wed Jul 21 2010 David Malcolm <dmalcolm@redhat.com> - 0.12.1-5
- Rebuilt for https://fedoraproject.org/wiki/Features/Python_2.7/MassRebuild

* Fri Feb  5 2010 Neal Becker <ndbecker2@gmail.com> - 0.12.1-4
- Disable check for now as it fails on PPC

* Tue Feb  2 2010 Neal Becker <ndbecker2@gmail.com> - 0.12.1-2
- typo
- stupid rpm comments

* Mon Nov 23 2009 Neal Becker <ndbecker2@gmail.com> - 0.12-1.rc1
- Make that 0.12

* Mon Nov 23 2009 Neal Becker <ndbecker2@gmail.com> - 0.12.1-1.rc1
- Update to 0.12.1

* Sun Sep 27 2009 Neal Becker <ndbecker2@gmail.com> - 0.11.3-1.rc1
- Update to 0.11.3rc1
- Update to 0.11.3

* Fri Jul 24 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.11.2-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_12_Mass_Rebuild

* Wed May 20 2009 Neal Becker <ndbecker2@gmail.com> - 0.11.2-1
- Update to 0.11.2

* Thu Apr 16 2009 Neal Becker <ndbecker2@gmail.com> - 0.11.1-1
- Update to 0.11.1

* Sat Mar 14 2009 Neal Becker <ndbecker2@gmail.com> - 0.11-2
- Missed cython.py*

* Sat Mar 14 2009 Neal Becker <ndbecker2@gmail.com> - 0.11-1
- Update to 0.11
- Exclude numpy from tests so we don't have to BR it

* Mon Feb 23 2009 Fedora Release Engineering <rel-eng@lists.fedoraproject.org> - 0.10.3-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_11_Mass_Rebuild

* Wed Dec 17 2008 Neal Becker <ndbecker2@gmail.com> - 0.10.3-1
- Update to 0.10.3

* Thu Dec 04 2008 Ignacio Vazquez-Abrams <ivazqueznet+rpm@gmail.com> - 0.10.2-2
- Rebuild for Python 2.6

* Mon Dec  1 2008 Neal Becker <ndbecker2@gmail.com> - 0.10.2-1
- Update to 0.10.2

* Sat Nov 29 2008 Ignacio Vazquez-Abrams <ivazqueznet+rpm@gmail.com> - 0.10.1-2
- Rebuild for Python 2.6

* Wed Nov 19 2008 Neal Becker <ndbecker2@gmail.com> - 0.10.1-1
- Update to 0.10.1

* Sun Nov  9 2008 Neal Becker <ndbecker2@gmail.com> - 0.10-3
- Fix typo

* Sun Nov  9 2008 Neal Becker <ndbecker2@gmail.com> - 0.10-1
- Update to 0.10

* Fri Jun 13 2008 Neal Becker <ndbecker2@gmail.com> - 0.9.8-2
- Install into python_sitearch
- Add %%check

* Fri Jun 13 2008 Neal Becker <ndbecker2@gmail.com> - 0.9.8-1
- Update to 0.9.8

* Mon Apr 14 2008 José Matos <jamatos[AT]fc.up.pt> - 0.9.6.13.1-3
- Remove remaining --record.
- Add more documentation (Doc and Tools).
- Add correct entry for egg-info (F9+).

* Mon Apr 14 2008 Neal Becker <ndbecker2@gmail.com> - 0.9.6.13.1-2
- Change License to Python
- Install About.html
- Fix mixed spaces/tabs
- Don't use --record

* Tue Apr  8 2008 Neal Becker <ndbecker2@gmail.com> - 0.9.6.13.1-1
- Update to 0.9.6.13.1

* Mon Apr  7 2008 Neal Becker <ndbecker2@gmail.com> - 0.9.6.13-1
- Update to 0.9.6.13
- Add docs

* Tue Feb 26 2008 Neal Becker <ndbecker2@gmail.com> - 0.9.6.12-1
- Initial version
