# ![package](../images/icons/package.png) Building RPMs


## Build requirements
```shell
dnf install gcc gcc-c++ \
            libXtst-devel libXdamage-devel libxkbfile-devel \
            python3-devel python3-Cython \
            python3-gobject pygobject3-devel python3-cairo-devel \
            gtk3-devel gobject-introspection-devel \
            redhat-rpm-config \
            pandoc
```
You may also refer to the more generic list of [dependencies](./Dependencies.md)

## Extra dependencies
<details>
  <summary>Vfb command</summary>

To use [Xdummy](../Usage/Xdummy.md):
```shell
dnf install xorg-x11-server-Xorg xorg-x11-drv-dummy xorg-x11-xauth xorg-x11-xkb-utils
```
Otherwise, use `Xvfb`:
```shell
dnf install xorg-x11-server-Xvfb
```
</details>
<details>
  <summary>Video codecs</summary>

For extra video encoding support, install the following development headers from [rpmfusion.org](https://rpmfusion.org/) and / or [EPEL](https://docs.fedoraproject.org/en-US/epel/):
```shell
dnf install libvpx-devel libyuv-devel ffmpeg-devel x264-devel
```
</details>
<details>
  <summary>OpenGL</summary>

For [OpenGL accelerated client rendering](../Usage/Client-OpenGL.md) support, add this runtime dependency:
```shell
dnf install python3-pyopengl
```
</details>

## Build
```shell
python3 ./setup.py install
```
</details>

## ![RPM](../images/icons/rpm.png)
The spec file can be found here:
https://github.com/Xpra-org/xpra/tree/master/packaging/rpm/xpra.spec


The quick and easy way:
```shell
mkdir -p ~/rpmbuild/SOURCES/ >& /dev/null
git clone https://github.com/Xpra-org/xpra
cd xpra
python3 ./setup.py sdist --formats=xz
cp dist/*xz patches/* ~/rpmbuild/SOURCES/
rpmbuild -ba ./packaging/rpm/xpra.spec
ls -s ~/rpmbuild/RPMS/*/
```
This builds fresh packages from git master.  
You can also use other branches, tags or download a [source release](https://xpra.org/src/) instead.
