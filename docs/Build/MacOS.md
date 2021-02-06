![MacOS](https://xpra.org/icons/osx.png)

# Setup
Install [XCode](https://developer.apple.com/xcode/) and its command line tools.

Download the latest version of the [gtk-osx](https://wiki.gnome.org/Projects/GTK/OSX/Building) setup script and run it:
```shell
curl -O -osx-setup.sh https://gitlab.gnome.org/GNOME/gtk-osx/raw/master/gtk-osx-setup.sh
sh gtk-osx-setup.sh
```
This will have installed `jhbuild` in `~/.local/bin`, so let's add this to our `$PATH`:
```shell
export PATH=$PATH:~/.local/bin/
```
Configure `jhbuild` to use our modules:
```shell
curl -O ~/.jhbuildrc-custom https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/MacOS/jhbuild/jhbuildrc-custom-xpra
```
Download everything required for the build:
```shell
jhbuild update
```

# Build all the libraries
```shell
jhbuild bootstrap
jhbuild build
```

# Build and Package Xpra
```shell
git clone https://github.com/Xpra-org/xpra
cd xpra/packaging/MacOS/
sh ./make-app.sh
sh ./make-DMG.sh
```
Signing the resulting `.app`, `DMG` and `PKG` images requires setting up certificates.
