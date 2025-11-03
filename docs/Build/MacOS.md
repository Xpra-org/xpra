# ![MacOS](../images/icons/osx.png) Building MacOS Binaries

## Setup
Install [XCode](https://developer.apple.com/xcode/) and its command line tools.

If [homebrew](https://brew.sh/) or [macports](https://www.macports.org/) are installed, either remove them completely or at least move them out of the way. \
Having these package managers installed will interfere with the `jhbuild` build process. (example [here](https://github.com/Xpra-org/gtk-osx-build/issues/47))


<details>
  <summary>Setup gtk-osx</summary>

Download the latest version of the [gtk-osx](https://wiki.gnome.org/Projects/GTK/OSX/Building) setup script and run it:
```shell
git clone https://github.com/Xpra-org/gtk-osx-build
cd gtk-osx-build
sh gtk-osx-setup.sh
```
This will have installed `jhbuild` in `~/.new_local/bin`, so let's add this to our `$PATH`:
```shell
export PATH=$PATH:~/.new_local/bin/
```
</details>
<details>
  <summary>Configure `jhbuild` to use our modules</summary>

From the `gtk-osx-build` directory, run:
```shell
ln -sf "$(realpath .)/jhbuildrc-gtk-osx" ~/.config/jhbuildrc
ln -sf "$(realpath .)/jhbuildrc-custom" ~/.config/jhbuildrc-custom
```
</details>

Bootstrap:
```shell
jhbuild bootstrap-gtk-osx
```

Optional: install [pandoc](https://pandoc.org/installing.html#macos)

## Build all the libraries

First, make sure that all the modulesets will be using the same system libffi
as the one used by Python, so run this command from a `jhbuild shell`:
```commandline
cat > ${JHBUILD_PREFIX}/lib/pkgconfig/libffi.pc << EOF
prefix=$(xcrun --show-sdk-path)
libdir=\${prefix}/usr/lib
includedir=\${prefix}/usr/include/ffi

Name: libffi
Description: Library supporting Foreign Function Interfaces
Version: 3.4.6
Libs: -L\${libdir} -lffi
Cflags: -I\${includedir}
EOF
```
```shell
jhbuild update
jhbuild build
```

## Build and Package Xpra
```shell
git clone https://github.com/Xpra-org/xpra
cd xpra/packaging/MacOS/
sh ./make-app.sh
sh ./make-DMG.sh
sh ./make-PKG.sh
```
Signing the resulting `.app`, `DMG` and `PKG` images requires setting up certificates.
