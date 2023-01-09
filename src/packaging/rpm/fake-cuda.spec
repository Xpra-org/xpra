Name:           fake-cuda
Release:        1
Summary:        Fake CUDA RPM
License:        none
Version:        1.0
Provides:		cuda
Conflicts:		cuda

%description
A Fake CUDA RPM do allow us to build python-pycuda against non-RPM versions of CUDA.

%files

%changelog
* Fri Sep 30 2022 Antoine Martin <antoine@xpra.org> 1.0-1
- fake changelog entry to fix build warnings
