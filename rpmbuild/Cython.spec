%{!?__python2: %global __python2 python2}
%{!?__python3: %define __python3 python3}
%{!?python_sitearch: %global python_sitearch %(%{__python2} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib(1))")}
%{!?py3dir: %global py3dir %{_builddir}/python3-%{name}-%{version}-%{release}}
%define with_python3 0%{?fedora}%{?suse_version}

%if 0%{?suse_version}
Name:		python-Cython
%else
Name:		python2-Cython
%endif

Version:	0.26
Release:	0rc2%{?dist}
Summary:	A language for writing Python extension modules

Group:		Development/Tools
License:	Python
URL:		http://www.cython.org
#Source:		http://www.cython.org/Cython-%{version}.tar.gz
Source:		https://github.com/cython/cython/archive/0.26rc2.zip
BuildRoot:	%{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Requires:   python
%if 0%{?suse_version}
#no conflicts?
%else
Conflicts:	Cython
Obsoletes:	Cython < %{version}-%{release}
Provides: 	Cython = %{version}-%{release}
Provides: 	python2-Cython = %{version}-%{release}
%endif

BuildRequires:	python-devel python-setuptools
%if %{with_python3}
BuildRequires:  python3-devel
%endif


%description
This is a development version of Pyrex, a language
for writing Python extension modules.


%if %{with_python3}
%package -n python3-Cython
Summary:        A language for writing Python extension modules
Group:          Development/Tools
 
%description -n python3-Cython
This is a development version of Pyrex, a language
for writing Python extension modules.
%endif


%prep
#%setup -q -n Cython-%{version}
%setup -q -n cython-0.26rc2

%if %{with_python3}
rm -rf %{py3dir}
cp -a . %{py3dir}
find %{py3dir} -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python3}|'
%endif
 
find -name '*.py' | xargs sed -i '1s|^#!python|#!%{__python}|'


%build
CFLAGS="$RPM_OPT_FLAGS" %{__python} setup.py build
 
%if %{with_python3}
pushd %{py3dir}
CFLAGS="$RPM_OPT_FLAGS" %{__python3} setup.py build
popd
%endif


%install
rm -rf %{buildroot}
# Must do the python3 install first because the scripts in /usr/bin are
# overwritten with every setup.py install (and we want the python2 version
# to be the default for now).
%if %{with_python3}
pushd %{py3dir}
%{__python3} setup.py install --skip-build --root $RPM_BUILD_ROOT
mv $RPM_BUILD_ROOT/usr/bin/cython $RPM_BUILD_ROOT/usr/bin/cython3
mv $RPM_BUILD_ROOT/usr/bin/cygdb $RPM_BUILD_ROOT/usr/bin/cygdb3
rm -rf %{buildroot}%{python3_sitelib}/setuptools/tests
popd
%endif

%{__python} setup.py install -O1 --skip-build --root %{buildroot}
rm -rf %{buildroot}%{python_sitelib}/setuptools/tests


%clean
rm -rf %{buildroot}


##%%check
##%%{__python} runtests.py -x numpy


%files
%defattr(-,root,root,-)
%{_bindir}/cython
%{_bindir}/cythonize
%{_bindir}/cygdb
%{python_sitearch}/*
%doc *.txt Demos Doc Tools
%if %{with_python3}
%files -n python3-Cython
%{python3_sitearch}/*
%{_bindir}/cython3
%{_bindir}/cygdb3
%{python3_sitearch}/Cython*egg-info
%doc *.txt Demos Doc Tools
%endif


%changelog
* Wed Jul 19 2017 Antoine Martin <antoine@devloop.org.uk> - 0.26-0rc2
- new release candidate

* Sat Jul 15 2017 Antoine Martin <antoine@devloop.org.uk> - 0.26-0rc0
- release candidate

* Tue Jul 11 2017 Antoine Martin <antoine@devloop.org.uk> - 0.26-0b2p1
- add fallthrough fix

* Tue Jul 11 2017 Antoine Martin <antoine@devloop.org.uk> - 0.26-0b2
- new beta release

* Tue Jul 04 2017 Antoine Martin <antoine@devloop.org.uk> - 0.26-0b0
- new beta release

* Sun Dec 25 2016 Antoine Martin <antoine@devloop.org.uk> - 0.25.2-2
- add provides for python2 package naming

* Fri Dec 09 2016 Antoine Martin <antoine@devloop.org.uk> - 0.25.2-1
- new upstream release

* Fri Nov 04 2016 Antoine Martin <antoine@devloop.org.uk> - 0.25.1-1
- new upstream release

* Wed Oct 26 2016 Antoine Martin <antoine@devloop.org.uk> - 0.25-1
- new upstream release

* Fri Jul 15 2016 Antoine Martin <antoine@devloop.org.uk> - 0.24.1-1
- new upstream release

* Tue Apr 05 2016 Antoine Martin <antoine@devloop.org.uk> - 0.24-1
- new upstream release

* Sat Mar 26 2016 Antoine Martin <antoine@devloop.org.uk> - 0.23.5-1
- new upstream release

* Sun Oct 11 2015 Antoine Martin <antoine@devloop.org.uk> - 0.23.4-1
- new upstream release

* Tue Sep 29 2015 Antoine Martin <antoine@devloop.org.uk> - 0.23.3-1
- new upstream release

* Fri Sep 11 2015 Antoine Martin <antoine@devloop.org.uk> - 0.23.2-1
- new upstream release

* Sun Aug 23 2015 Antoine Martin <antoine@devloop.org.uk> - 0.23.1-2
- build python3 package

* Sun Aug 23 2015 Antoine Martin <antoine@devloop.org.uk> - 0.23.1-1
- new upstream release

* Wed Aug 19 2015 Antoine Martin <antoine@devloop.org.uk> - 0.23-2
- add upstream patch for infinite deepcopy loop

* Sun Aug 09 2015 Antoine Martin <antoine@devloop.org.uk> - 0.23-1
- new upstream release

* Mon Jun 22 2015 Antoine Martin <antoine@devloop.org.uk> - 0.22.1-1
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

* Thu Feb 12 2015 Antoine Martin <antoine@devloop.org.uk> - 0.22-1
- new upstream release

* Thu Jan 22 2015 Antoine Martin <antoine@devloop.org.uk> - 0.22.beta0-0
- new beta

* Sun Dec 28 2014 Antoine Martin <antoine@devloop.org.uk> - 0.21.2-1
- new upstream release

* Sun Oct 19 2014 Antoine Martin <antoine@devloop.org.uk> - 0.21.1-1
- Update to 0.21.1

* Thu Sep 11 2014 Antoine Martin <antoine@devloop.org.uk> - 0.21-1
- Update to 0.21

* Thu Jul 31 2014 Antoine Martin <antoine@devloop.org.uk> - 0.20.2-2
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
