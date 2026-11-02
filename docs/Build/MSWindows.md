# Building MS Windows Binaries

<div class="docs-section-heading" markdown="1">

## Setup

</div>

* install [MSYS2](https://www.msys2.org/) and update the system: run `pacman -Syu` until all the updates are applied
* use the `UCRT64` or `CLANG64` shell: the old `MINGW64` environment is [deprecated](https://www.msys2.org/docs/environments/), and packages it used to ship have already been removed from it
* from a MinGW shell, run this setup script: [SETUP.sh](https://github.com/Xpra-org/xpra/tree/master/packaging/MSWindows/SETUP.sh), which also installs verpatch and InnoSetup for generating EXE packages
* for the extra components required by full (non-light) builds, then run [SETUP_EXTRAS.sh](https://github.com/Xpra-org/xpra/tree/master/packaging/MSWindows/SETUP_EXTRAS.sh), which also installs Visual Studio Build Tools and TortoiseSVN for PuTTY plink support


<div class="docs-section-heading" markdown="1">

## Optional dependencies

</div>

* to build [NVENC](../Usage/NVENC.md) or NVFBC support, install [CUDA](https://developer.nvidia.com/cuda-downloads) and follow the NVIDIA setup instructions printed by `SETUP_EXTRAS.sh`


<div class="docs-section-heading" markdown="1">

## Build

</div>
From the source directory, just run the build script [BUILD.py](https://github.com/Xpra-org/xpra/tree/master/packaging/MSWindows/BUILD.py)


<div class="docs-section-heading" markdown="1">

## See also

</div>

* [Windows Subsystem for Linux (WSL)](../Usage/WSL.md)
* [Windows system service](../Usage/Windows-Service.md)
* [Windows downloads and installer formats](../Download/Windows.md)
* [Build dependencies](Dependencies.md)
