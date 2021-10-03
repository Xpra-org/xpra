# Dependencies
Most of these dependencies should be installed automatically when you install official packages.  
Unless otherwise stated, the dependencies are all optional.


<details>
  <summary>Core Dependencies</summary>

Those are required by almost every component.
| Project | Source Download Link | Purpose | Client or Server | Notes |
|---------|----------------------|---------|------------------|:------|
|[glib](https://developer.gnome.org/glib/)|[https://ftp.gnome.org/pub/gnome/sources/glib/](https://ftp.gnome.org/pub/gnome/sources/glib/)|low-level library|both|Required|
|[gtk](http://www.gtk.org/)|http://ftp.gnome.org/pub/gnome/sources/gtk+/|UI Toolkit|both|Required|
|[pyopengl](http://pyopengl.sourceforge.net/)|https://pypi.python.org/pypi/PyOpenGL and <br /> https://pypi.python.org/pypi/PyOpenGL-accelerate|[client OpenGL accelerated rendering](./Client-OpenGL)|client| |
|[pycups](https://github.com/zdohnal/pycups)|https://pypi.org/project/pycups/|[Printing](./Printing)|both| |
</details>

<details>
  <summary>Network Layer</summary>

See [Network](../Network/README.md)
| Project | Source Download Link | Purpose | Client or Server | Notes |
|---------|----------------------|---------|------------------|:------|
|[rencode](https://github.com/aresch/rencode)|https://pypi.python.org/pypi/rencode/|[packet encoding](./PacketEncoding)|both |Recommended|
|[pyyaml](http://pyyaml.org/)|https://pypi.python.org/pypi/PyYAML/|alternative packet encoder|both |optional (usually unused)|
|[lz4](https://github.com/lz4/lz4)|https://github.com/lz4/lz4/releases|[packet compression](./PacketEncoding)|both|Recommended|
|[python-lz4](https://pypi.python.org/pypi/lz4)|https://github.com/python-lz4/python-lz4|python wrapper for lz4|both|Recommended|
|[lzo](https://www.lzop.org/)|http://www.oberhumer.com/opensource/lzo/#download|[packet compression](./PacketEncoding)|both|optional - deprecated (usually unused as lz4 is better) - win32 build, see [#1044](../../issues/1044)|
|[python-lzo](https://github.com/jd-boyd/python-lzo)|https://pypi.org/project/python-lzo/|python wrapper for lzo|both|optional|
|[python-cryptography](https://cryptography.io/en/latest/)|https://pypi.python.org/pypi/cryptography|[Encryption](./Encryption)|both||
|[python-zeroconf](https://github.com/jstasiak/python-zeroconf)|https://pypi.org/project/zeroconf/|[Multicast DNS](./Multicast-DNS) session publishing|server||
|[python-netifaces](http://alastairs-place.net/projects/netifaces/)|https://pypi.python.org/pypi/netifaces|[Multicast DNS](./Multicast-DNS) session publishing|server||
|[dbus-python](https://pypi.python.org/pypi/dbus-python/)|https://dbus.freedesktop.org/releases/dbus-python/|desktop integration, server control interface|both|not applicable to MS Windows or Mac OSX|
|[openssl](https://www.openssl.org/)|https://www.openssl.org/source/|[SSL](./SSL)|both||
|[paramiko](https://pypi.org/project/paramiko/)|https://pypi.org/project/paramiko/|[ssh integration](./SSH)|both||
|[sshpass](https://sourceforge.net/projects/sshpass/)|https://sourceforge.net/projects/sshpass/files/sshpass/|non-interactive SSH password authentication|usually client||
|[brotli](https://github.com/google/brotli)|https://github.com/google/brotli/releases|HTML client compression|r15540 |
</details>

<details>
  <summary>Authentication</summary>

See [authentication modules](../Usage/Authentication.md)
| Project | Source Download Link | Purpose | Client or Server | Notes |
|---------|----------------------|---------|------------------|:------|
|[python-gssapi](https://github.com/sigmaris/python-gssapi)|https://pypi.org/project/gssapi/|GSSAPI|server|[#1691](../../issues/1691)|
|[python-kerberos](https://github.com/apple/ccs-pykerberos)|https://pypi.org/project/kerberos/|Kerberos|server|[#1691](../../issues/1691)|
|[python-ldap](https://www.python-ldap.org)|https://pypi.org/project/python-ldap/|LDAP|server|[#1691](../../issues/1691)|
|[python-ldap3](https://github.com/cannatag/ldap3)|https://pypi.org/project/ldap3/|LDAP v3|server|[#1691](../../issues/1691)|
|[pyu2f](https://github.com/google/pyu2f)|https://pypi.org/project/pyu2f/|U2F|server|[#1789](../../issues/1789)|
</details>

<details>
  <summary>Python modules</summary>

| Project | Source Download Link | Notes |
|---------|----------------------|:------|
|[python-ipaddress](https://github.com/phihag/ipaddress)|https://pypi.org/project/ipaddress/|unspecified: r11859|
|[python-idna](https://github.com/kjd/idna)|https://pypi.org/project/idna/|unspecified: r11860|
|[python-decorator](https://github.com/micheles/decorator)|https://pypi.org/project/decorator/|required by gssapi: r18781|
|[pytest-runner](https://github.com/pytest-dev/pytest-runner)|https://pypi.org/project/pytest-runner/|required by python-lz4: r17864|
|[python-deprecation](http://deprecation.readthedocs.io/)|https://pypi.org/project/deprecation/|required by python-lz4: r17749|
|[python-pkgconfig](https://github.com/matze/pkgconfig)|https://pypi.org/project/pkgconfig/|required by python-lz4: r17748|
|[python-setuptools-scm](https://github.com/pypa/setuptools_scm/)|https://pypi.org/project/setuptools-scm/|required by python-lz4: r15282|
|[nose](https://nose.readthedocs.io/en/latest/)|https://pypi.org/project/nose/|required by python-lz4: r8676|
|[pyasn1](https://github.com/etingof/pyasn1)|https://pypi.org/project/pyasn1/|unspecified: r5829|
|[asn1crypto](https://github.com/wbond/asn1crypto)|https://pypi.org/project/asn1crypto/|required by python-cryptography: r17856|
|[python-packaging](https://github.com/pypa/packaging)|https://pypi.org/project/packaging/|required by python-cryptography: r15310|
|[pyparsing](https://github.com/pyparsing/pyparsing/)|https://pypi.org/project/pyparsing/|required by python-cryptography: r15310|
|[cffi](https://cffi.readthedocs.io/en/latest/)|https://pypi.org/project/cffi/|required by python-cryptography: r11633|
|[six](https://github.com/benjaminp/six)|https://pypi.org/project/six/|required by python-cryptography: r11640|
|[enum-compat](https://github.com/jstasiak/enum-compat)|https://pypi.org/project/enum-compat/|required by zeroconf: r20441|
|[enum34](https://bitbucket.org/stoneleaf/enum34)|https://pypi.org/project/enum34/|required by enum-compat: r15397|
|[setuptools](https://github.com/pypa/setuptools)|https://pypi.org/project/setuptools/|unspecified: r5829|
|[pycparser](https://github.com/eliben/pycparser)|https://pypi.org/project/pycparser/|required by cffi: r11634|
|[pynacl](https://github.com/pyca/pynacl/)|https://pypi.org/project/PyNaCl/|crypto library used by paramiko: r19967|
|[bcrypt](https://github.com/pyca/bcrypt/)|https://pypi.org/project/bcrypt/|crypto library used by paramiko: r19965|
</details>

<details>
  <summary>Encodings</summary>

See [picture encodings](../Usage/Encodings.md)
| Project | Source Download Link | Purpose | Client or Server |
|---------|----------------------|---------|------------------|
|[x264](http://www.videolan.org/developers/x264.html)|ftp://ftp.videolan.org/pub/x264/snapshots/|h264 encoding|server|
|[ffmpeg](http://www.ffmpeg.org/)|http://ffmpeg.org/releases/|h264, h265, vp8 and vp9 decoding|client|
|[vpx](http://www.webmproject.org/tools/)|http://downloads.webmproject.org/releases/webm/index.html|vp8 and vp9 codec|both|
|[webp](https://code.google.com/p/webp/)|http://downloads.webmproject.org/releases/webp/index.html|webp codec|both|
|[libpng](http://www.libpng.org/pub/png/libpng.html)|ftp://ftp.simplesystems.org/pub/libpng/png/src/libpng16/|png encoding|both|
|[libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo)|https://sourceforge.net/projects/libjpeg-turbo/files/|jpeg encoding|both|
|[python-pillow](https://python-pillow.github.io/)|https://pypi.python.org/pypi/Pillow|png,jpeg,webp encoding and decoding, format conversion - **Required**|both|
|[opencv](http://opencv.org/)|https://opencv.org/releases/|[Webcam capture](./Webcam)]|client|
|[libyuv](https://chromium.googlesource.com/libyuv/libyuv/)|https://chromium.googlesource.com/libyuv/libyuv/|[Colourspace Conversion](./CSC)|both|
|[pycuda](https://mathema.tician.de/software/pycuda/)|https://pypi.python.org/pypi/pycuda|[NVENC](./NVENC)|server|
|[cuda](http://www.nvidia.com/object/cuda_home_new.html)|https://developer.nvidia.com/cuda-toolkit|[NVENC](./NVENC)|server|
|[pyNVML](http://pythonhosted.org/nvidia-ml-py/)|https://pypi.python.org/pypi/nvidia-ml-py/|[NVENC](./NVENC)|server|
</details>

<details>
  <summary>Audio</summary>

See [audio forwarding](../Features/Audio.md)
| Project | Source Download Link | Purpose |
|---------|----------------------|---------|
|[gstreamer](http://gstreamer.freedesktop.org/)|http://gstreamer.freedesktop.org/src/|audio framework|
|[Ogg](http://xiph.org/ogg/)|http://downloads.xiph.org/releases/ogg/|ogg container format|
|[opus](https://www.opus-codec.org/)|http://downloads.xiph.org/releases/opus/|opus codec|
|[Flac](https://xiph.org/flac/)|http://downloads.xiph.org/releases/flac/|flac codec|
|[Speex](http://www.speex.org/)|http://downloads.xiph.org/releases/speex/|speex codec|
|[Vorbis](http://www.vorbis.com/)|http://downloads.xiph.org/releases/vorbis/|vorbis codec|
|[wavpack](http://www.wavpack.com/)|http://www.wavpack.com/downloads.html|wavpack codec|
|[faac](http://faac.sourceforge.net/)|http://faac.sourceforge.net/|aac encoder|
|[faad](http://faac.sourceforge.net/)|http://faac.sourceforge.net/|aac decoder|
|[lame](http://lame.sourceforge.net/)|http://sourceforge.net/projects/lame/files/lame/|MP3 encoder|
|[TwoLame](http://www.twolame.org/)|http://sourceforge.net/projects/twolame/files/twolame/|MP3 encoder|
|[Mad](http://sourceforge.net/projects/mad/)|http://sourceforge.net/projects/mad/files/libmad/|MP3 decoder|
</details>
