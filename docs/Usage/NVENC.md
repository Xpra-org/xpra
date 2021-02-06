![NVENC](https://xpra.org/icons/nvidia.png)

This encoder offers [the best latency](https://xpra.org/stats/NVENC/), which is most noticeable at higher resolutions.

# Hardware
This encoder requires a [supported NVIDIA graphics card](https://developer.nvidia.com/nvidia-video-codec-sdk#gpulist):
* a "professional" Quadro 4000 card (no license key required)
* a consumer card and a license key or a [patch](https://github.com/keylase/nvidia-patch) to workaround the artificial context limit which can be debilitating

# Software Requirements
You must have [PyCUDA](http://mathema.tician.de/software/pycuda/) installed (it is included in the official [xpra repositories](https://github.com/Xpra-org/xpra/wiki/Download)), and a recent enough version of the nvidia drivers. It is not compatible with the `nouveau` driver.

How you install those drivers is entirely up to you, here are some options for Fedora / RHEL:
* [nvidia installers](http://www.nvidia.com/object/unix.html)
* [negativo17 repository](http://negativo17.org/nvidia-driver/)
* [rpmfusion](http://rpmfusion.org/)
* [elrepo](http://elrepo.org/tiki/tiki-index.php)
etc..

If your CUDA (`libcuda.so`) or NVENC (`libnvidia-encode.so`) libraries are installed in an unusual location, it is your responsibility to ensure they can be loaded at runtime, usually by adding the directory to the `LD_LIBRARY_PATH`.

## Using NVENC
If the codec loads properly, it will be used ahead of the other software encoders automatically.

You can verify the video encoder currently in use with:
```shell
xpra info | grep "encoder="
```
Important: the video encoder is only used when needed, usually when there is a stream of screen updates.


## Debugging
To force xpra to use nvenc exclusively as video encoder, you can use the `--video-encoders=` command line option:
```shell
xpra start :10 --video-encoders=nvenc
```

To debug the availability of video encoders and GPUs:
```shell
xpra encoding
xpra video
xpra nvinfo
```

Once nvenc is running, you can debug the encoding process step with:
```shell
xpra start -d nvenc ...
```


## License Keys
You can store the license keys in `nvenc.keys`, either globally in `/etc/xpra/` or per-user in `~/.xpra/`.

Or you can also use the environment variable:
```shell
XPRA_NVENC_CLIENT_KEY="0A1B2C3D-4E5F-6071-8293-A4B5C6D7E8F9" xpra ...
```

Newer SDK versions may not support keys, or just not the same set of keys, in which case the number of sessions will be limited when using consumer cards.


## Building
* download and install the [CUDA SDK](https://developer.nvidia.com/cuda-downloads)
* install [PyCuda](http://wiki.tiker.net/PyCuda/Installation/Linux) - it is included in the [official repositories](https://github.com/Xpra-org/xpra/wiki/Download) for Fedora and RHEL
* download the [NVENC SDK](https://developer.nvidia.com/nvidia-video-codec-sdk), aka "NVIDIA VIDEO CODEC SDK" and install it somewhere (ie: just unzip into `/opt/`)
* create a `pkgconfig` file matching your SDK version and location, ie:
```shell
cat > /usr/lib64/pkgconfig/nvenc.pc
prefix=/usr/local/nvenc
exec_prefix=${prefix}
includedir=${prefix}/Interface
libdir=/usr/lib64/nvidia

Name: nvenc
Description: NVENC
Version: 10
Requires: 
Conflicts:
Libs: -L${libdir} -lnvidia-encode
Cflags: -I${includedir}
END
```
* when building xpra, nvenc support should be auto-detected, but you can try forcing it to verify, ie:
```shell
./setup.py build --with-nvenc
```


## Caveats
* you may need to adjust some paths
* if CUDA refuses to build and complains about `Installation Failed. Using unsupported Compiler` run the CUDA installer with `--override`
* there are undocumented incompatibilities between kernel versions, nvidia driver versions and nvenc SDK versions. If possible, install the driver version bundled with the nvenc SDK - these may manifest itself as undecipherable errors at runtime (`incompatible structure version errors`, etc)
* to adapt to new versions of the SDK and new architectures, one must add compile options to the build file - see [Matching SM architectures (CUDA arch and CUDA gencode) for various NVIDIA cards](https://arnon.dk/matching-sm-architectures-arch-and-gencode-for-various-nvidia-cards/)
