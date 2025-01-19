# Changelog

## [5.0.12] 2025-01-19
* Platforms, build and packaging:
    * [MSYS2 aarch64 build fix](https://github.com/Xpra-org/xpra/commit/fab8d9f02de9b4ca57d7fa88b8031a2c29a77d91) and [prefix detection](https://github.com/Xpra-org/xpra/commit/8166eee7d2f5e4b00327763627b33987edd5e0c7)
    * [RPM support for per-arch cuda pkgconfig](https://github.com/Xpra-org/xpra/commit/fa614d8672658f26d4094834dda89d5ee2d79038)
    * [`exe` installer standalone step](https://github.com/Xpra-org/xpra/commit/7d0c0c30e3d002f7468ec73f8fac6862b020ca6b)
    * [move default package list for newer build script default](https://github.com/Xpra-org/xpra/commit/dc7e2c74fbdfc584c8a830f258b4608af3a20a8c)
    * [invalid refresh rate detected on some MS Windows configurations](https://github.com/Xpra-org/xpra/commit/fa3b06de8a9d8737e9af5ea89a17b806b2f9fff5)
    * [MS Windows EXE upgrades conflict with left-over files](https://github.com/Xpra-org/xpra/commit/047c6e0d7b66c436e005629a504a2ff188cb1d62)
    * [MS Windows build script support for custom arguments](https://github.com/Xpra-org/xpra/commit/7bf6d970f6b43d3b077182d783aee76b4a8a4e9f)
* SBOM:
    * [minor fixes](https://github.com/Xpra-org/xpra/commit/5cb8451158a7070a3c44c0b7715b135ea17e6683)
    * [record CUDA](https://github.com/Xpra-org/xpra/commit/ecd20b6a0523aa8c3b07192f35ca694a03a30280)
    * [record 'Light' builds](https://github.com/Xpra-org/xpra/commit/bd604bf45db130f9066acef98424edd4bca5b854)
    * [export to JSON](https://github.com/Xpra-org/xpra/commit/558ceb8d6cd9e6a6da830909355ba1f1b356649a)
    * [fallback to `pip` package data](https://github.com/Xpra-org/xpra/commit/19842b615760b0a2ab3e504d4c99c204c421c3f6)
* RHEL 10:
    * [package list](https://github.com/Xpra-org/xpra/commit/8a70cfa92e40bd000692c5b5012a0f5e0d1f8604) + [fixup](https://github.com/Xpra-org/xpra/commit/5efb705aaab52c96096a6d8060253d03336ecd7b)
    * [provide wrapper script for `weston` + `Xwayland`](https://github.com/Xpra-org/xpra/commit/d96cdc84a71f8a6f895cee8a9a6a70872de4ba8a)
    * [use `weston` + `Xwayland` as `xvfb` option](https://github.com/Xpra-org/xpra/commit/023870556484b97f35108fc798f79e6fce42ed08)
    * [pycairo build fix](https://github.com/Xpra-org/xpra/commit/facee938bb3cd4891d3e4e8733fb45172126fc8f)
    * [no `pandoc` or `x264`](https://github.com/Xpra-org/xpra/commit/183f9996cfb8b9cbb6176955dfbf37150cc8e56d) + fixups: [x264](https://github.com/Xpra-org/xpra/commit/e94acc7c0f8fcb8f65deafe506c444eb3d42efce), [docs](https://github.com/Xpra-org/xpra/commit/9b4c93b88ddb0136811de2192d4a74f2e039bf7a)
    * [do build `libfakeXinerama`](https://github.com/Xpra-org/xpra/commit/d479991910311d55f9d81c305d4ff12f33a785ad)
* Major:
    * [`SSL` upgrades discard options](https://github.com/Xpra-org/xpra/commit/b6b396c2188f651f994809177368d0c74e4781bb)
    * [use symlinks to prevent ssh agent forwarding setup errors](https://github.com/Xpra-org/xpra/commit/3805cbdfe02244d6ece591acc642b67f6e57b109)
    * [websocket connection loss with some proxies sending empty payloads](https://github.com/Xpra-org/xpra/commit/9d679b30d940d70e8dbc6458b9ad2e3001f5d3b2)
    * [Network Manager API errors in some environments](https://github.com/Xpra-org/xpra/commit/276f8c0f7ced293504286e651cfdf92ebdab11cf)
    * [keyboard layout group regression](https://github.com/Xpra-org/xpra/commit/8068e18bee6a8d74b87084ead15984e63b5ee855)
* Desktop mode:
    * [better compatibility with some window managers when resizing](https://github.com/Xpra-org/xpra/commit/cf39bb72de8fe53f3404b40c7bcf8c1630ec3e5b)
    * [handle fixed size desktops correctly](https://github.com/Xpra-org/xpra/commit/2a440ae37db998d199e1975eff18861709d11f48)
* Clipboard:
    * [always claim the clipboard selection when updated](https://github.com/Xpra-org/xpra/commit/faf1e5c0a3413783d9c213ed8243732d771defe0)
    * [always update the peer when the owner changes](https://github.com/Xpra-org/xpra/commit/885a52f5ebd27df39f3af41dbf749bb9a153db4a)
    * [remote clipboard option not honoured on some platorms](https://github.com/Xpra-org/xpra/commit/1e093325a00c25c185f105edfc7bcf233923722b)
    * [allow all clipboards by default](https://github.com/Xpra-org/xpra/commit/9c48ccb4e5b08aeaade4c774a708ee51682e2522)
* Encodings:
    * [batch delay increase compounded](https://github.com/Xpra-org/xpra/commit/46cc6bdf4e2763f4f3ca9e6be3df605e1a57d707)
    * [avoid damage storms: switch to full frames earlier](https://github.com/Xpra-org/xpra/commit/f488150bc8ae227f71e4d6b7bbd38371b9db4243)
    * [`rgb` errors at unusual bit depths](https://github.com/Xpra-org/xpra/commit/2b0539dd4292235d30ddd3ac2f985c0a735467b9)
    * [transparency detection with 10-bit per channel windows](https://github.com/Xpra-org/xpra/commit/25b03183a9246a2b9c95f5b110e0a86f5dad0fb5)
    * [use `pillow` encoder for 10-bit per channel pictures](https://github.com/Xpra-org/xpra/commit/8db730382934f53f5dd0ae78278358c577b26231)
    * [pillow encoder fixes](https://github.com/Xpra-org/xpra/commit/3e2d7ad77d328bb5aaab1b9099657ca59e41332b)
    * [missing options when encoding is set to `auto` from the system tray menu](https://github.com/Xpra-org/xpra/commit/0319aaa209300b1aa5725c12fe9c561d32a08f6f)
    * [system tray speed control not available](https://github.com/Xpra-org/xpra/commit/aaf99601c6f2f20bccb226e42e4e19a323e915cf)
* Minor:
    * [toolbox examples do not run on some platforms](https://github.com/Xpra-org/xpra/commit/066b159a986ae5e184b0e3a06592f21f73a2386f)
    * [`quic` connections are safe for authentication](https://github.com/Xpra-org/xpra/commit/0355808d3b33a068ace81a82d51ab4ef9b77251c)
    * [`start-gui` fails if no application is selected](https://github.com/Xpra-org/xpra/commit/7a662155c4546642ccc08b5b1d2662bdc3ec863d)
    * [check for latest version from current branch](https://github.com/Xpra-org/xpra/commit/783d2ca9ae7af299f5ef54a83b27bc0017cf8b1c)
    * [clamp `vrefresh` to a useful range](https://github.com/Xpra-org/xpra/commit/62a958b6255c1f1884cfb1b71b88e2c8a95094a1)
    * [division by zero on MS Windows](https://github.com/Xpra-org/xpra/commit/d873fd54cc6c5d202b3f278c76fe5b28a62dbcd6)
    * [typo in nvjpeg encoder / decoder build switches](https://github.com/Xpra-org/xpra/commit/2726353d0751ee4f8da451149e62a0d9b8973989)
    * [avoid potential remote logging loop](https://github.com/Xpra-org/xpra/commit/d8754afd2e15eee00638c06a5e70ef92135dbb17)
* Cosmetic:
    * [proxy error messages formatting](https://github.com/Xpra-org/xpra/commit/b62ea90467389e7c03b84f4bf474653ade3a6f07)
    * [remove superfluous logging](https://github.com/Xpra-org/xpra/commit/e045e44a643914114924fbbcae96124e3446c72d)
    * [don't log scary warning about missing `numpy_formathandler`](https://github.com/Xpra-org/xpra/commit/3143698c630928f59d20780344e1c35dd4ffcc2a)
    * [unset load-balancer CUDA option is valid](https://github.com/Xpra-org/xpra/commit/d4283a911949a5cbdd7e350bd0f31c516348bc19)
    * [icon glob lookup mismatch](https://github.com/Xpra-org/xpra/commit/de9d565e3f43e21e933f6bf08177f5c076a794c3)
    * [typo](https://github.com/Xpra-org/xpra/commit/ee1dfcc16ef8768517c7202a4fad94e9e029391c)
    * [value in debug logging is incorrect](https://github.com/Xpra-org/xpra/commit/55c63aa2c9bdcc4625065d09052b684ef751dabf)
    * [log spam with rpd connection attempts](https://github.com/Xpra-org/xpra/commit/cde5b9da87f755961d594af339a3aafef3af9336)

## [5.0.11] 2024-11-22
* Platforms, build and packaging:
    * [don't build ffmpeg encoder on MacOS](https://github.com/Xpra-org/xpra/commit/bf2f1a3f4927428da0ae4c5d40e5125c4c8617d0)
    * [RPM builds without nvidia codecs failed](https://github.com/Xpra-org/xpra/commit/eeb6fd4cfb7c9c486b0c5649a993c4dc79099f34)
    * [RPM simplify Fedora feature checks](https://github.com/Xpra-org/xpra/commit/034b0a5c5891595b9cbda687f1fed2c25607e4cb)
    * [unnecessary module import on MacOS](https://github.com/Xpra-org/xpra/commit/6c7e63b93f40bc3a2fc710b82edff80c8450b38d)
    * [match `comtypes` module changes](https://github.com/Xpra-org/xpra/commit/51c589e30159e2d3559e144d8f6e64fd3644b869)
    * [run CI on Ubuntu 22.04 image](https://github.com/Xpra-org/xpra/commit/37cbdc2ca3f6991f792ae40786f84da3109db197)
    * [generate SBOM for MS Windows builds](https://github.com/Xpra-org/xpra/commit/3a060d5adfbedc48b71f8fb5ab7cebc610eeb0a8)
    * [missing SVG loader on MS Windows](https://github.com/Xpra-org/xpra/commit/3e98a4a5bbc510dc12f567776350c67514ecd7c9)
    * [loaders cache not populated](https://github.com/Xpra-org/xpra/commit/9923f1597a4841d70ed710a1fd7152e28a4f4960)
    * [record which repository is targeted](https://github.com/Xpra-org/xpra/commit/ad17c3b1fe6428769d232ea645b1e8849810c698)
    * [support providing build arguments using environment](https://github.com/Xpra-org/xpra/commit/986d88119348db767aaccd008cc145416898fb8d)
    * [syntax errors in the MS Windows build setup script](https://github.com/Xpra-org/xpra/commit/92e6cb9fc0c23ad3696620bdcd63aafabe7eaa55)
    * [aioquic 1.2.0 build fix](https://github.com/Xpra-org/xpra/commit/da8b51531850cd4e584d6e62dd8d8a993e505aa2)
    * [use arch specific pkg-config for cuda, if found](https://github.com/Xpra-org/xpra/commit/eca3def0b05f2b690f32a2bdf2c35865e006734a)
    * [patch pycuda for Python 3.13](https://github.com/Xpra-org/xpra/commit/76716a23a19ad5e3d945db01dafbd33289e3d85a)
    * [pynvml 12.560.30](https://github.com/Xpra-org/xpra/commit/963bfd306d30a422996adbcc67e57ca0df6b240d)
    * [pyuinput 1.0.1](https://github.com/Xpra-org/xpra/commit/2b9d5486692e6f72ee96d35e5fde5a09d8c05073)
    * [don't try to build ffmpeg encoder with ffmpeg >= 7](https://github.com/Xpra-org/xpra/commit/6122a4dd8bf0ae1e8674da47590338e949e12dd1)
    * [install clang++ on Debian distros that need it](https://github.com/Xpra-org/xpra/commit/97f1b03aefd3c39c2714ce8d24b91ad47ff79b1f) [but not on riscv64](https://github.com/Xpra-org/xpra/commit/f33422cd5248d92ba3f58f07da842ec2465e9962)
    * [newer libyuv needed newer patches](https://github.com/Xpra-org/xpra/commit/ada3a90820121f9957bd7406386738649d029fcd)
* Major:
    * [prevent buffer overflows in `libyuv` converter](https://github.com/Xpra-org/xpra/commit/b34f986035b7164860fb762f12351d5d2a2c5ee4)
    * [handle padded video streams (ie: from NVENC)](https://github.com/Xpra-org/xpra/commit/b5da77b7386af6737dad7a6053f86f2899da8a91)
    * [`run_scaled` syntax error](https://github.com/Xpra-org/xpra/commit/75d25ef615b8782f221eeacb3d424f6aabbb9b93)
    * [`xpra top` corrupted output](https://github.com/Xpra-org/xpra/commit/d631793d0c1f8d35593aa51c749af4ac70871c3c), [initialization failure](https://github.com/Xpra-org/xpra/commit/be38d098da0302a37e1ef108ad28d44b97472617)
    * [focus lost](https://github.com/Xpra-org/xpra/commit/2551a32bac64aee8354c4962426e80eb9fe3a298)
    * [keycode mapping for Wayland clients](https://github.com/Xpra-org/xpra/commit/1b7a4ea01a964a0a249c1121d89568b1587852cb)
    * [printing errors on MS Windows](https://github.com/Xpra-org/xpra/commit/bb0bd50d37c98a2e2002ba642a4c3d165b5ac62c)
* Network:
    * [verify ssl certificates can be accessed - not just the parent directory](https://github.com/Xpra-org/xpra/commit/f6e1caf75025a9f9354b587262d1350f7f915944)
    * [automatic re-connection path errors with MS Windows clients](https://github.com/Xpra-org/xpra/commit/6bfd2dc03bf5a6253f389f32525bef4b3bbb255a)
    * [ssl redirection errors](https://github.com/Xpra-org/xpra/commit/4e64fb776f4e14f6929dd1faa2a68202705883e5)
    * [raise maximum number of AES key stretching iterations](https://github.com/Xpra-org/xpra/commit/c6c055490605a85bfb02fbff7ac9c3f8e4867989), [and default](https://github.com/Xpra-org/xpra/commit/a296babb5020f1f78232cb8142005fcb44c8831f)
    * [automatic port assignment error](https://github.com/Xpra-org/xpra/commit/cc6582e6c5a61c6a05107c3fd2f9a11f338683c0)
    * [`vsock` connection errors](https://github.com/Xpra-org/xpra/commit/74cef58753b66b9f24f3252a03b6cbed8e17d4da)
* Minor:
    * [quality and speed options can be used with generic encodings](https://github.com/Xpra-org/xpra/commit/28034bef38b8b675fd802c55643b443669a63991)
    * [support pointer polling](https://github.com/Xpra-org/xpra/commit/8a7df98a6683f3af958df74308090e5734306b75)
    * [version update dialog cannot be closed](https://github.com/Xpra-org/xpra/commit/7643e477bf57dda71e137e73fe51f9ebe7ccbd60)
    * [prevent missing menu data from causing connection errors](https://github.com/Xpra-org/xpra/commit/deab47e10cc95005ca13d13afdc9e0f3e05a7c6e)
    * [redirection context errors should not propagate](https://github.com/Xpra-org/xpra/commit/0011ee06954a71b1a8aab9bd43ff0e0ed46578e4)
    * [the `openh264` home page states that 4k is the encoder limit](https://github.com/Xpra-org/xpra/commit/1f0b5aaf811c2eed631387d6832e17cab5edca16)
* Cosmetic:
    * [silence http timeouts](https://github.com/Xpra-org/xpra/commit/892f8de2b8c50928d30c27889350b46be000e83b)
    * [typo in manpage](https://github.com/Xpra-org/xpra/commit/233c8ddca6ceae90fe59ad326ff20f864c658b83)
    * [remove unused logger](https://github.com/Xpra-org/xpra/commit/a2e14564ee7cf349b408e20b51d9e4f0ca8c2c5e)
    * [handle missing `python-pillow` more gracefully](https://github.com/Xpra-org/xpra/commit/01c2f4ac050173f519a9de1b88ae5e4c67fcd17f)

## [5.0.10] 2024-09-10
* Platforms, build and packaging:
    * [syntax compatibility fix](https://github.com/Xpra-org/xpra/commit/8b56099122a8a8f6f753b97421910de487c30335), [and another one](https://github.com/Xpra-org/xpra/commit/a74a949e90c5fb397c8e6cf590e9fed4aad10de4)
    * [`openssl.cnf` location in MS Windows builds](https://github.com/Xpra-org/xpra/commit/3ad6c8e44438912c5dd9dcba427b17d6b20a463f)
    * [force rebuild of dummy driver RPMs](https://github.com/Xpra-org/xpra/commit/528816af936c95ea9a238507bd6a9f371b3baa84)
    * [Fedora can build html documentation again](https://github.com/Xpra-org/xpra/commit/4533efa1ffe7cc0d52cc4063b9b1da3a3478308a)
    * [always build the latest dummy DEB](https://github.com/Xpra-org/xpra/commit/1f7f9e3a8b3418e87b89e5c863a92b058f2a6baf)
    * [MS Windows multi-page printing](https://github.com/Xpra-org/xpra/commit/f3c0e92d3b5b85b7c05d898ad51ed7d24af6ece3)
    * [run CI builds with Python 3.6 and 3.12](https://github.com/Xpra-org/xpra/commit/4af53ffc9c20d5afd90e3bc8e4e14f0be4bbbe8b), [this requires Ubuntu 20.04](https://github.com/Xpra-org/xpra/commit/6ed0f4fce7833fb4a45c0960ce3c24bfe8d84385)
    * [remove outdated numpy workaround](https://github.com/Xpra-org/xpra/commit/a2940534da564578ed7a53fb7e4af92b06ca1978)
    * [libyuv 0.1878](https://github.com/Xpra-org/xpra/commit/eedb55fdcd0d88cccdc30970b9287b090fe82bef)
    * [nasm 2.16.03](https://github.com/Xpra-org/xpra/commit/73ef29ca1077697d7dca47a22d4eb547c5db95fb)
    * [cython 3.0.11](https://github.com/Xpra-org/xpra/commit/468018ed39989fdfc6c87263681c1bb6dfd30051)
    * [aioquic 1.2.0](https://github.com/Xpra-org/xpra/commit/8142aee9b2d6ed713f0b003b21334bab0e8bf802)
    * [pynvml 12.555.43](https://github.com/Xpra-org/xpra/commit/e3115ed747986edbcea4f26300b65854ebacefe5)
    * [pycuda 2024.1.2](https://github.com/Xpra-org/xpra/commit/73767cd45819f621f6e0308ae5bde67191d7cd93)
    * [pycuda RPMs to link against the system boost library](https://github.com/Xpra-org/xpra/commit/313092fa342f66d79ace1b4be552caead2a38b1b), [but not on RHEL 8](https://github.com/Xpra-org/xpra/commit/3f5325acedc0cb917bfb5ef53c22d664ade83803)
    * [build fix for ffmpeg v7 decoder and csc module](https://github.com/Xpra-org/xpra/commit/db493b80c224c2da3de539ea8d5f4615090bcf8d)
    * [build CUDA kernels with clang++ instead of gcc >= 14](https://github.com/Xpra-org/xpra/commit/3a6be55fed30528ce4753b26ec598596007c17f5)
    * [don't ship any Qt components in this branch](https://github.com/Xpra-org/xpra/commit/c595576cabdc33d45061cb92cf65c8c342559ef2)
    * [skip `xauth` setup on MS Windows servers](https://github.com/Xpra-org/xpra/commit/ad335412c4164293823158284794109ecb3fc70f)
* Major:
    * [system tray docking causing server crashes](https://github.com/Xpra-org/xpra/commit/010c091fc4da583d8ec6a32e793467d039084724) [+ fixup](https://github.com/Xpra-org/xpra/commit/141a82a33811b061c544310b67aaa4468eb87ca2)
    * [MS Windows PDF printing crash](https://github.com/Xpra-org/xpra/commit/57b88bc7703a6aebb619ef93809ff7e05d52107b), [library mismatch](https://github.com/Xpra-org/xpra/commit/89377450c9b728366d18208f775cc3419d712b39)
    * [honour `ssh` option when re-connecting](https://github.com/Xpra-org/xpra/commit/45bad59e6255f03087b8dbd51dfd2380472f6f20)
    * [missing http headers caused html5 client caching](https://github.com/Xpra-org/xpra/commit/bb8db97afcbd79ca8924728a674736026201d80f)
    * [mDNS browser handling for binary `text` records from zeroconf](https://github.com/Xpra-org/xpra/commit/14bd95980ce63e08aa6f2532b0a495f541caa01b)
    * [`sync-xvfb`: always free images with an error context](https://github.com/Xpra-org/xpra/commit/85547dac5f0d7fabd361db6d84964c27cba5b6bc)
    * [better compatibility with all builds of python cryptography](https://github.com/Xpra-org/xpra/commit/c91372a566ce46b82e1f406eba5a10ce0b092fb5)
    * [uninitialized pixels when resizing windows](https://github.com/Xpra-org/xpra/commit/c90eee5e235e5b8e288d3ecef5169319e0c28dde)
    * [window border offset with non-opengl renderer](https://github.com/Xpra-org/xpra/commit/bfb21a569858b849b7d752cdeef677c81326c817)
    * [client errors out with window forwarding disabled](https://github.com/Xpra-org/xpra/commit/c62bddc5ad170ca4a2bc7de121c969dce5e65349), [remove more assumptions](https://github.com/Xpra-org/xpra/commit/0541065690c0b52fcc41617d33469bf85a95224e)
    * [xshape client errors with desktop scaling](https://github.com/Xpra-org/xpra/commit/674103206ed64eeae92d8d232358472776647c9b)
    * [xshape windows should still honour the window border](https://github.com/Xpra-org/xpra/commit/e3c659fdf4e06190bc0c97126044a9c1d7cc8ddd)
    * [expose all clipboard targets](https://github.com/Xpra-org/xpra/commit/61ecf3f743c141937844b7eb6f226e6924d3d1aa)
    * [clipboard `INCR` transfers get stuck](https://github.com/Xpra-org/xpra/commit/f51f86a747690fe68f628b7cd72a1513f835607a)
    * [`scroll` paint corruption](https://github.com/Xpra-org/xpra/commit/ae957f2ff9808c9d5570a6b56e21b6e29483e610)
    * [connection drops when downscaling](https://github.com/Xpra-org/xpra/commit/3c66507b31f80eddbeb4ec2bfb66e5da709a4bd4)
    * [authentication aborted due to encryption not detected](https://github.com/Xpra-org/xpra/commit/557efe2514323c647ac2d4a49283dd8e34fc1475)
    * [always set a default initial resolution](https://github.com/Xpra-org/xpra/commit/a5edfc628ed02837faf6e337a167ae02ab925ec5)
    * [honour the initial resolution, even if resizing is disabled](https://github.com/Xpra-org/xpra/commit/1973b37e38f00b22d591445e19ce84b1052aef62)
    * [failure to add new virtual monitors](https://github.com/Xpra-org/xpra/commit/3dd7abcb5732288a421f52623692220883366d2a)
    * [http directory listing](https://github.com/Xpra-org/xpra/commit/3aa22cfa636f21ba079e352b81448d675174d59a) + [handler errors](https://github.com/Xpra-org/xpra/commit/ea6894996a3315311187eceffb1298c42bf904fa)
    * [avoid _Directory listing forbidden_ error](https://github.com/Xpra-org/xpra/commit/309a7c60d6df86f94bf842d93224cabfca0e5fa0)
* Encodings:
    * [`mmap` race condition](https://github.com/Xpra-org/xpra/commit/85e5a753aa96999d8160d71bff094f682ae3fc74)
    * [validate openh264 colorspace](https://github.com/Xpra-org/xpra/commit/0be7faef9ee503efabcd6d925ded8259243e4ac9)
    * [test used potentially invalid colorspace](https://github.com/Xpra-org/xpra/commit/d4883187a0c1497b0ece3330a6864f1b67d1a217)
    * avoid [slow modules](https://github.com/Xpra-org/xpra/commit/7a16475b73ebd8398e3c1b44561647a9d7877933) and [slow encoders](https://github.com/Xpra-org/xpra/commit/38a7b3daaa6b908d7faf93ab2fa31eed3cabc104)
    * [reduce how often quality swings cause scaling changes](https://github.com/Xpra-org/xpra/commit/7951a696e3afb79cd8b60394561eebaf379453b4)
    * [stick to the same video scaling value longer](https://github.com/Xpra-org/xpra/commit/aaf22afec492240dae512230aa5fe88c73546c51)
    * [sub-optimal non-scroll areas](https://github.com/Xpra-org/xpra/commit/3b90fc10cd945ee875bda8fc66497991d6fb01ef)
    * [prettier sampling filter when downscaling](https://github.com/Xpra-org/xpra/commit/5b2c89d53d9c9df119f860209e2c637140989ae1)
    * [nvenc causing decoding errors](https://github.com/Xpra-org/xpra/commit/9d7f74bc6b6d30cd8ffde66451189da42c1fd493)
    * workaround nvenc padded frames: [openh264 decoder](https://github.com/Xpra-org/xpra/commit/124baa8f3f061d81b5d71cb01bd1ee0dd56a0fef) and [ffmpeg decoder](https://github.com/Xpra-org/xpra/commit/9cb2a66791773f7c06ac961990a9466c8d2b56ca)
* Keyboard:
    * [`keyboard-sync` switch](https://github.com/Xpra-org/xpra/commit/404dc1c177ad292bdaca9ffabbf8bb8a709bd947) [not honoured](https://github.com/Xpra-org/xpra/commit/4823b24778329cd9718730ea515dbe72b8c607f2) [and not sent](https://github.com/Xpra-org/xpra/commit/55809937f4cd3aad0c0ba7b04d75377f15dcedc9)
    * [ignore MS Windows keyboard layouts without a valid X11 layout name](https://github.com/Xpra-org/xpra/commit/3eca141e0027e93ea1150a5a5939fc63425d9aaf)
    * [try harder to identify the key event string](https://github.com/Xpra-org/xpra/commit/01b36a92c1d2113c3897166c12bfc1177e4bdc55)
    * [don't show duplicate keyboard layout names](https://github.com/Xpra-org/xpra/commit/07d51f73ea08188b728633da745ea29b5285bb77)
    * [try harder to find a matching key by name](https://github.com/Xpra-org/xpra/commit/f5b83a7d8b19d50f161ecb5d51d44d1e8a4babfc) [try lowercase if needed](https://github.com/Xpra-org/xpra/commit/7c9be1a19755a96c476db74c8b176accf554caa5), [use default modifiers if that's all we've got](https://github.com/Xpra-org/xpra/commit/ef9e2839f494de28353b5aeb6fa01dd63703b582)
* Minor:
    * [remove enum prefix with older Python versions](https://github.com/Xpra-org/xpra/commit/8eabd33b578aed9670c1cef62a24e2dc73370b79)
    * [ssl path checks](https://github.com/Xpra-org/xpra/commit/e29d360cf5d09d1909c7556eca6bdaeadbb5d48a)
    * [RFB connections cannot be upgraded to `http` or `ws`](https://github.com/Xpra-org/xpra/commit/d91d34fb8b1303bbebbfbff733e35fed1ec6fb0a)
    * [make it possible to skip NM api](https://github.com/Xpra-org/xpra/commit/560e25100dafdf4c18caef559539db4510f4b997)
    * [expose QUIC sockets via mDNS](https://github.com/Xpra-org/xpra/commit/c58425cd5512a669da487414483f045943876f27)
    * [only enable gtk error context with x11 Gdk backend](https://github.com/Xpra-org/xpra/commit/161acb245b65e71dae6f179bcbfe0ef8ced230d2)
    * [handle empty ibus daemon command](https://github.com/Xpra-org/xpra/commit/12289c125af7caa58acac01a6b484a6be6fdac0c)
    * [handle invalid dbus-launch command](https://github.com/Xpra-org/xpra/commit/1c7433556d05175d5e43b85dfdcfb88501aab4ca)
    * [system tray setup failures with non-composited screens, ie: 8-bit displays](https://github.com/Xpra-org/xpra/commit/350bd4ac1f639814a0f9d384687394cca366bfdb)
    * [map missing modifiers using defaults](https://github.com/Xpra-org/xpra/commit/905cf2e5ca61e6504ba1cfb0429f659cd6c4842e)
    * [don't setup ssh agent dispatch when ssh is disabled](https://github.com/Xpra-org/xpra/commit/ab61a462d79c9aa0dbda310ef9f561c856bece82)
    * [request mode failures](https://github.com/Xpra-org/xpra/commit/afacb052499549b5ea088cfe95d1bd0321c93ae5)
    * [proxy servers should respond to `id` requests](https://github.com/Xpra-org/xpra/commit/3de103258e8d1a6d297427adf92a6f1ff5763fb7)
    * [system tray menu encoding options don't stick](https://github.com/Xpra-org/xpra/commit/ffe9a6bf8a8abd0c266c137f2abd47ddc8132c06)
* Cosmetic:
    * [errors when connections are closed as we process them](https://github.com/Xpra-org/xpra/commit/4d4ba9a078e91af86cd61b12b5021504a5e75ac2)
    * [try to prevent ATK warnings](https://github.com/Xpra-org/xpra/commit/440a182dbaaf1db0af81ab1b33d05bc454a726a0)
    * [validate application's opaque-region](https://github.com/Xpra-org/xpra/commit/6749cc91f8853ee03e406d6c0cec763c61d13274)
    * [slow CI test times out](https://github.com/Xpra-org/xpra/commit/6dff61f8dba6a1b5f9a59c0cd761cfe9674d5f14), [ignore it](https://github.com/Xpra-org/xpra/commit/0e0c24e679a21f0a63cf727fab6175ab6f5b1cc3)
    * only import modules actually needed: [notifications](https://github.com/Xpra-org/xpra/commit/ac5c314750104b879c5d088dd837ce21d14f1b73), [windows](https://github.com/Xpra-org/xpra/commit/7cb5f913131ccf8ac35d1dc42da5b4498060ebfe), [mmap](https://github.com/Xpra-org/xpra/commit/e0a873ccddcc519196d842f44c70dc4908e1f8d2)
    * [`desktop-scaling=no` parsing warnings](https://github.com/Xpra-org/xpra/commit/fb2f05cf9fba4919ede17831f125612b963474bb)
    * [log `ssl` error just once per socket](https://github.com/Xpra-org/xpra/commit/a409b1bbebece4d86dfe04fdd54c9b7f385fc1a9)
    * [OpenSSH documentation misplaced](https://github.com/Xpra-org/xpra/commit/b074848ada873561dd975238cfeb1ed5cf81ba93)
    * [we do have tests](https://github.com/Xpra-org/xpra/commit/8af9bb37c22f0b696b312c76801ec1b5dc597a74)
    * [incorrect exception debug message](https://github.com/Xpra-org/xpra/commit/8802efbbe28c1a445202f98a904d7210ac853c7c) and [format](https://github.com/Xpra-org/xpra/commit/544a11020a7e345b5eb08fdd5ec627cadba8fc44)
    * [paramiko looks unmaintained](https://github.com/Xpra-org/xpra/commit/253433ddc4e902dbb3b99d49b34148bba70975bd)
    * [AES modes and keydata safety documentation](https://github.com/Xpra-org/xpra/commit/c299b0100865b763284403dce83d496eb76bbeb6)
    * [missing line continuation backslash in example](https://github.com/Xpra-org/xpra/commit/e95b0c8d551ffe85c7644b3d1055d0410086fbfe)
    * [missing quote](https://github.com/Xpra-org/xpra/commit/b88e1667033398ebad55639b10e448a22b08648e)
    * [log opengl probe command](https://github.com/Xpra-org/xpra/commit/675bf35b7f25ac3ec4d5ccd83c0920bba4c9d935)
    * [clarify display name message](https://github.com/Xpra-org/xpra/commit/28f3c30cb10528a91e14b0961b98b1ac2eb47851)
    * [support the same resolution aliases as newer versions](https://github.com/Xpra-org/xpra/commit/f2c3f6bb182a0007a255a0f52fa9ce55886147a5)
    * [log randr error code](https://github.com/Xpra-org/xpra/commit/1ec9ff7752d139a2477fcbe4ab219c9507658eea)
    * [X11 client messages warnings](https://github.com/Xpra-org/xpra/commit/f267241ff07bcb86df10e5ebec19582968626dd0)
    * [avoid 'none' values warnings with video options](https://github.com/Xpra-org/xpra/commit/8eed3948a0ac4f14ffd28a8a1b1baef2047af9be)


## [5.0.9] 2023-06-18
* Encodings:
    * [video encoding errors causing missed screen updates](https://github.com/Xpra-org/xpra/commit/188e9903754e1abc8cd86ecd65bf9427000e7012)
    * [drop alpha if requested](https://github.com/Xpra-org/xpra/commit/6e1934575cabc412782616704bb4ee24b5f36930) and [for video encoders](https://github.com/Xpra-org/xpra/commit/3cbdccbcdd9be7fdf6eabb67b322e612852f108c)
    * [`konsole` is a text application](https://github.com/Xpra-org/xpra/commit/6c46f648ed923615de08385aa4b7e900ad4357dc)
    * [smarter auto refresh encoding selection](https://github.com/Xpra-org/xpra/commit/6f138036414a404bf1782d5554009a038dd6feab)
    * [X264 warning `intra-refresh is not compatible with open-gop`](https://github.com/Xpra-org/xpra/commit/0c8153330e081b1ea894a73529339e052ace5c70)
    * [openh264 decoder self test](https://github.com/Xpra-org/xpra/commit/cd6104331b079714974fe42f50b59abcccb4bd89)
    * [Pillow 10 supports memoryview buffers](https://github.com/Xpra-org/xpra/commit/534c674c920130036e23af8f3ccd029e443d572e)
* Platforms, build and packaging:
    * [arm64 and riscv builds can timeout adding build info](https://github.com/Xpra-org/xpra/commit/85ee52e738a75ab63749c0b986bf7702cf135c5d), [and generating the documentation](https://github.com/Xpra-org/xpra/commit/a6c9c98665d9ad384729a0eb8f74d77a62ff4771)
    * [saner source information defaults](https://github.com/Xpra-org/xpra/commit/79b7484c6f50275f48a3195385d80be918e2aa18)
    * [more simple / reliable OpenGL pixel format attributes on MacOS](https://github.com/Xpra-org/xpra/commit/d95bcdb01d13ee0e363b70f281113ec88b1fadca)
    * [MS Windows usernames should also be using strings](https://github.com/Xpra-org/xpra/commit/6a14cedcaf528d106ccc3d9e80db2f900a4ffa93)
    * [Cython compilation warnings](https://github.com/Xpra-org/xpra/commit/dfd6fea4f3099a3894f93c32c0cfb5904e96ccc5)
    * [CI: build test with Python 3.6 and 3.12](https://github.com/Xpra-org/xpra/commit/1101463901b4db5f2d13b15b8a0b6a52705dbd9a)
    * [missing explicit `cairo` dependency](https://github.com/Xpra-org/xpra/commit/21bc5d847965ff00d548af8d8fb4db90efa53ea0)
    * [RPM revision number missing](https://github.com/Xpra-org/xpra/commit/92247353d4a32b99aab49aa9e499cb29a74beb5a)
* Major:
    * [handle downscaled video correctly without OpenGL](https://github.com/Xpra-org/xpra/commit/e59d1c5f28c06b295bd28eca1ccf728d4ce06a15)
    * [Gtk crashes on exit](https://github.com/Xpra-org/xpra/commit/5032b0144a68e6dadd6f18a095e48c0e8891c4ef)
    * [OpenGL check failures on X11](https://github.com/Xpra-org/xpra/commit/2cb40fa38a7be95431abbe55d784767e52f6ef60)
    * [`OpenGL` check failures on MS Windows when executed from GUI tools](https://github.com/Xpra-org/xpra/commit/72096d0a4b89e9371751d7e07c7be311c8ebf241)
    * [sync-xvfb not honoured](https://github.com/Xpra-org/xpra/commit/fe6b7ea6e0c891ba37844b72bccd71cb48575356)
    * [replace dead ssh agent symlinks](https://github.com/Xpra-org/xpra/commit/37842c6b4d39185385a55df3f34cab4cfd444b0f)
    * [validate http request hostname before sending it back](https://github.com/Xpra-org/xpra/commit/2157a0d12aef852e08d3a75da19a54d510568ee6)
    * [guess content type from commands](https://github.com/Xpra-org/xpra/commit/e1159b5a7b9bf6a25a694646c5b349612bddaba8)
    * [ssh channel pollution](https://github.com/Xpra-org/xpra/commit/14efe7164d555e8bb6255a91454f17b829a43615)
    * [incorrect client exit code with Python 3.10 and earlier](https://github.com/Xpra-org/xpra/commit/5d8a6f7e78eb7125583049a1cd2a3958fa5193c8), [don't convert enums to strings](https://github.com/Xpra-org/xpra/commit/7a9d8f745b7cf566f7fc62521a2424de000d2e9b), [correct matching type hints](https://github.com/Xpra-org/xpra/commit/523d8b1b4a6315f4de10e292fa5bad1c3314dfef)
    * [libyuv converter cannot scale `YUV444P`](https://github.com/Xpra-org/xpra/commit/2623ca48ef3d2314c0afef8fae957e07be889420)
    * [ffmpeg decoder can accept images with dimensions rounded down to a multiple of 2](https://github.com/Xpra-org/xpra/commit/f2ab789f2c623b93f01bb692982125a472181097), [same for swscale](https://github.com/Xpra-org/xpra/commit/ebed4b2b3541641944615e0b61cbbd91bcfdc697)
    * [audio source plugins not found](https://github.com/Xpra-org/xpra/commit/35e8a5c27136294087bd62c6b90fd81128866237)
    * [client startup failures caused by `dbus`](https://github.com/Xpra-org/xpra/commit/160032c06d5f3857986462f80a7007ce7bb117b5)
    * [updated `run_scaled` script](https://github.com/Xpra-org/xpra/commit/d7643c8252bbe7d7d5053323d23d70f1cd5b1706)
    * [use the dynamic speed and quality assigned for video encoders](https://github.com/Xpra-org/xpra/commit/3d4f05939feb82e27c50725f7039c8f8d536407f)
    * [proxy compression broken](https://github.com/Xpra-org/xpra/commit/7138c22ac0b530e66c67e29753f213b65a7dd5dd)
* Minor:
    * [fix parsing of scaling values as percentages](https://github.com/Xpra-org/xpra/commit/848d1658f2f4eb1bef57312736166e3f438fdca9)
    * [fix ssl unit test](https://github.com/Xpra-org/xpra/commit/0a03faadd843450c158df80e7a53729432d1e102), [use SSL specific error codes](https://github.com/Xpra-org/xpra/commit/e52882a6ac2cd3cef3067bb89a227feb59e6fa31)
    * [case-insensitive window role matching](https://github.com/Xpra-org/xpra/commit/e14e3509be23bdfcd2df9b1779a0fa888e9f1d11)
    * [splash screen communication errors due to unexpected characters](https://github.com/Xpra-org/xpra/commit/c8c460db288bb41678bd1e69f5447a0c06f18987)
    * [splash screen can exit cleanly](https://github.com/Xpra-org/xpra/commit/7c9a4748b28a5f422748d9c6264d79d7400cd922)
    * [standlone bug report tool cannot exit cleanly](https://github.com/Xpra-org/xpra/commit/80aabb353aae2c6f1a7e8de35664fead590279cd)
    * [never try to start a display in `proxy` or `shadow` modes](https://github.com/Xpra-org/xpra/commit/688c09c7e37cbb980ca2abf46df7832b176099b7)
    * [do verify that the display is available in `monitor` mode](https://github.com/Xpra-org/xpra/commit/a4a63223409e5a3de2f8eac2f55000e26dec5e9a)
    * [prevent audio DoS in the future](https://github.com/Xpra-org/xpra/commit/c4a88d406aa5fe9c43e6af4059284f434c26139d)
    * [help video decodes with colorspace metadata](https://github.com/Xpra-org/xpra/commit/288a2a5bd8def111efa72eed29eaa24763de3286)
    * [handle decoding of full-range YUV](https://github.com/Xpra-org/xpra/commit/8427da4d6219d74ec7fe075ffbb9feb6949972f8)
    * [`sync-xvfb` requires cairo](https://github.com/Xpra-org/xpra/commit/20ef5ce0f29cb839d428d78c759c35f80b46af8e)
    * [blacklist `llvmpipe` software OpenGL renderer](https://github.com/Xpra-org/xpra/commit/1055dc14b112e5907e09fa5bea34894a261a3139) [but probe server opengl properties anyway](https://github.com/Xpra-org/xpra/commit/b7beadf2ee32198719145463839166fb8e30a106)
    * [allow printing with more socket authentication modules](https://github.com/Xpra-org/xpra/commit/0f73968a69d2a1867635c48d6eb68bf949981775)
    * [map Visual Studio Code to `text`](https://github.com/Xpra-org/xpra/commit/431eca8468dc41c892c21840972ae81d2327dd21)
    * [isolate failures to show or hide a window](https://github.com/Xpra-org/xpra/commit/9087d1bc684a0a6da4a40206d53fe5497acc22c0)
    * [bump openh264 bitstream level](https://github.com/Xpra-org/xpra/commit/16278362c0a417cc4df810b41c738f9bdeab8654)
    * [only reparent windows if needed](https://github.com/Xpra-org/xpra/commit/0356c81c1529c139532f8177f8070afa0d453c29) [but always send `ConfigureNotify`](https://github.com/Xpra-org/xpra/commit/91f1a0b03440c291f53eee836d599931dd06dc60)
    * [full self-tests for `jpeg` decoder](https://github.com/Xpra-org/xpra/commit/df2c2e77f76d0924962b025c72269f97f3727664)
    * [openh264 encoder should set the frame number](https://github.com/Xpra-org/xpra/commit/96fdb7ca2252acd8023ddf0dfaea3c869c9a3aea)
* Cosmetic:
    * [don't spam the logs](https://github.com/Xpra-org/xpra/commit/8e7433178007a82d99eca047894c8a8e1d6bec8a) [because of a `pyxdg` bug](https://github.com/Xpra-org/xpra/commit/720c79b545fea021b5c063db485d9c496b715d5e)
    * [clearer audio error message](https://github.com/Xpra-org/xpra/commit/7adc99fa9143d60e0c8cd7886eb7bdc576373db1)
    * [clearer ssh error message](https://github.com/Xpra-org/xpra/commit/83750ca62606878a01303257b87119ac4dca62ab)
    * [use a consistent shebang](https://github.com/Xpra-org/xpra/commit/93ccf524ea43c3fa3cc2355a109e87e8eb4c35e1)
    * [file upload deprecation warnings](https://github.com/Xpra-org/xpra/commit/f1b44902bbc1e44436fe7988f279f3da89c045c8)
    * [fail fast when testing decoders with junk data](https://github.com/Xpra-org/xpra/commit/cb7a7f1914aa8fceec960a17ba5816980c1d5636)
    * [documentation dead link](https://github.com/Xpra-org/xpra/commit/c3d3abb81127fb979c6f1293e37b9e924f1dc1c6)
    * [make version checks more robust](https://github.com/Xpra-org/xpra/commit/e1e409e579cc89f77a8a32d0ec9471aec272ff55)
    * [skip warning about missing amf gstreamer elements](https://github.com/Xpra-org/xpra/commit/5bc11fc6d4498651aefebf3926c28f1907daa92a)
    * [docstring: server configuration file applies to all servers](https://github.com/Xpra-org/xpra/commit/2a9207c5c3b1d9a654af12c90e414dbbec29300f)
    * [remove X11 keyword from desktop files](https://github.com/Xpra-org/xpra/commit/6ddcecafa00814f87350e47baa8e9ef1410151c5)
    * potential future issues: [variable name shadowing](https://github.com/Xpra-org/xpra/commit/c92dbbd92cfee64d2c29e7d0503ea6b2fa9a6603), [memoryview handling](https://github.com/Xpra-org/xpra/commit/c1e5c05803aedeba2b2b517b2f1fa07bf668c046), [strict type](https://github.com/Xpra-org/xpra/commit/add853dee27ed16d7d70c6a5309d1e921997c8a4)
    * [unused statements](https://github.com/Xpra-org/xpra/commit/4808053c37943048fe572233591de48ec59c8349)
    * [linter warning and consistency](https://github.com/Xpra-org/xpra/commit/717cc581f75f5960007619a6aa99defea7bfc8a1), [consistent return value](https://github.com/Xpra-org/xpra/commit/65f8e5d1ba9e5100e2531ffdb9f6576ea89c8a58)
    * [ignore 'noabstract' v6 bind option](https://github.com/Xpra-org/xpra/commit/72eb7a1861377fc93a163b820723b6f06555890d) + [fixup](https://github.com/Xpra-org/xpra/commit/2dc836e20c1dfba319bd5a2e5538ffbcc25ec667)
    * fix unit tests: [enable previously broken tests](https://github.com/Xpra-org/xpra/commit/d6b576a71f2de3041173302ff72d316e44dd92dc), [faulty backport](https://github.com/Xpra-org/xpra/commit/4c3de0c84e085fe57af06895c93e811332035f3c)
    * [downgrade Wayland warning](https://github.com/Xpra-org/xpra/commit/8467801befdc8ab8d747930a89f2c2488cf24291)
    * [explicit return statement](https://github.com/Xpra-org/xpra/commit/bd0b1f0c072853e1df6457fcb9a3450d0766dc84)
    * [warn users about deprecated syntax](https://github.com/Xpra-org/xpra/commit/4a1aaf1d64a924d9e67fe199b52715c87b8dc719)
    * [discord link had expired](https://github.com/Xpra-org/xpra/commit/f7557893fad97892a49d6fe4b727dd21a1883c36)
    * [codec self tests](https://github.com/Xpra-org/xpra/commit/cc759a64d8168796ccf1f8e755bb15829cabb5fb), [skip tests without sample data](https://github.com/Xpra-org/xpra/commit/08bb25365dd7c476d60b803a514a2d07724a4df6)
    * [pam authentication error messages](https://github.com/Xpra-org/xpra/commit/138f934a72758292bda5fc5230e5625dcdf0af1b), [twice](https://github.com/Xpra-org/xpra/commit/10c6be61a9965c2d1de30cdab61f7bb0dd241240)
    * [prevent future MacOS Gdk Pixbuf path errors](https://github.com/Xpra-org/xpra/commit/8ab8168732076f40c1a686462b2fa82969cb0b3b)
    * [log full details with all threaded initialization errors](https://github.com/Xpra-org/xpra/commit/4448bb0643c4b5aeea9f01533aa2a68202880c55)
    * [match function signature](https://github.com/Xpra-org/xpra/commit/534aec50b9d8b3646f2e4701983bc9b0a2a2895a)


## [5.0.8] 2024-04-03
* Platforms, build and packaging:
    * [MS Windows 'Light' builds](https://github.com/Xpra-org/xpra/issues/4100)
    * [compatibility with multiple "Windows Kits" locations](https://github.com/Xpra-org/xpra/commit/0fed808d376bcf441140609f5d73ac8069566a91)
    * [typo in MacOS bundle file](https://github.com/Xpra-org/xpra/commit/526b6fba3ac3398f810a400a78a5dae1f7df27a2)
    * [force include all brotli dylibs in MacOS builds](https://github.com/Xpra-org/xpra/commit/8a245ebb28ab6132e2c16b049ca35f5738521ab2)
    * [missing 'bcrypt' module](https://github.com/Xpra-org/xpra/commit/5dea9ba3ba5be1de4451b7d4835427e0e3621ad7)
    * [spng encoder build switch not honoured](https://github.com/Xpra-org/xpra/commit/d491e1689c2fc4c2cdcb67d9e9e6f996e0d8cc3d)
    * [Cython 3.0.9](https://github.com/Xpra-org/xpra/commit/6469e52b2ecf37c8a22c4bf0906e20b5e82f8ea9)
    * [aioquic 1.0.0](https://github.com/Xpra-org/xpra/commit/12ba4849a47f0c1f6b5f801126bc83b1c14dc2ef)
    * [include `pynvml` in MS Windows full builds](https://github.com/Xpra-org/xpra/commit/c4760301dd95939af3ea316f2f4b966cf83ab743)
    * [force include `zeroconf` in MS Windows builds](https://github.com/Xpra-org/xpra/commit/b50194dbabe6fd52c58f89963cbcd75b7386966a)
    * [MS Windows builds not waiting for input to close](https://github.com/Xpra-org/xpra/commit/cc0fc8b9cdeb8c897bf648554f13de0ff6d8d17b)
    * [MS Windows tools fail to run](https://github.com/Xpra-org/xpra/commit/1a05229c2001aa4b0cbdafd642e9b63d8b92196e) [due to incomplete environment](https://github.com/Xpra-org/xpra/commit/f6cd59c08b083b5a6189c09a3546f2dfc6354054) [and errors](https://github.com/Xpra-org/xpra/commit/2fb0e13fbb1cefcdee6e265f962eea7c20af85db)
    * [build info cannot be parsed](https://github.com/Xpra-org/xpra/commit/0ba4c924cd0d54dfb6db06f574bd48b91f46aa8b)
    * [debug builds on MS Windows](https://github.com/Xpra-org/xpra/commit/8d3b4edb7e3481bab3aeb6530604d02b9a7ba24f)
* Major:
    * [missing X11 clipboard events](https://github.com/Xpra-org/xpra/commit/5d07825aae44d7d7055ac4fbf44727c8e4c65c8b)
    * [OpenGL cleanup from correct context](https://github.com/Xpra-org/xpra/commit/8e9c4fdb755f7108af83db408540e469989911c1)
    * [nvfbc module loading errors](https://github.com/Xpra-org/xpra/commit/98d34bef02483fb878c813f6f1f9defa8df026c3)
    * [ensure NV12 streams can be decoded properly](https://github.com/Xpra-org/xpra/commit/79803454439839657025dfb7a090ec5426999443)
    * [client chooses the fastest colorspace conversion option](https://github.com/Xpra-org/xpra/commit/635d0f0fb6bc4a93a228aec4698c751380625de9)
    * [use libyuv to convert video to rgb when rendering without OpenGL](https://github.com/Xpra-org/xpra/commit/246685f1c0b6ee23c63eb90701da8e0e94afaeb4)
    * [`xpra top` hanging on start](https://github.com/Xpra-org/xpra/commit/2be7c41fdf44b4320960fa0450911e8a60028862)
    * [network manager unexpected datatype](https://github.com/Xpra-org/xpra/commit/d609f26301b8cd7264ab1b05d6ec1e5c192f31e1)
    * [disable ssl auto upgrades](https://github.com/Xpra-org/xpra/commit/32f62dcdffee2013ce9db9c7746da46ea7239567)
    * [freedesktop portal / remotedesktop should not use X11](https://github.com/Xpra-org/xpra/commit/5992663d24cbf650336c9b8560117abe0ae20dca)
    * password authentication issues with MS Windows and MacOS client: [dialog hangs](https://github.com/Xpra-org/xpra/commit/3698385172b03a8a56d4f95901d00728502d1d20), [client terminates](https://github.com/Xpra-org/xpra/commit/7bb55a06a18ef92c24fabe83a15e995fd5ea2438)
    * [mmap compatibility fix for older clients](https://github.com/Xpra-org/xpra/commit/e968d7f66c3065e47bd0ab87655a6d35202c553c)
    * [mmap client token errors should not be fatal](https://github.com/Xpra-org/xpra/commit/8ef274e97c3532d37948279c98eefadf173b0f2a)
    * [proxy draw passthrough stripping of unused alpha channels](https://github.com/Xpra-org/xpra/commit/7514d88e057b74e8f1ccab5e3ca5f8ff4c079b42)
    * [named pipe connections error](https://github.com/Xpra-org/xpra/commit/afdd06862d66c3825c2eff95cae1085c3f267419)
    * [MS Windows system tray initial icon may be lost](https://github.com/Xpra-org/xpra/commit/662c83816e18d55e0725bedb1afe18bce20f56f7)
    * [`xpra top` client failures recording backtraces](https://github.com/Xpra-org/xpra/commit/7be1883c232c35ae7b899c126b03e137bf6d1395)
    * [never wait for input in a subprocess](https://github.com/Xpra-org/xpra/commit/fc9e0dd459976f67eef63050e73e07a6483abaa6) [or in splash process](https://github.com/Xpra-org/xpra/commit/2c4aac4128d89c4b9ba6d0b5efb70f1ceaaa2635)
* Minor and cosmetic bugs:
    * [shadow server about dialog](https://github.com/Xpra-org/xpra/commit/328d0c4668ec981687b701888b1e2d41c25345d9)
    * [proxy instances signal handlers not firing](https://github.com/Xpra-org/xpra/commit/0cdb7a5427e1b8ebef70117ceb6686616aa558ff)
    * [log the prompt with u2f handler](https://github.com/Xpra-org/xpra/commit/154534049b8795e9a4a4fa9659ae56ca0b07076f)
    * [handle missing stderr more gracefully](https://github.com/Xpra-org/xpra/commit/f700a631ab3c8fae8e87c35f2edd7ba6253499e6)
    * [handle missing timeout value more gracefully](https://github.com/Xpra-org/xpra/commit/c403b497a71a25f43c53a2096b32a0394a099679)
    * [socket setup error handler logging incorrect](https://github.com/Xpra-org/xpra/commit/72664f72c8289e0a80bdef478870e9d018b4f512), [now extra safe](https://github.com/Xpra-org/xpra/commit/7b7b2f9405d4283b5bce764370ff10ec4d033cc5)
    * [socket authentication errors with malformed socket options](https://github.com/Xpra-org/xpra/commit/ffd8fa55b897362757d56863922f6484a6036c4d)
    * [avoid encryption errors during authentication](https://github.com/Xpra-org/xpra/commit/8a35b469fa09d44f15b7ef1c4382e298992b4cc3)
    * [support arguments with `xpra encoding` subcommand](https://github.com/Xpra-org/xpra/commit/99d8f739bdd6edf11c356649dc0299a32382b935)
    * [more tolerant option parsing](https://github.com/Xpra-org/xpra/commit/c9a9ff97e487ba1214d88a1e36542b3575021f99)
    * [avoid sending a warning notification for missing server log](https://github.com/Xpra-org/xpra/commit/3cf9ac8053d5e9eb6f756d34b854c96fcb5ad3ec)
    * [avoid showing warnings for options from newer versions](https://github.com/Xpra-org/xpra/commit/1ec821edf851e8f963b57bdb950cdcc5e56baa72)
    * [missing information from `net_util` tool](https://github.com/Xpra-org/xpra/commit/6b4aac358d783cf2222f4426dabf4c24ff6b59f7)
    * [only warn once per window when no video options are found](https://github.com/Xpra-org/xpra/commit/14b9ed386d736f2460dcb810e7a39d3891a0a40d), [same for csc](https://github.com/Xpra-org/xpra/commit/e1d570cc2ff363842d0dda1b76f6c48b9e78672f) [and when there are no options to choose from](https://github.com/Xpra-org/xpra/commit/f8dfbedbd1fd9ed4e271b20511f9c7a5b50387e1)
    * [update discord link](https://github.com/Xpra-org/xpra/commit/9ebcae3a2658fb9484f3513ab7579f93996ac05c)
    * [more detailed connection error messages](https://github.com/Xpra-org/xpra/commit/972ed49ec4587d1614350087fa78a69ba9e9e583)
    * [point to the pyxdg bug information when theme parsing fails](https://github.com/Xpra-org/xpra/commit/6999c96013ccb436730f9545341de2adb4dcd59a)
    * [typo shown in display information](https://github.com/Xpra-org/xpra/commit/58374bb5f5370da0b74eaf1af7b78d5bd97c4099)
    * [libvpx decoder use correct (unused) pixel format constant](https://github.com/Xpra-org/xpra/commit/d0a03ae2b464aabe1d3abc49614e3fd242c86a76)
    * [ignore dimensions rounded up in openh264 decoder](https://github.com/Xpra-org/xpra/commit/94da7c67aa77309529a5ddbb96aad1de05f7a3a0)
    * [some tests can take long on a slow CI run](https://github.com/Xpra-org/xpra/commit/1d9e881b889f93757128169204e571c80917b8ce)

## [5.0.7] 2024-02-28
* Regressions:
    * [typo causing CUDA codecs error](https://github.com/Xpra-org/xpra/commit/062be135cbe8298ba775582b70e5731e04a16d3f)
    * [window content-type guessing broken with Python < 3.8](https://github.com/Xpra-org/xpra/commit/8141bcfa20df314f11f7b60d770ee3c6a22aeacd)
    * [X11 clipboard backend broken with Python < 3.9](https://github.com/Xpra-org/xpra/commit/0ca51f1848e7d1ce5eaa99f2b6937b45555083b6)
* Platforms and packaging:
    * [installation path for manual pages on FreeBSD](https://github.com/Xpra-org/xpra/commit/94b0acb64b7bf0a5a866c1c10eb30ff7f9e36fec)
    * [comtypes clear cache script executable was moved](https://github.com/Xpra-org/xpra/commit/21736d6616fbb6d9743d266873498343958af78d)
    * [missing RPM soft dependency](https://github.com/Xpra-org/xpra/commit/43ffeeaed02438e4d3556028feb07f18e28ce179)
    * [MacOS builds missing libxxhash](https://github.com/Xpra-org/xpra/commit/ae7a4e4c55fcda3ccc584ef8517fe55d3091b24e)
* Major bugs:
    * [missing feature flags](https://github.com/Xpra-org/xpra/commit/ddeb2f8e64b5fb31bd850e3f8616450f145ad436)
    * [client wrongly claiming file download is not available](https://github.com/Xpra-org/xpra/commit/a0642cc106c5f2a8b852bcd117e47cb558600c47)
    * [desktop geometry changes can't clamp windows to display area](https://github.com/Xpra-org/xpra/commit/80a82f1962d4b6b1f7f4899fc75b42e5ecf24e29)
* Minor and cosmetic bugs:
    * [don't try to query the Linux distributions on MacOS or MS Windows](https://github.com/Xpra-org/xpra/commit/742ee0eedd9b639cf4e63b4c3a2c9a7114587543)
    * [use namespaced capabilities check](https://github.com/Xpra-org/xpra/commit/337452695f39e1cf865095c17ffe2a84b9c0f58e)
    * [potential undesirable side-effects](https://github.com/Xpra-org/xpra/commit/f124abd66095335442cc1c90eba3f3550ce33bfe)
    * [method signature consistency](https://github.com/Xpra-org/xpra/commit/797ec70749b2efe261a41234103e0bf6757c0e01)


## [5.0.6] 2024-02-22
* Major:
    * [windows misplaced on screen, moving unexpectedly](https://github.com/Xpra-org/xpra/commit/bb25b6c8ac4195ab140d7772dba2b05cbe272791)
    * [windows wm-state synchronization issue](https://github.com/Xpra-org/xpra/commit/479f8bea673058fc607d5428de8a80c1a0810dad)
    * [blurry text due to downscaling](https://github.com/Xpra-org/xpra/commit/fc89e36c0b11bb9cc5cb7a28706787e66ee911fb), [faulty commit](https://github.com/Xpra-org/xpra/commit/1aaf6ca3a95390cf3a521b08b2298ded8f96026d), [video size constraints](https://github.com/Xpra-org/xpra/commit/1c532fa30582276ac03f8bea51727446cda47d72), [colorspace subsampling](https://github.com/Xpra-org/xpra/commit/142df20cbc0e0d3eca8c53eb1d96d89b9c8f1b3a)
    * [window model setup delays](https://github.com/Xpra-org/xpra/commit/f0616a69072397727613a40ebbcd3e619930181f)
    * [empty menu data](https://github.com/Xpra-org/xpra/commit/953635c487501d8e57a12fe1414e2042d989794d)
    * [X11 properties clash](https://github.com/Xpra-org/xpra/commit/53208fcd6ca5dc4c2951ad3f417a16e3abb87c80)
    * [try harder to handle unexpected clipboard data formats](https://github.com/Xpra-org/xpra/commit/2e84b222886b75ebfd7eb813e4de8d2fea077943)
    * [`run_scaled` and `attach=yes` errors in virtual envs](https://github.com/Xpra-org/xpra/commit/eda6327a6aee64e03c3be84374c3f4dc1f9e1459)
* Platforms and packaging:
    * [missing ffmpeg RPM dependencies](https://github.com/Xpra-org/xpra/commit/c6cfb44002509286ac0e3bed772041db5047b276) and [stricter submodule dependencies](https://github.com/Xpra-org/xpra/commit/5abff5310795bfbc357420854db0570e96fc225c)
    * [updated service file for DEB packages](https://github.com/Xpra-org/xpra/commit/915b2e699999e36e0120ed69fb6a3af413cfa64b)
    * [remove duplicated systemd service and socket files in DEB packages](https://github.com/Xpra-org/xpra/commit/3692506a7288637e007933a6a234cfb179a18281)
    * [enable OpenGL with Intel drivers](https://github.com/Xpra-org/xpra/commit/2a699ce0a51d762acaf6b12c20b4ee0498f0f9af)
    * [add Ubuntu Noble](https://github.com/Xpra-org/xpra/commit/86a214b69a6b5db0e7a167e9c7b63b9994383e05)
* Minor:
    * [OpenGL error due to numpy import race condition](https://github.com/Xpra-org/xpra/commit/06bba8c7c179595bf15b1388dba915ef7f134649)
    * [`start-child-late` cannot be used alone](https://github.com/Xpra-org/xpra/commit/3049d0b7e7e6be7d951f841eea851d5b4c7af32c)
    * [builtin ssh server connection errors when display is specified](https://github.com/Xpra-org/xpra/commit/eb2d15e7e681478dca239e729e00d32c532880b1)
    * [ssh upgrade errors when unavailable](https://github.com/Xpra-org/xpra/commit/7cd8a6363fa99aededdeaf9cddda068b6e179bba)
    * [blacklist some more greedy clipboard applications](https://github.com/Xpra-org/xpra/commit/38b1b48b630fd748cde02810d8da139b1fb9d224)
    * [pixel buffers we allocate are read-write](https://github.com/Xpra-org/xpra/commit/20007f166aec707cefc4e0492d4ee8830f6a4113)
* Cosmetic:
    * [OpenGL probe error messages](https://github.com/Xpra-org/xpra/commit/925d8a04cec82a780fe366760346c51a0cddab06)
    * [Cython3 warnings](https://github.com/Xpra-org/xpra/commit/ca70ab859050a9b405382f35efd339d0105dadc2)
    * [avoid mDNS errors, log message instead](https://github.com/Xpra-org/xpra/commit/933917d2f03dea31d680baa05b5096841e717f02)
    * [use the expected data type](https://github.com/Xpra-org/xpra/commit/8843b7db531b1f018fa7de1038710937a71b9a0a)
    * [remove unused device context](https://github.com/Xpra-org/xpra/commit/9656a14a46e323e5bf3b6cbf73532b02b5002d5a)
    * [silence spurious messages sent by wine applications](https://github.com/Xpra-org/xpra/commit/962ad206d3efed56169883a4f06ce2fcf503e3ec)
    * [gst-plugin-scanner packaging for MacOS](https://github.com/Xpra-org/xpra/commit/28c380c941b5b5da205acafe6b1e09bf574342f8)
    * [ffmpeg decoder error handler could fail during self tests](https://github.com/Xpra-org/xpra/commit/46e9d6fd12aa1ba011ffe2e002cc492dc38a07dd)
    * [notification errors during shutdown](https://github.com/Xpra-org/xpra/commit/ba74801e3c4acb815b8eeee64b423d48589ed6ec)


## [5.0.5] 2024-02-05
* Major:
    * [race condition in OpenGL initialization](https://github.com/Xpra-org/xpra/commit/498b8f6c7da012bb555fb087ead26ba218701ada)
    * [http socket upgrades for slow requests](https://github.com/Xpra-org/xpra/commit/c2935630d505b11752c2851dc0f1b1590c2788eb)
    * [window state attributes wrongly set to False](https://github.com/Xpra-org/xpra/commit/e46192fb428ac1b32c3f113fc40e0cf7cf69ad7b)
    * [window geometry not updated](https://github.com/Xpra-org/xpra/commit/5feb4058d954e501f39175f90ed1236d847e3767), [not restored](https://github.com/Xpra-org/xpra/commit/e1509849ec63ff24d6ce2222ec1323046a71b972)
    * [handle pointer events missing the shadow window id more gracefully](https://github.com/Xpra-org/xpra/commit/98f38bd8105ca7ec17e39872915542aa305c0cec)
    * [socket setup failure cleanup](https://github.com/Xpra-org/xpra/commit/d6294f80efa635cfe57b492440b5c9eb30363b7b)
    * [ensure text is always lossless](https://github.com/Xpra-org/xpra/commit/0bc563c31ea6e2ad011a6947662cfa7f9415d3c0)
    * [fixup DPI backport for Xvfb users](https://github.com/Xpra-org/xpra/commit/30c7cfa5a9f119aac300b5652d3d545f9ca799cf)
    * [window max-height nor honoured](https://github.com/Xpra-org/xpra/commit/824d488b11d78df580657181fcb10d8021c6c78d)
    * [tools and examples hang on SIGINT](https://github.com/Xpra-org/xpra/commit/6b83eab06d691adcfcf6f7d9d0618aded1d0b774)
    * [start-gui error when specifying a port](https://github.com/Xpra-org/xpra/commit/8d01102dc2b60e6169acfb346b0f5e2af82f0fef)
    * [broken about dialog](https://github.com/Xpra-org/xpra/commit/356dda7aa3fcba9a1ca23e2875dc6ee1c6f13009) [with shadow servers](https://github.com/Xpra-org/xpra/commit/99e227e945dd9ad309c477212621fbddb6eedaf5)
    * [missing shadow server system tray](https://github.com/Xpra-org/xpra/commit/453dd544dc6d3efa4518e8922f1139a46cedab58)
    * [workaround missing icon size config](https://github.com/Xpra-org/xpra/commit/efcb254105600987b06539b9929c66911f9713b5)
    * [workaround paramiko error with agent keys](https://github.com/Xpra-org/xpra/commit/55f2cc6787bfc6f57e1577a803a4cd33a1addbe1)
    * [incomplete desktop server startup with `Xvfb` backend](https://github.com/Xpra-org/xpra/commit/c2dfebc63caa9d85517a2b8f8e6158d1ffeb32f8)
    * [packet encoding error on client control command](https://github.com/Xpra-org/xpra/commit/8f02457af98ab3d45845fa8d6dea23e0d577f5bc)
* Platforms and packaging:
    * [appindicator system tray not shown](https://github.com/Xpra-org/xpra/commit/fff396758291432af40e7d26f12ef3a2615487fd)
    * (Free)BSD compatibility: [don't build pam](https://github.com/Xpra-org/xpra/commit/dd80ab2f02fbd2f4e72165c99012d072a5373952), [do build drm](https://github.com/Xpra-org/xpra/commit/4753b487a56b16d065b868ababc8a27e99e025d0)
    * [don't expand environment variables in config files](https://github.com/Xpra-org/xpra/commit/72bd4497731089fed87393dca9d265e889c7877c)
    * [MS Windows console title was not set](https://github.com/Xpra-org/xpra/commit/70b8e54bafb2444d88c050334ce4e300d81940c1)
    * [close log files to avoid warnings on MS Windows](https://github.com/Xpra-org/xpra/commit/bb77dfc46902ee7e2626d53c688434028fc48610)
    * [only build CUDA kernels if needed](https://github.com/Xpra-org/xpra/commit/c388d6930de7d49da768fca5f27ed39b262c7013)
    * [allow building CUDA kernels with clang](https://github.com/Xpra-org/xpra/commit/6ceb529c46e88a0712abaa8174f5f212ec89af8c)
    * [RHEL8 pycuda 2022.1 patch for compatibility with CUDA 12.x](https://github.com/Xpra-org/xpra/commit/dd3e514f92269ba9cf0c967c576aea59af23a2a0)
    * [libproc module compatibility with GCC 14](https://github.com/Xpra-org/xpra/commit/ffb5abfce7217b49ddd8045e4e83275c34c136c4)
    * [use the correct enum type for nvfbc constants](https://github.com/Xpra-org/xpra/commit/5d962187d75bfe1c77a62e3c5971668c8f444a45)
    * [pycuda 2024.1](https://github.com/Xpra-org/xpra/commit/513d3292bd0181714d9e5778bb857ffb0a0621b2)
    * [Cython 3.0.8](https://github.com/Xpra-org/xpra/commit/3b77de331d8978c5c999c2115dd3fcd75d22632f)
    * [aioquic 0.9.25](https://github.com/Xpra-org/xpra/commit/a026d41f783f53c222b4e0bb16d89fc29382a0e7)
    * [disable auto-dependencies for python modules](https://github.com/Xpra-org/xpra/commit/51cfb4e6bba2db4f4d0237eab0f52bbe1e7c6c04)
* Clipboard:
    * [honour client specified order of clipboard preferred targets](https://github.com/Xpra-org/xpra/commit/0da4d81741fed523e1d356f8ab3fce209cdbd221)
    * [allow `text/html` as `text` target](https://github.com/Xpra-org/xpra/commit/eaf2e5472b7a3f775d2fd3a6944804eaa833f268)
* Minor:
    * [restore chosen window size](https://github.com/Xpra-org/xpra/commit/fc18ad92f3b37d1adf35411fb7ffb2f97bf4a132)
    * [ensure each socket gets its own options object](https://github.com/Xpra-org/xpra/commit/8d4521c179dce07d0ddf6009cc3efd04af26a9a4)
    * [correctly set XImage buffers read-only](https://github.com/Xpra-org/xpra/commit/6b0c1777597ab8859605cc47a7ba0601f82ef058)
    * [cleanup errors with RFB connections](https://github.com/Xpra-org/xpra/commit/4e047e4d388e7c532bcc2473072f289a2fbb0049)
    * [close file descriptors of pinentry subprocess](https://github.com/Xpra-org/xpra/commit/e55c8969e8dbfc967f0c6bfbf768c562c92f8915)
    * [don't wrap our own exceptions twice](https://github.com/Xpra-org/xpra/commit/bc4a33642923ca7274971678325a1a570076b156)
    * [don't try to print a size we don't have](https://github.com/Xpra-org/xpra/commit/93c62c9229e6faf995ac5791549d0ef55a90280e)
    * [support multiple attributes with `bind` options](https://github.com/Xpra-org/xpra/commit/eaf2e5472b7a3f775d2fd3a6944804eaa833f268)
    * [make iconify delay configurable](https://github.com/Xpra-org/xpra/commit/a9441fb82745fb6cd8e0c2f2d085a1c1a7e3fe4c)
    * [update trixie and sid libavif dependency](https://github.com/Xpra-org/xpra/commit/4ba44484eb9d8a3225d11d823f4ea57794dd08b7)
    * [simplify regex syntax](https://github.com/Xpra-org/xpra/commit/8cf8494340a26a1149ee7f273eaa27c1e62a0aab)
    * [pillow unit test failure with versions >= 10](https://github.com/Xpra-org/xpra/commit/1275e3caac610c94174a11862bf7fe61cc8b9f6c)
    * [documentation dead links](https://github.com/Xpra-org/xpra/commit/c322b77f1c3d7d2d95c9ff94362ee1c16cc3e022)
    * [don't import X11 modules under Wayland](https://github.com/Xpra-org/xpra/commit/e896c23e73fc7b4496b66413aafa64296a72dcc5)
    * deprecation warnings: [ssl constants](https://github.com/Xpra-org/xpra/commit/111ec73e442569bc949644a0894340125f94f82e), [re.sub](https://github.com/Xpra-org/xpra/commit/119e58de1a687ba75d917da936bce33d1d4a7d63)
    * [skip test failing on CI](https://github.com/Xpra-org/xpra/commit/0bea6b21193cceecddb892e9f2ab2caa4dce13bd)

## [5.0.4] 2023-11-28
* Major:
    * [missing flush marker with some scroll screen updates](https://github.com/Xpra-org/xpra/commit/ff36bc1a085c6caca3bdb95791c5001c3c6909bb)
    * [fixup tray backport regression](https://github.com/Xpra-org/xpra/commit/6631cfe8b8c228894cd93b679d7ed78ef5715f81)
    * [signal watcher backport regression](https://github.com/Xpra-org/xpra/commit/96f0351ba1dbc5c1dee6bfcf760a4350b2d2b9c0)
    * [exit signal watcher on errors and hangups](https://github.com/Xpra-org/xpra/commit/713009f869468898857038051cffc6eb59f74f45)
    * [avoid menu and input device errors when client is not set](https://github.com/Xpra-org/xpra/commit/ce25a2468194d1b25472562acde6070419fcad28)
    * [ensure the content-type is initialized at least once](https://github.com/Xpra-org/xpra/commit/608bf55e822f78eabfd59f5a4f44929e71dad679)
    * [ensure all encoders are initialized before choosing an encoding](https://github.com/Xpra-org/xpra/commit/dd808947a7ceff1524adae44bc930636eef7a4e7)
    * [video modules lost after initial connection](https://github.com/Xpra-org/xpra/commit/8217fabfcee476c2f44ae78cde1c718ee609157f)
    * [OpenGL crash warnings on MacOS](https://github.com/Xpra-org/xpra/commit/2e4248d5a61a20b81d4f39dce85464689136c69c)
    * [client error if xpra-x11 is not installed](https://github.com/Xpra-org/xpra/commit/5c131462755e004d74126e06db0dd3cd9555fe1a)
    * [DPI fix for older distributions](https://github.com/Xpra-org/xpra/commit/79f183744a16b1606c43baeed67134375ecdd3cb)
* `start-gui` fixes:
    * [display number ignored](https://github.com/Xpra-org/xpra/commit/db7f6f4ea1530e7b6c901b2b0e44f00271c9d8b6)
    * [exit-with-children can't be unchecked in start-gui](https://github.com/Xpra-org/xpra/commit/98ee5a6f26cdac6bf62166b1ceca522b02f6fca4)
    * [port number always specified but not validated](https://github.com/Xpra-org/xpra/commit/bb1c06d77370bd6b4a94e28572311368c2c23817)
* Platform and packaging:
    * [pycuda 2023.1](https://github.com/Xpra-org/xpra/commit/f7b18df18e0f1b1a6134f15b2760d94e764b1b48), 2022.2.2 for RHEL8
    * [Cython 3.0.5](https://github.com/Xpra-org/xpra/commit/3a46ee575f0147f6e4ccc00bab27321825709ab1)
    * [also use Cython 3.x for Debian builds](https://github.com/Xpra-org/xpra/commit/6c11d25ca987e5cb70f5977f34760da169c4605e)
    * library updates: [aioquic 0.9.22](https://github.com/Xpra-org/xpra/commit/8070b632eb7f022d9529c1c7ca1e50842c447fef), [pylsqlpack 0.3.18](https://github.com/Xpra-org/xpra/commit/98e986ee177cfae7a2d11f9ff3db39db555755b6) + [python-wheel](https://github.com/Xpra-org/xpra/commit/a3a4fbefeb3f6a2761eb058a179b3e9895b14ad7) 0.41.3 (0.33.6 for Python 3.6)
    * [C functions cannot raise Python exceptions](https://github.com/Xpra-org/xpra/commit/55e4fe2450aaf96ba049f9b9e825e3c77d6b6b22) + [reorder](https://github.com/Xpra-org/xpra/commit/0618f163b0e6c9102be56b6fd02eef614baae19d)
    * [MacOS pyobjc warnings](https://github.com/Xpra-org/xpra/commit/c17caa0cb25f68fa8a75c975fe886504b142c9a6)
    * [workaround py2app failure](https://github.com/Xpra-org/xpra/commit/262cffc6b3745c68db8b528405652ed1ca709bc8)
    * [bogus date in changelog](https://github.com/Xpra-org/xpra/commit/1562623a170cce00cf286a403bc0e5773aa05369)
    * [improve session type detection](https://github.com/Xpra-org/xpra/commit/1233e0ce1100a7b82454cad728c08dc26cf35ac1)
    * [notification backend order](https://github.com/Xpra-org/xpra/commit/8b3d31cab9220facc917b60d5db971c016638d0e) [and cleanup](https://github.com/Xpra-org/xpra/commit/a09f80b563822990619fb51e973b8a371b3a2e7f)
    * [DEB packages should not rely on transitive dependencies](https://github.com/Xpra-org/xpra/commit/a403a271a80a5d7b5468d9b9a27303188b83547d)
    * [ignore some transient CI failures](https://github.com/Xpra-org/xpra/commit/47cb8affd6a3d59d26392697e1d98fe8ef3a8b00)
    * [use latest Cython with CI](https://github.com/Xpra-org/xpra/commit/cecc5b2e624c78166a79cdac51d14adf896dcd9a)
    * [ship systemd service if building socket activation](https://github.com/Xpra-org/xpra/commit/b2b20f260bfae9951f0f803c1c19a124e1968297)
* Minor:
    * [shortcut out when signal watcher has already terminated](https://github.com/Xpra-org/xpra/commit/f3e922181e5fbabc63f778e9a7d6fe4a7809b6f7)
    * [move-resize test tool broken](https://github.com/Xpra-org/xpra/commit/5e79b41a830203412566b4f3c9fa4119a9a441a6)
    * [safer handshake calls](https://github.com/Xpra-org/xpra/commit/7927461b0532ebc29ba167d7d87addcd66a802f7)
    * [use absolute script paths when re-connecting](https://github.com/Xpra-org/xpra/commit/2d1dc323fadcc97df73472123abf7a680b22ef59)
    * [avoid errors with clients sending packets to disabled subsystems](https://github.com/Xpra-org/xpra/commit/9771a6853f512c7e8a188b06ef522c9ee6c38f75)
    * close all sockets [on errors](https://github.com/Xpra-org/xpra/commit/e07d80a42d9ab380fb440a5a77bc15efe8c0c480), [on permission errors](https://github.com/Xpra-org/xpra/commit/28c6dd726712f58aae67ac0b7bc03ecfba12f554) and [on exit](https://github.com/Xpra-org/xpra/commit/04a76b6a3b6a77eccafbbf34c8a293778302fb88)
    * [ssh error connecting to some hosts](https://github.com/Xpra-org/xpra/commit/c00d9328ce57d4a95006f4ff7a9a69e05688d168) + [fixup](https://github.com/Xpra-org/xpra/commit/493477056fc6148ed551f62bbd93815064a18752)
    * [type safety](https://github.com/Xpra-org/xpra/commit/e490532251abf2a74c8683daa25b3df6f77465f4)
    * [don't include empty key event in debug list](https://github.com/Xpra-org/xpra/commit/f91e7d261418117e7e03430bb9259b0c37f3e41d)
    * [parsing large numbers without units](https://github.com/Xpra-org/xpra/commit/a34c33573fddf319ec4f6a0e2a0c9f0b75396c45)
* OpenGL client accleration:
    * [honour opengl=force option](https://github.com/Xpra-org/xpra/commit/b869ba0466cfe3fdeabb7815fee12d1cb6ab8f65)
    * [X11 OpenGL context manager is not consistent](https://github.com/Xpra-org/xpra/commit/e73187fc427aae60041ebd1dc65582790875d59b)
    * [remove confusing unused method in OpenGL client window](https://github.com/Xpra-org/xpra/commit/8a4151ebcf07b9a88ace25ff0a163c77ad1db356)
    * [OpenGL debugging errors](https://github.com/Xpra-org/xpra/commit/2a45a2e44449fecd1b96a38f26bd89227be440bb)
    * [opengl test window misnamed](https://github.com/Xpra-org/xpra/commit/62784a7510de5c37b8a15e035040a08106d29151)
    * [try harder to exit more cleanly on error](https://github.com/Xpra-org/xpra/commit/fe64f343f149dc8e2b7a82aeaeef54bdcb8d122d)
* Cosmetic:
    * [check all icon directories](https://github.com/Xpra-org/xpra/commit/83ab6c5f21e6546cd459ffb77b70968dbdc1e935) [and themes](https://github.com/Xpra-org/xpra/commit/ec6100cb8a3c12b57c17b9e21d62fecf8209a4a4)
    * [silence GStreamer warnings with auto source](https://github.com/Xpra-org/xpra/commit/65ec4317a663a56af93890f4b76d48b7fea76ccf)
    * [outdated email address](https://github.com/Xpra-org/xpra/commit/a994becb5c3e2fbd0561d1296814f84e1770084a)
    * [don't warn if `avif` decoder is missing](https://github.com/Xpra-org/xpra/commit/3d919bd6e7f7fe1018800ced86641e48151be900), [same for encoder](https://github.com/Xpra-org/xpra/commit/f829661b87631ceac56522d6260bcfe6ceb7c4df)
    * [add newline to clear stdout](https://github.com/Xpra-org/xpra/commit/00427351e049cab6d1c585be7df366248858321d)
    * [extra `%` in tray menu](https://github.com/Xpra-org/xpra/commit/7bc5d5b6059c9c785d72794b945c340ece28486b), [twice](https://github.com/Xpra-org/xpra/commit/1cf818034cf64b12747b0ced126e1f955dfb9c9c)
    * [show failing script](https://github.com/Xpra-org/xpra/commit/a9f0cc35d94e274d4830d320ccc89f959cc2c6d7)
    * [silence deprecation warning](https://github.com/Xpra-org/xpra/commit/6c98ef1c9d8fac81b5ea43e33971b398c9d51e07)
    * [weird Debian changelog format warning](https://github.com/Xpra-org/xpra/commit/58914b4a8653e2af5172a50177bca53d9b0fe677)
    * [man pages fixes](https://github.com/Xpra-org/xpra/commit/1d22676e6d19d47978dd4ca01056b1a037be18bd)

## [5.0.3] 2023-10-05
* Major:
    * [client signal watcher not starting](https://github.com/Xpra-org/xpra/commit/0b1841d6eecbd3af6e11ec5aa79749ec3f3f9910)
    * [pipe and process leak with signal watcher](https://github.com/Xpra-org/xpra/commit/2de2a52e03f40b071fbe84f700d65fd504e0945d)
    * [jpeg decoder invalid image attributes](https://github.com/Xpra-org/xpra/commit/b9cfef343242551d6c338f8a0647a55de3862f89)
    * [video encodings setup error](https://github.com/Xpra-org/xpra/commit/9b365b6fe8aac954de4b85f43ffb43feb920e428)
    * [nvjpeg encoder downscaling](https://github.com/Xpra-org/xpra/commit/a8fcdbc8f292ae8b9fef7f71964cc43a290fd8a3)
    * [prefer native system tray on MS Windows and MacOS](https://github.com/Xpra-org/xpra/commit/e5500b0e0bb3688ad9223db2ecad3e7aff04037d)
    * [avoid None value errors with non-native MS Windows system tray](https://github.com/Xpra-org/xpra/commit/16285978c2c4a5f39202d5121c21ac8531d589b7)
    * [about dialog crashes on MS Windows](https://github.com/Xpra-org/xpra/commit/71011e197f689b69d1a305c71f52b3535357659d)
    * [clipboard size limits](https://github.com/Xpra-org/xpra/commit/b9d8fc7de69e8675a9ac50fe534fd9f1a2d34d60)
    * [splash screen hangs](https://github.com/Xpra-org/xpra/commit/36298db710a42e6744cb9015eb16bad364f85a24)
    * [remove x265 encoder](https://github.com/Xpra-org/xpra/commit/ec12676d68585a926109f1e8d4783f83f4d7768b)
    * [start gui error in encoding dialog](https://github.com/Xpra-org/xpra/commit/e404fb6120afe29cbcd90776fa3031e72f083bca)
    * [dialogs causing crashes on some platforms](https://github.com/Xpra-org/xpra/commit/4666c19a8887299642cd191871064953768d1c1e)
* Compatibility fixes:
    * [build against deprecated NVENC presets](https://github.com/Xpra-org/xpra/commit/2914c8a972f12398d3654f8a9c4b93693e3325b4)
    * [webcam geometry](https://github.com/Xpra-org/xpra/commit/d0dd98591b82f6602d47ac80e17f342e867da77b)
    * [handle microphone option with both state and device](https://github.com/Xpra-org/xpra/commit/cc5e00184423ccb0fab446f4a57bcbd9d99084d6)
    * [MacOS regression](https://github.com/Xpra-org/xpra/commit/597ec5cc7d95bdbfec76b564482452fec78082c1)
    * [all clients support menu updates](https://github.com/Xpra-org/xpra/commit/c1618738fd6fe4ec24c86c08e63e6e75743a1571)
    * [relative pointers](https://github.com/Xpra-org/xpra/commit/4977c28e1ca15a5ef99c1e02f7db4d7471015579)
    * [don't expose numpy datatypes](https://github.com/Xpra-org/xpra/commit/20e5b390438327c56a1db4320c4af556bd7d1169)
    * [still show tray menu without qrcode module](https://github.com/Xpra-org/xpra/commit/276e2282f46f8924e4bc781199ecac4a5f077831)
    * [missing utility wrappers on MS Windows](https://github.com/Xpra-org/xpra/commit/db63e1c8ab4cfe34b148cafc1106dc54047603cd)
* Minor:
    * [fps counter](https://github.com/Xpra-org/xpra/commit/72c31b74e7027ca2522ee4441dab786e312fcc82) [rounded to an int](https://github.com/Xpra-org/xpra/commit/0db7d41005081b5b85b153302a076fb8471e185e) and [dpi values](https://github.com/Xpra-org/xpra/commit/b9cfef343242551d6c338f8a0647a55de3862f89) should use integers
    * [debug logging of Cython modules](https://github.com/Xpra-org/xpra/commit/25805dfe03330e0409ec2b145a8544bb60a04717)
    * [missing OpenGL toolbox on X11](https://github.com/Xpra-org/xpra/commit/0f1435648f968fdda3b0625b82e2e42834773035)
    * invalid type for [max-display-no](https://github.com/Xpra-org/xpra/commit/09d455068a5c9aabe51012ba7dc119af7acf77ba), [watcher pid](https://github.com/Xpra-org/xpra/commit/3bb7d93e1adcd580f9c68047466f420d36dc90b4)
    * [catch invalid display names earlier](https://github.com/Xpra-org/xpra/commit/f9553d961824c87619566964d6358ca640f1bcbc)
    * [re-attach error on MS Windows](https://github.com/Xpra-org/xpra/commit/597ec5cc7d95bdbfec76b564482452fec78082c1)
    * [ensure all required modules are included on MS Windows](https://github.com/Xpra-org/xpra/commit/971d0745b9192c1c124f8fbe8a2e859162ed0823)
    * cosmetic: [typo](https://github.com/Xpra-org/xpra/commit/650e63dc78b98bf71e46f9e647e7d7b9aadb9919) and [bad formatting](https://github.com/Xpra-org/xpra/commit/a8fcdbc8f292ae8b9fef7f71964cc43a290fd8a3), [missing subcommand](https://github.com/Xpra-org/xpra/commit/c55b9989ef104a78de907610b03911702ce8d0b0), [deprecation warning](https://github.com/Xpra-org/xpra/commit/b6f423accefee16f0743578fb67a4f22ee3cbfde), [debug logging](https://github.com/Xpra-org/xpra/commit/5fe516077a9097ee785dd8edb190b6470221cdda)
    * [skip unnecessary processing if bind=none](https://github.com/Xpra-org/xpra/commit/9907947948bc091798e0bdd76c3ab03cf3f1c10c)
    * [avoid uinput warning](https://github.com/Xpra-org/xpra/commit/6307c3f785a1415b0d2948056766bea1dd4c40dc)
    * [incorrect start command request parameters](https://github.com/Xpra-org/xpra/commit/7992dc4abd35195eb799e330bc77d7445b6b8067)

## [5.0.2] 2023-09-13
* Major fixes:
    * [missing x264 encoder in DEB packages](https://github.com/Xpra-org/xpra/commit/b8735c8b53ac908424f4c9092362ccda270a1138)
    * [unusable vsock module](https://github.com/Xpra-org/xpra/commit/b1264a7a3418936c3bed6622c346bc2283c94aa9)
    * [start-after-connect was broken](https://github.com/Xpra-org/xpra/commit/3cf4a83336909d0408caa0d41eff141ae2447532)
    * [Overflow error in MS Windows hooks](https://github.com/Xpra-org/xpra/commit/c46e59398b7833d3f0710d63abada57e9e6b6af5) + [fixup](https://github.com/Xpra-org/xpra/commit/7e2983c0ef73f49dd11684cb3f4af07b739706d6)
    * [notification packet errors due to missing icon](https://github.com/Xpra-org/xpra/commit/57c5baadc5b9f5abc4aa74c669a6632451cd0f44)
* Minor:
    * [workaround for ancient versions of Pillow](https://github.com/Xpra-org/xpra/commit/35f77d9d9dce78d569f453608aea8b5e712aeb25)
    * [log warnings with custom cursors and OpenGL backend](https://github.com/Xpra-org/xpra/commit/563339b8ba42f49a2b5c2bbd62f340d9d3332188)
    * [don't send cursors without a matching encoding](https://github.com/Xpra-org/xpra/commit/fdf79586e6d39e746e67fd291ec9e79524e2f115)
    * [better packet namespace compatibility](https://github.com/Xpra-org/xpra/commit/3e21c8a93ad6bd6390fc87f25cc0f0445a60e45a) + [simplify](https://github.com/Xpra-org/xpra/commit/f60bebd9dbfdfeec6dac4e50d3176166d4c27e90) and [fixup](https://github.com/Xpra-org/xpra/commit/aed7a3791db1cd8e38a2d18a89ce2be3ba18eed6)
    * [only warn once about unknown NVENC presets](https://github.com/Xpra-org/xpra/commit/5baf3e79e9dffadf19521c6e02df2b357ba1a508)
    * [skip unused codec information](https://github.com/Xpra-org/xpra/commit/d10838e9bb5ea9cc4f58490cdb5763bd4e635569)
    * [preserve 'proxy-video-encoders' in remote command lines](https://github.com/Xpra-org/xpra/commit/845fed7586fb600d5d744cf1be146aa8d3c57f5f)
    * [don't setup ssh agent forwarding directory when proxying](https://github.com/Xpra-org/xpra/commit/42ad1f53666a794d7aee7d0f687a59c4ab71d6f4)
    * [handle 'help' for video options](https://github.com/Xpra-org/xpra/commit/a35b5eeb0811352402babf8a0a5c13c255ba3e67)
* Compatibility fixes:
    * [bandwidth flag](https://github.com/Xpra-org/xpra/commit/1a01b86baa78bb67acea2dc21aecb6969f9aee65)
    * [encryption namespace](https://github.com/Xpra-org/xpra/commit/5f576be65d45ef9425df9bd6410a4d7e4bbc06fb)
    * [encoding namespace](https://github.com/Xpra-org/xpra/commit/3ba907a061151684b4628c930d7feaed3d63c421)
    * [script syntax](https://github.com/Xpra-org/xpra/commit/0f036f0b7f356e04e838eaf1b1c68587f16a3c06)
* Proxy:
    * [errors in threaded mode on second connection](https://github.com/Xpra-org/xpra/commit/b502efe919499700eb74550a013a2372916424a0)
    * [compressed picture data forwarding problems](https://github.com/Xpra-org/xpra/commit/7b92b21b31c08d64f26ef20eb284d0eb90606c70)
* System Tray:
    * [empty system tray menu on some platforms](https://github.com/Xpra-org/xpra/commit/b76cca2278b98c3bbe9d764f081afc5e1a6aa884)
    * [missing system tray on some X11 platforms](https://github.com/Xpra-org/xpra/commit/d2765677e71cf0a3038b16039297863991e0bbb5t)
    * [window setup failures due to system tray confusion](https://github.com/Xpra-org/xpra/commit/ba5af99d1ab2542e2a73cf74d28fdd46454c2c62)
    * [unresponsive system tray after explorer.exe restart](https://github.com/Xpra-org/xpra/commit/cb290d9b73ed5641c9f8816e917290c335671444)
* Audio:
    * [pactl output parsing bug](https://github.com/Xpra-org/xpra/commit/3a923c857a249e19ebc72ba2997ceafacd4fd77f)
    * [pactl improve detection of monitor devices](https://github.com/Xpra-org/xpra/commit/d0d1fc249e1d3e893a15affe7ad056b633991022)
    * [microphone support for Chromium](https://github.com/Xpra-org/xpra/commit/c53a983efe41f6e95b31160ef86099a711d62322)
    * [cleaner pulseaudio command options](https://github.com/Xpra-org/xpra/commit/8f903bb9f053eb9d57fa84f0e425fac2b198d169)

## [5.0.1] 2023-08-29
* Major fixes:
    * [missing dbus instance](https://github.com/Xpra-org/xpra/commit/79fda14b3419a0ff9e86405dcffc89082927eca5)
    * [ssh re-connection errors following ssh start command](https://github.com/Xpra-org/xpra/commit/4bfb8577b100e39d18ed72135d33c7cadca112c1)
    * [U2F authentication failures](https://github.com/Xpra-org/xpra/commit/1ca86629b46b60be47917b130cabff41105dfb60)
    * [gstreamer x264 capture errors](https://github.com/Xpra-org/xpra/commit/f7554b9650e32994a1b33d163d73f0dbcccaa4eb)
    * [proxy forwarding of 'draw' packets with stripped alpha](https://github.com/Xpra-org/xpra/commit/6d9814c12843e431453e463555b3a60156a2ccc1)
* Build and packaging:
    * Fedora 39: [debug package errors](https://github.com/Xpra-org/xpra/commit/6e2a4130c581a12f6caee027ec5d748c1454e65d) and [build workarounds](https://github.com/Xpra-org/xpra/commit/293dc03765070c12f78202b664b732059e7c238b)
    * [pycuda RPMs for Python 3.12](https://github.com/Xpra-org/xpra/commit/f4a1ff83173a951851996b32698e09919020b620)
    * [Cython 3.0.2 RPMs](https://github.com/Xpra-org/xpra/commit/910b7e172348a0cf3aef7e4c528c1761df841c4e)
    * [Ubuntu Focal workarounds](https://github.com/Xpra-org/xpra/commit/a392929946697f104c060ea4152edb5981bf32e5)
    * [Debian soft dependency for nvidia codecs](https://github.com/Xpra-org/xpra/commit/451640396e31b4d6c807dc9dabd81df54be6b444) and [pycuda](https://github.com/Xpra-org/xpra/commit/dc382c384f251cd1cd458b96eb4cb45ba3baeead)
    * [Debian x11 dependencies belong in the xpra-x11 package](https://github.com/Xpra-org/xpra/commit/2b67784f2dfe71660145cc7e443554933d9652e5)
    * [automatic revision no when building from source](https://github.com/Xpra-org/xpra/commit/a330a2b994600259f55bfaad003cc637a1f4cecf)
* Minor fixes:
    * [handle invalid compressors more gracefully](https://github.com/Xpra-org/xpra/commit/51095fbb4241a8c579bc4dbda7ded9ee2748fc90)
    * [typo in undocumented environment variable](https://github.com/Xpra-org/xpra/commit/d30268bf58a0e0336d675e84421732c299abbda5)
    * [gtk version info missing for verbosity level](https://github.com/Xpra-org/xpra/commit/1f4f7fdb702d987d9bfa30a90be38c55be23c57b)

## [5.0] 2023-07-18
* Major improvements:
    * [QUIC transport](https://github.com/Xpra-org/xpra/issues/3376)
    * [split packaging](https://github.com/Xpra-org/xpra/issues/3802)
    * [freedesktop screencast / remotedesktop](https://github.com/Xpra-org/xpra/issues/3750) for X11 and Wayland
    * ease of use: [easier basic commands](https://github.com/Xpra-org/xpra/issues/3841), [open html5 client](https://github.com/Xpra-org/xpra/issues/3842), [disable all audio features](https://github.com/Xpra-org/xpra/issues/3835)
* Platforms, build and packaging:
    * [Python 3.12 installations](https://github.com/Xpra-org/xpra/issues/3807)
    * [replace Python2 builds](https://github.com/Xpra-org/xpra/issues/3652)
    * [LTS feature deprecation](https://github.com/Xpra-org/xpra/issues/3592)
    * [stricter type checks](https://github.com/Xpra-org/xpra/issues/3927)
    * [more MacOS workarounds](https://github.com/Xpra-org/xpra/issues/3777)
* Server:
    * [try harder to find a valid menu prefix](https://github.com/Xpra-org/xpra/commit/a42e2343ee572ff2edb28ece0b38904969c75470)
    * [exit with windows](https://github.com/Xpra-org/xpra/issues/3595)
    * [side buttons with MS Windows shadow servers](https://github.com/Xpra-org/xpra/pull/3865)
    * [mirror client monitor layout](https://github.com/Xpra-org/xpra/issues/3749)
    * [side buttons with MS Windows shadow servers](https://github.com/Xpra-org/xpra/pull/3865)
* Client:
    * [allow keyboard shortcuts in readonly mode](https://github.com/Xpra-org/xpra/issues/3899)
    * [show decoder statistics](https://github.com/Xpra-org/xpra/issues/3796)
    * [keyboard layout switching shortcut](https://github.com/Xpra-org/xpra/pull/3859)
    * [layout switching detection for MS Windows](https://github.com/Xpra-org/xpra/issues/3857)
    * [mirror mouse cursor when sharing](https://github.com/Xpra-org/xpra/issues/3767)
* Minor:
    * [generic exec authentication module](https://github.com/Xpra-org/xpra/issues/3790)
    * [audio `removesilence`](https://github.com/Xpra-org/xpra/issues/3709)
    * [make pulseaudio real-time and high-priority scheduling modes configurable](https://github.com/Xpra-org/xpra/pull/3893)
    * [use urrlib for parsing](https://github.com/Xpra-org/xpra/issues/3599)
    * [GTK removal progress](https://github.com/Xpra-org/xpra/issues/3871)
    * documentation updates and fixes: [broken links](https://github.com/Xpra-org/xpra/pull/3839), [typos](https://github.com/Xpra-org/xpra/pull/3836)
* Network:
    * [smaller handshake packet](https://github.com/Xpra-org/xpra/issues/3812)
    * [SSL auto-upgrade](https://github.com/Xpra-org/xpra/issues/3313)
    * [better IPv6](https://github.com/Xpra-org/xpra/issues/3853)
    * [new packet format](https://github.com/Xpra-org/xpra/issues/1942)
    * [ssh agent forwarding automatic switching when sharing](https://github.com/Xpra-org/xpra/issues/3593)
    * [use libnm to query network devices](https://github.com/Xpra-org/xpra/issues/3623)
    * [exclude more user data by default](https://github.com/Xpra-org/xpra/issues/3582)
* Encodings:
    * [use intra refresh](https://github.com/Xpra-org/xpra/issues/3830)
    * [`stream` encoding for desktop mode](https://github.com/Xpra-org/xpra/issues/3872)
    * [GStreamer codecs](https://github.com/Xpra-org/xpra/issues/3706)


## [4.4] 2022-10-01
* Platforms, build and packaging:
    * [Native LZ4 bindings](https://github.com/Xpra-org/xpra/issues/3601)
    * Safer native brotli bindings for [compression](https://github.com/Xpra-org/xpra/issues/3572) and [decompression](https://github.com/Xpra-org/xpra/issues/3258)
    * [Native qrencode bindings](https://github.com/Xpra-org/xpra/issues/3578)
    * [openSUSE build tweaks](https://github.com/Xpra-org/xpra/issues/3597), [Fedora 37](https://github.com/Xpra-org/xpra/commit/414a1ac9ae2775f1566a800aa1eb4688361f2c38), [Rocky Linux / Alma Linux / CentOS Stream : 8 and 9](https://github.com/Xpra-org/repo-build-scripts/commit/f53085abf3227e4b758c3f4c04fa96092fc2b599), [Oracle Linux](https://github.com/Xpra-org/repo-build-scripts/commit/56a2bf9a48e55924782eb777b05e2b37262868e5)
    * [Debian finally moved to `libexec`](https://github.com/Xpra-org/xpra/issues/3493)
    * [MS Windows taskbar integration](https://github.com/Xpra-org/xpra/issues/508)
    * [SSH server support on MS Windows, including starting shadow sessions](https://github.com/Xpra-org/xpra/issues/3626)
* Server:
    * [Configurable vertical refresh rate](https://github.com/Xpra-org/xpra/issues/3600)
    * [Virtual Monitors](https://github.com/Xpra-org/xpra/issues/56)
    * [Multi-monitor desktop mode](https://github.com/Xpra-org/xpra/issues/3524)
    * [Expand an existing desktop](https://github.com/Xpra-org/xpra/issues/3390)
    * [Exit with windows](https://github.com/Xpra-org/xpra/issues/3595)
    * [Full shadow keyboard mapping](https://github.com/Xpra-org/xpra/issues/2630)
    * [xwait subcommand](https://github.com/Xpra-org/xpra/issues/3386)
    * [guess content-type from parent pid](https://github.com/Xpra-org/xpra/issues/2753)
    * [cups print backend status report](https://github.com/Xpra-org/xpra/issues/1228)
    * [Override sockets on upgrade](https://github.com/Xpra-org/xpra/issues/3568)
    * [Allow additional options to X server invocation](https://github.com/Xpra-org/xpra/issues/3553)
    * Control commands for [modifying command environment](https://github.com/Xpra-org/xpra/issues/3502), and [read only flag](https://github.com/Xpra-org/xpra/issues/3466)
    * [Start new commands via a proxy server's SSH listener](https://github.com/Xpra-org/xpra/issues/2898)
* Shadow server:
    * [Geometry restrictions](https://github.com/Xpra-org/xpra/issues/3384)
    * [Shadow specific applications](https://github.com/Xpra-org/xpra/issues/3476)
* Client:
    * [Automatic keyboard grabs](https://github.com/Xpra-org/xpra/issues/3059)
    * [Pointer confinement](https://github.com/Xpra-org/xpra/issues/3059)
    * [Faster window initial data](https://github.com/Xpra-org/xpra/issues/3473)
    * [Improved DPI detection on MS Windows](https://github.com/Xpra-org/xpra/issues/1526)
    * [Show all current keyboard shortcuts](https://github.com/Xpra-org/xpra/issues/2779)
    * [Preserve all options when reconnecting](https://github.com/Xpra-org/xpra/issues/3207)
    * [Option to accept SSL mismatched host permanently](https://github.com/Xpra-org/xpra/issues/3305)
    * [Forward all command line options](https://github.com/Xpra-org/xpra/issues/3566)
    * [Smooth scrolling options](https://github.com/Xpra-org/xpra/issues/3127)
    * [Per-window scaling](https://github.com/Xpra-org/xpra/issues/3454) - experimental
    * [Workaround Wayland startup hangs](https://github.com/Xpra-org/xpra/issues/3630)
* Security and authentication:
    * [Configurable information disclosure](https://github.com/Xpra-org/xpra/issues/3582)
    * [Keycloak authentication](https://github.com/Xpra-org/xpra/issues/3486)
    * [Capability based authentication](https://github.com/Xpra-org/xpra/issues/3575)
    * [Authentication for web server scripts](https://github.com/Xpra-org/xpra/issues/3100)
    * [OTP authentication](https://github.com/Xpra-org/xpra/issues/2906)
    * [Workaround paramiko `No existing session` error](https://github.com/Xpra-org/xpra/issues/3223)
* Encodings and latency:
    * [Option to cap picture quality](https://github.com/Xpra-org/xpra/issues/3420)
    * [Expose scaling quality](https://github.com/Xpra-org/xpra/issues/3598)
    * [NVJPEG decoder](https://github.com/Xpra-org/xpra/issues/3504) (WIP - leaks memory)
    * [AVIF encoding](https://github.com/Xpra-org/xpra/issues/3457)
    * [selective `scroll` encoding detection](https://github.com/Xpra-org/xpra/issues/3519)
* Network:
    * [SOCKS proxy connection support](https://github.com/Xpra-org/xpra/issues/2105)
    * [SSH agent forwarding](https://github.com/Xpra-org/xpra/issues/2303)
    * [proxy network performance improvement](https://github.com/Xpra-org/xpra/issues/2976)
    * [SSH workarounds for polluted stream premable](https://github.com/Xpra-org/xpra/issues/3610)
* Misc:
    * [easier xpra subcommand invocation](https://github.com/Xpra-org/xpra/issues/3371)
* Refactoring and preparation for the next LTS release:
    * [Feature deprecation](https://github.com/Xpra-org/xpra/issues/3592)
    * [Remove "app menus" support](https://github.com/Xpra-org/xpra/issues/2163)
    * [Remove ancient complicated code](https://github.com/Xpra-org/xpra/issues/3537)
    * [Simplify the build file](https://github.com/Xpra-org/xpra/issues/3577)
    * [More robust info handlers](https://github.com/Xpra-org/xpra/issues/3509)
    * [Remove scary warnings](https://github.com/Xpra-org/xpra/issues/3625)
    * [f-strings](https://github.com/Xpra-org/xpra/issues/3579)


## [4.3] 2021-12-05
* Platforms, build and packaging:
	* [arm64 support](https://github.com/Xpra-org/xpra/issues/3291), including [nvenc and nvjpeg](https://github.com/Xpra-org/xpra/issues/3378)
	* [non-system header builds (eg: conda)](https://github.com/Xpra-org/xpra/issues/3360)
	* [fixed MacOS shadow start via ssh](https://github.com/Xpra-org/xpra/issues/3343)
	* [parallel builds](https://github.com/Xpra-org/xpra/issues/3255)
	* [don't ship too may pillow plugins](https://github.com/Xpra-org/xpra/issues/3133)
	* [easier access to documentation](https://github.com/Xpra-org/xpra/issues/3015)
	* [Python 3.10 buffer api compatibility](https://github.com/Xpra-org/xpra/issues/3031)
* Misc:
	* [make it easier to silence OpenGL validation warnings](https://github.com/Xpra-org/xpra/issues/3380)
	* [don't wait for printers](https://github.com/Xpra-org/xpra/issues/3170)
	* [make it easier to autostart](https://github.com/Xpra-org/xpra/issues/3134)
	* ['clean' subcommand](https://github.com/Xpra-org/xpra/issues/3099)
	* [flexible 'run_scaled' subcommand](https://github.com/Xpra-org/xpra/issues/3303)
	* [more flexible key shortcuts configuration](https://github.com/Xpra-org/xpra/issues/3183)
* Encodings and latency:
	* [significant latency and performance improvements](https://github.com/Xpra-org/xpra/issues/3337)
	* [spng decoder](https://github.com/Xpra-org/xpra/issues/3373) and [encoder](https://github.com/Xpra-org/xpra/issues/3374)
	* [jpeg with transparency](https://github.com/Xpra-org/xpra/issues/3367)
	* [faster argb module](https://github.com/Xpra-org/xpra/issues/3361)
	* [faster nvjpeg module using CUDA, add transparency](https://github.com/Xpra-org/xpra/issues/2984)
	* [faster xshape scaling](https://github.com/Xpra-org/xpra/issues/1226)
	* [downscale jpeg and webp](https://github.com/Xpra-org/xpra/issues/3333)
	* [disable av-sync for applications without audio](https://github.com/Xpra-org/xpra/issues/3351)
	* [opaque region support](https://github.com/Xpra-org/xpra/issues/3317)
	* [show FPS on client window](https://github.com/Xpra-org/xpra/issues/3311)
	* [nvenc to use the same device context as nvjpeg](https://github.com/Xpra-org/xpra/issues/3195)
	* [nvenc disable unsupported presets](https://github.com/Xpra-org/xpra/issues/3136)
* Network:
	* [make it easier to use SSL](https://github.com/Xpra-org/xpra/issues/3299)
	* [support more AES modes: GCM, CFB and CTR](https://github.com/Xpra-org/xpra/issues/3247)
	* [forked rencodeplus encoder](https://github.com/Xpra-org/xpra/issues/3229)
* Server:
	* [shadow specific areas or monitors](https://github.com/Xpra-org/xpra/issues/3320)
	* [faster icon lookup](https://github.com/Xpra-org/xpra/issues/3326)
	* [don't trust _NET_WM_PID](https://github.com/Xpra-org/xpra/issues/3251)
	* [move all sessions to a sub-directory](https://github.com/Xpra-org/xpra/issues/3217)
	* [more reliable server cleanup](https://github.com/Xpra-org/xpra/issues/3218)
	* [better VNC support](https://github.com/Xpra-org/xpra/issues/3256)
	* [more seamless server upgrades](https://github.com/Xpra-org/xpra/issues/541)
	* [source /etc/profile](https://github.com/Xpra-org/xpra/issues/3083)
	* [switch input method to ibus](https://github.com/Xpra-org/xpra/issues/2359)


## [4.2] 2021-05-18
* [use pinentry for password prompts](https://github.com/Xpra-org/xpra/issues/3002) and [ssh prompts](https://github.com/Xpra-org/xpra/commit/2d2022d184f31f53c2328b5e5ca804e5ea46ff6c)
* [nvjpeg encoder](https://github.com/Xpra-org/xpra/issues/2984) - also requires [this commit](https://github.com/Xpra-org/xpra-html5/commit/cd846f0055276ecd9b021767a13be05a16e833eb) to the [html5 client](https://github.com/Xpra-org/xpra-html5/)
* [gui for starting remote sessions](https://github.com/Xpra-org/xpra/issues/3070)
* new subcommands: `recover`, `displays`, `list-sessions`, `clean-displays`, `clean-sockets` - [#3098](https://github.com/Xpra-org/xpra/issues/3098), [#3099](https://github.com/Xpra-org/xpra/issues/3099)
* many fixes: [window initial position](https://github.com/Xpra-org/xpra/issues/2008), [focus](https://github.com/Xpra-org/xpra/issues/2852), non-opengl paint corruption, [slow rendering on MacOS](https://github.com/Xpra-org/xpra/commit/5ad0e767441454758b111f1c80baf49c10b964e8), build scripts, [handle smooth scroll events with wayland clients](https://github.com/Xpra-org/xpra/issues/3127), always lossy screen updates for terminals, [clipboard timeout](https://github.com/Xpra-org/xpra/issues/3086), [peercred auth options](https://github.com/Xpra-org/xpra/commit/e401e650c18974288d71cebc6491970698560a9f)
* support multiple clients using mmap simultaneously [with non-default file paths](https://github.com/Xpra-org/xpra/commit/ef936f461996915547141e8d02c15a57516d5ff0)
* [only synchronize xsettings with seamless servers](https://github.com/Xpra-org/xpra/commit/f7cbb40230ed5170859f5b5ea6cbd27ded3d3d02)
* automatic desktop scaling is now [disabled](https://github.com/Xpra-org/xpra/commit/092800cbe44716fb0adaf842de5bc95a6329527a)
* workaround for [gnome applications starting slowly](https://github.com/Xpra-org/xpra/issues/3109)

## [4.1] 2021-02-26
* Overhauled container based [build system](https://github.com/Xpra-org/xpra/tree/master/packaging/buildah)
* [Splash screen](https://github.com/Xpra-org/xpra/issues/2540)
* [`run_scaled` utility script](https://github.com/Xpra-org/xpra/issues/2813)
* Client:
	* [header bar option](https://github.com/Xpra-org/xpra/issues/2539) for window control menu
	* generate a [qrcode](https://github.com/Xpra-org/xpra/issues/2627) to connect
	* show all [keyboard shortcuts](https://github.com/Xpra-org/xpra/issues/2779)
	* [progress bar](https://github.com/Xpra-org/xpra/issues/2678) for file transfers
	* GTK cairo backend support for [more native bit depths](https://github.com/Xpra-org/xpra/issues/2839)
	* [disable xpra's keyboard shortcuts](https://github.com/Xpra-org/xpra/issues/2739) from the system tray menu
	* automatically [include the server log](https://github.com/Xpra-org/xpra/issues/2570) in bug reports
* OpenGL client backend:
	* render at [fixed bit depths](https://github.com/Xpra-org/xpra/issues/2826) with the `pixel-depth` option
	* support [more bit depths](https://github.com/Xpra-org/xpra/issues/2828)
* Clipboard:
	* [MacOS support](https://github.com/Xpra-org/xpra/issues/273) for images, more text formats, etc
	* [MS Windows](https://github.com/Xpra-org/xpra/issues/2619) support for images
	* [wayland](https://github.com/Xpra-org/xpra/issues/2927) clients
* Server:
	* [faster server startup](https://github.com/Xpra-org/xpra/issues/2815)
	* [`xpra list-windows`](https://github.com/Xpra-org/xpra/issues/2700) subcommand
	* new window control commands: [move - resize](https://github.com/Xpra-org/xpra/issues/2774), [map - unmap](https://github.com/Xpra-org/xpra/issues/3028)
	* remote logging: [from server to client](https://github.com/Xpra-org/xpra/issues/2749)
	* support [window re-stacking](https://github.com/Xpra-org/xpra/issues/2896)
* `xpra top`:
	* [show pids, shortcuts](https://github.com/Xpra-org/xpra/issues/2601)
	* more details in the [list view](https://github.com/Xpra-org/xpra/issues/2553)
	* show [speed and quality](https://github.com/Xpra-org/xpra/issues/2719)
* Display:
	* bumped maximum resolution [beyond 8K](https://github.com/Xpra-org/xpra/issues/2628)
	* [set the initial resolution](https://github.com/Xpra-org/xpra/issues/2772) more easily using the 'resize-display' option
* Encoding:
	* server side picture [downscaling](https://github.com/Xpra-org/xpra/issues/2052)
	* [libva](https://github.com/Xpra-org/xpra/issues/451) hardware accelerated encoding
	* NVENC [30-bit](https://github.com/Xpra-org/xpra/issues/1308) accelerated encoding
	* vpx [30-bit](https://github.com/Xpra-org/xpra/issues/1310)
	* x264 [30-bit](https://github.com/Xpra-org/xpra/issues/1462)
	* faster [30-bit RGB subsampling](https://github.com/Xpra-org/xpra/issues/2773)
	* scroll encoding now handled [more generically](https://github.com/Xpra-org/xpra/issues/2810)
	* [black and white](https://github.com/Xpra-org/xpra/issues/1713) mode
* Network:
	* [IGD / UPNP](https://github.com/Xpra-org/xpra/issues/2417)
	* [SO_KEEPALIVE](https://github.com/Xpra-org/xpra/issues/2420) option
	* clients can be [queried](https://github.com/Xpra-org/xpra/issues/2743) and [controlled](https://github.com/Xpra-org/xpra/issues/2856) using local sockets
	* specify connection attributes [using the connection string](https://github.com/Xpra-org/xpra/issues/2794)
	* [nested SSH tunnels](https://github.com/Xpra-org/xpra/issues/2867)
	* websocket [header modules](https://github.com/Xpra-org/xpra/issues/2874)
	* [specify the socket type](https://github.com/Xpra-org/xpra/issues/2914) with socket activation
	* expose the [packet flush flag](https://github.com/Xpra-org/xpra/issues/2975)
	* [`xpra shell`](https://github.com/Xpra-org/xpra/issues/2750) subcommand for interacting with processes in real time
	* [custom group sockets directory](https://github.com/Xpra-org/xpra/issues/2907) permissions and name
* Testing:
	* better [test coverage](https://github.com/Xpra-org/xpra/issues/2598)
	* [cleanup output](https://github.com/Xpra-org/xpra/issues/2938)

## [4.0] 2020-05-10
* Drop support for:
    * Python 2, GTK2
    * legacy versions (pre 1.0)
    * weak authentication
* Network, per socket options:
    * authentication and encryption
    * ssl
    * ssh
    * bind options for client
* make it easier to send files from the server
* xpra toolbox subcommand
* xpra help subcommand
* xpra top new features
* faster startup
* signal handling fixes
* smoother window resizing
* refactoring and testing
    * unit tests coverage and fixes
    * completely skip loading unused features at runtime
    * get rid of capabilities data after parsing it
    * better module dependency separation
    * don't convert to a string before we need it
* more useful window and tray title
* make it easier to source environment
* disable desktop animations in desktop mode
* automatic start-or-upgrade, automatic X11 display rescue
* support MS Windows OpenSSH server to start shadow
* more selective use of OpenGL acceleration in client
* expose server OpenGL capabilities
* cleaner HTML5 syntax


## [3.0] 2019-09-21
* Python 3 port complete, now the default: [#1571](https://github.com/Xpra-org/xpra/issues/1571), [#2195](https://github.com/Xpra-org/xpra/issues/2195)
* much nicer HTML5 client user interface: [#2269](https://github.com/Xpra-org/xpra/issues/2269)
* Window handling:
    * smoother window resizing: [#478](https://github.com/Xpra-org/xpra/issues/478) (OpenGL)
    * honouring gravity: [#2217](https://github.com/Xpra-org/xpra/issues/2217)
    * lock them in readonly mode: [#2137](https://github.com/Xpra-org/xpra/issues/2137)
* xpra top subcommand: [#2348](https://github.com/Xpra-org/xpra/issues/2348)
* faster startup:
    * [#2347](https://github.com/Xpra-org/xpra/issues/2347) faster client startup
    * [#2341](https://github.com/Xpra-org/xpra/issues/2341) faster server startup
* OpenGL:
    * more reliable driver probing: [#2204](https://github.com/Xpra-org/xpra/issues/2204)
    * cursor paint support: [#1497](https://github.com/Xpra-org/xpra/issues/1497)
    * transparency on MacOS: [#1794](https://github.com/Xpra-org/xpra/issues/1794)
* Encoding:
    * lossless window scrolling: [#1320](https://github.com/Xpra-org/xpra/issues/1320)
    * scrolling acceleration for non-OpenGL backends: [#2295](https://github.com/Xpra-org/xpra/issues/2295)
    * harden image parsing: [#2279](https://github.com/Xpra-org/xpra/issues/2279)
    * workaround slow video encoder initialization (ie: NVENC) using replacement frames: [#2048](https://github.com/Xpra-org/xpra/issues/2048)
    * avoid loading codecs we don't need: [#2344](https://github.com/Xpra-org/xpra/issues/2344)
    * skip some CUDA devices, speedup enumeration: [#2415](https://github.com/Xpra-org/xpra/issues/2415)
* Clipboard:
    * new native clipboard implementations for all platforms: [#812](https://github.com/Xpra-org/xpra/issues/812)
    * HTML5 asynchronous clipboard: [#1844](https://github.com/Xpra-org/xpra/issues/1844)
    * HTML5 support for copying images: [#2312](https://github.com/Xpra-org/xpra/issues/2312) (with watermarking)
    * brotli compression for text data: [#2289](https://github.com/Xpra-org/xpra/issues/2289)
* Authentication:
    * modular client authentication handlers: [#1796](https://github.com/Xpra-org/xpra/issues/1796)
    * mysql authentication module: [#2287](https://github.com/Xpra-org/xpra/issues/2287)
    * generic SQL authentication module: [#2288](https://github.com/Xpra-org/xpra/issues/2288)
* Network:
    * client listen mode: [#1022](https://github.com/Xpra-org/xpra/issues/1022)
    * retry to connect until it succeeds or times out: [#2346](https://github.com/Xpra-org/xpra/issues/2346)
    * mdns TXT attributes updated at runtime: [#2187](https://github.com/Xpra-org/xpra/issues/2187)
    * zeroconf fixes: [#2317](https://github.com/Xpra-org/xpra/issues/2317)
    * drop pybonjour: [#2297](https://github.com/Xpra-org/xpra/issues/2297)
    * paramiko honours IdentityFile: [#2282](https://github.com/Xpra-org/xpra/issues/2282), handles SIGINT better: [#2378](https://github.com/Xpra-org/xpra/issues/2378)
    * proxy server fixes for ssl and ssh sockets: [#2399](https://github.com/Xpra-org/xpra/issues/2399), remove spurious options: [#2193](https://github.com/Xpra-org/xpra/issues/2193)
    * proxy ping and timeouts: [#2408](https://github.com/Xpra-org/xpra/issues/2408)
    * proxy dynamic authentication: [#2261](https://github.com/Xpra-org/xpra/issues/2261)
* Automated Testing:
    * test HTML5 client: [#2231](https://github.com/Xpra-org/xpra/issues/2231)
    * many new mixin tests: [#1773](https://github.com/Xpra-org/xpra/issues/1773) (and bugs found)
* start-new-commands is now enabled by default: [#2278](https://github.com/Xpra-org/xpra/issues/2278), and the UI allows free text: [#2221](https://github.com/Xpra-org/xpra/issues/2221)
* basic support for native GTK wayland client: [#2243](https://github.com/Xpra-org/xpra/issues/2243)
* forward custom X11 properties: [#2311](https://github.com/Xpra-org/xpra/issues/2311)
* xpra launcher visual feedback during connection: [#1421](https://github.com/Xpra-org/xpra/issues/1421), sharing option: [#2115](https://github.com/Xpra-org/xpra/issues/2115)
* "Window" menu on MacOS: [#1808](https://github.com/Xpra-org/xpra/issues/1808)


## [2.5] 2019-03-19
* Python 3 port mostly complete, including packaging for Debian
* pixel compression and bandwidth management:
    * better recovery from network congestion
    * distinguish refresh from normal updates
    * better tuning for mmap connections
    * heuristics improvements
    * use video encoders more aggressively
    * prevent too many delayed frames with x264
    * better video region detection with opengl content
* better automatic tuning for client applications
    * based on application categories
    * application supplied hints
    * application window encoding hints
    * using environment variables and disabling video
* HTML5 client improvements
* Client improvements:
    * make it easier to start new commands, provide start menu
    * probe OpenGL in a subprocess to detect and workaround driver crashes
    * use appindicator if available
* Packaging:
    * merge xpra and its dependencies into the ​MSYS2 repository
    * ship fewer files in MS Windows installers
    * partial support for parallel installation of 32-bit and 64-bit version on MS Windows
    * MacOS library updates
    * CentOS 7: libyu## [] and turbojpeg
    * Windows Services for Linux (WSL) support
    * Fedora 30 and Ubuntu Disco support
    * Ubuntu HWE compatibility (manual steps required due to upstream bug)
* Server improvements:
    * start command on last client exit
    * honour minimum window size
    * Python 3
    * upgrade-desktop subcommand
* Network layer:
    * less copying
    * use our own websocket layer
    * make it easier to install mdns on MS Windows
    * make mmap group configurable
    * TCP CORK support on Linux
* SSH transport:
    * support .ssh/config with paramiko backend
    * connecting via ssh proxy hosts
* SSHFP with paramiko:
    * clipboard: restrict clipboard data transfers size
    * audio: support wasapi on MS Windows
* code cleanups, etc
	

## [2.4] 2018-10-13
* SSH client integration (paramiko)
* builtin server support for TCP socket upgrades to SSH (paramiko)
* automatic TCP port allocation
* expose desktop-sessions as VNC via mdns
* add zeroconf backend
* register more URL schemes
* window content type heuristics configuration
* use content type it to better tune automatic encoding selection
* automatic video scaling
* bandwidth-limit management in video encoders
* HTML5 client mpeg1 and h264 decoding
* HTML5 client support for forwarding of URL open requests
* HTML5 client Internet Explorer 11 compatibility
* HTML5 client toolbar improvements
* HTML5 fullscreen mode support
* limit video dimensions to cap CPU and bandwidth usage
* keyboard layout handling fixes
* better memory management and resource usage
* new default GUI welcome screen
* desktop file for starting shadow servers more easily
* clipboard synchronization with multiple clients
* use notifications bubbles for more important events
* workarounds for running under Wayland with GTK3
* modal windows enabled by default
* support xdg base directory specification and socket file time
* improved python3 support (still client only)
* multi-window shadow servers on MacOS and MS Windows
* buildbot upgrade
* more reliable unit tests
* fixes and workarounds for Java client applications
* locally authenticated users can shutdown proxy servers
* restrict potential privileged information leakage
* enhanced per-client window filtering
* remove extra pixel copy in opengl enabled client
* clip pointer events to the actual window content size
* new platforms: Ubuntu Cosmic, Fedora 29


## [2.3] 2018-05-08
* stackable authentication modules
* tcp wrappers authentication module
* gss, kerberos, ldap and u2f authentication modules
* request access to the session
* pulseaudio server per session to prevent audio leaking
* better network bandwidth utilization and congestion management
* faster encoding and decoding: YUV for webp and jpeg, encoder hints, better vsync
* notifications actions forwarding, custom icons, expose warnings
* upload notification and management
* shadow servers multi window mode
* tighter client OS integratioin
* client window positioning and multi-screen support
* unique application icon used as tray icon
* multi stop or attach
* control start commands
* forward signals sent to windows client side
* forward requests to open URLs or files on the server side
* html5 client improvements: top bar, debugging, etc
* custom http headers, support content security policy
* python3 port improvements
* bug fixes: settings synchronization, macos keyboard mapping, etc
* packaging: switch back to ffmpeg system libraries, support GTK3 on macos
* structural improvements: refactoring, fewer synchronized X11 calls, etc


## [2.2] 2017-12-11
* support RFB clients (ie: VNC) with bind-rfb or rfb-upgrade options
* UDP transport (experimental) with bind-udp and udp://host:port URLs
* TCP sockets can be upgrade to Websockets and / or SSL, RFB
* multiple bind options for all socket types supported: tcp, ssl, ws, wss, udp, rfb
* bandwidth-limit option, support for very low bandwidth connections
* detect network performance characteristics
* "xpra sessions" browser tool for both mDNS and local sessions
* support arbitrary resolutions with Xvfb (not with Xdummy yet)
* new OpenGL backends, with support for GTK3 on most platforms
	   and window transparency on MS Windows
* optimized webp encoding, supported in HTML5 client
* uinput virtual pointer device for supporting fine grained scrolling
* connection strings now support the standard URI format protocol://host:port/
* rencode is now used by default for the initial packet
* skip sending audio packets when inactive
* improved support for non-us keyboard layouts with non-X11 clients
* better modifier key support on Mac OS
* clipboard support with GTK3
* displayfd command line option
* cosmetic system tray menu layout changes
* dbus service for the system wide proxy server (stub)
* move mmap file to $XDG_RUNTIME_DIR (where applicable)
* password prompt dialog in client
* fixed memory leaks


## [2.1] 2017-07-24
* improve system wide proxy server, logind support on, socket activation
* new authentication modules:
    * new posix peercred authentication module (used by system wide proxy)
    * new sqlite authentication module
* split packages for RPM, MS Windows and Mac OS
* digitally signed MS Windows installers
* HTML5 client improvements:
    * file upload support
    * better non-us keyboard and language support
    * safe HMAC authentication over HTTP, re-connection etc
    * more complete window management, (pre-)compression (zlib, brotli)
    * mobile on-screen keyboard
    * audio forwarding for IE
    * remote drag and drop support
* better Multicast DNS support, with a GUI launcher
* improved image depth / deep color handling
* desktop mode can now be resized easily
* any window can be made fullscreen (Shift+F11 to trigger)
* Python3 GTK3 client is now usable
* shutdown the server from the tray menu
* terminate child commands on server shutdown
* macos library updates: [#1501](https://github.com/Xpra-org/xpra/issues/1501), support for virtual desktops
* NVENC SDK version 8 and HEVC support
* Nvidia capture SDK support for fast shadow servers
* shadow servers improvements: show shadow pointer in opengl client
* structural improvements and important bug fixes


## [2.0] 2017-03-17
* dropped support for outdated OS and libraries (long list)
* 64-bit builds for MS Windows and MacOSX
* MS Windows MSYS2 based build system with fully up to date libraries
* MS Windows full support for named-pipe connections
* MS Windows and MacOSX support for mmap transfers
* more configurable mmap options to support KVM's ivshmem
* faster HTML5 client, now packaged separately (RPM only)
* clipboard synchronization support for the HTML5 client
* faster window scrolling detection, bandwidth savings
* support more screen bit depths: 8, 16, 24, 30 and 32
* support 10-bit per pixel rendering with the OpenGL client backend
* improved keyboard mapping support when sharing sessions
* faster native turbojpeg codec
* OpenGL enabled by default on more chipsets, with better driver sanity checks
* better handling of tablet input devices (multiple platforms and HTML5 client)
* synchronize Xkb layout group
* support stronger HMAC authentication digest modes
* unit tests are now executed automatically on more platforms
* fix python-lz4 0.9.0 API breakage
* fix html5 visual corruption with scroll paint packets


## [1.0] 2016-12-06
* SSL socket support
* IANA assigned default port 14500 (so specifying the TCP port is now optional)
* include a system-wide proxy server service on our default port, using system authentication
* MS Windows users can start a shadow server from the start menu, which is also accessible via http
* list all local network sessions exposed via mdns using xpra list-mdns
* the proxy servers can start new sessions on demand
* much faster websocket / http server for the HTML5 client, with SSL support
* much improved HTML client, including support for native video decoding
* VNC-like desktop support: "xpra start-desktop"
* pointer grabs using Shift+Menu, keyboard grabs using Control+Menu
* window scrolling detection for much faster compression
* server-side support for 10-bit colours
* better automatic encoding selection and video tuning, support H264 b-frames
* file transfer improvements
* SSH password input support on all platforms in launcher
* client applications can trigger window move and resize with MS Windows and Mac OS X clients
* geometry handling improvements, multi-monitor, fullscreen
* drag and drop support between application windows
* colour management synchronisation (and DPI, workspace, etc)
* the configuration file is now split into multiple logical parts, see /etc/xpra/conf.d
* more configuration options for printers
* clipboard direction restrictions
* webcam improvements: better framerate, device selection menu
* audio codec improvements, new codecs, mpeg audio
* reliable video support for all Debian and Ubuntu versions via private ffmpeg libraries
* use XDG_RUNTIME_DIR if possible, move more files to /run (sockets, log file)
* build and packaging improvements: minify during build: rpm "python2", netbsd v4l
* selinux policy for printing
* Mac OS X PKG installer now sets up ".xpra" file and "xpra:" URL associations
* Mac OS X remote shadow start support (though not all versions are supported)


## [0.17.5] 2016-07-13
* fix webcam skewed picture
* fix size calculations for the 1 pixel bottom edge of video areas
* fix heavy import with side effects for shadow servers
* fix MS Windows shadow servers picture corruption
* fix jpeg wrongly included in auto-refresh encodings
* fix compatibility with ffmpeg 3.1+, warn but don't fail
* fix socket-dir option not being honoured
* fix log dir in commented out Xvfb example
* fix build on some non US locales


## [0.17.4] 2016-06-27
* fix severe regression in damage handling
* fix lossless refresh causing endless loops
* fix path stripping during packaging
* fix password leak in server log file
* fix keyboard layout change handling
* fix openSUSE RPM packaging dependencies
* fix video region API stickiness
* fix application iconification support
* fix XShape performance when scaling
* fix file transfer packet handling and checksum validation
* fix webcam forwarding
* fix spurious pulseaudio exit message on shutdown
* CUDA 8 and Pascal GPU optimization support
* disable webp (black rectangles with some versions)


## [0.17.3] 2016-06-03
* fix logging errors with libyu## [] module (hiding real errors)
* fix memory handling in error cases with x264 encoder
* fix video encoder and colourspace converter leak
* fix rare delta encoding errors
* fix dbus x11 dependency in RPM packaging
* fix dependencies for RHEL 7.0
* fix DPI option miscalculation when used from the client
* fix window aspect ratio hints handling
* fix stripping of temporary build paths
* fix sound subprocess stuck in paused state after an early error
* fix H264 decoding in HTML5 client (disabled for now)
* fix AES padding errors with HTML5 client
* fix spurious import statements in NVENC codecs
* fix crashes in X11 keyboard handling
* fix compatibility with newer GCC versions
* fix OSX and win32 shadow server key mappings
* fix OSX shadow server disconnections with invalid RGB packet data
* fix OSX shadow server crashes with webp
* fix OSX shadow server errors with opus sound codec (disable it)
* fix RGB compression algorithm reported in logging


## [0.17.2] 2016-05-14
* fix suse leap builds (no python3 because os missing dependencies)
* fix aspect-ratio hint handling
* fix sound queue state not getting updated
* fix socket protocol and family information reported
* fix scratchy sound with GStreamer 0.10 (ie: CentOS 6.x)
* fix handling of DPI command line switch client side
* fix printer requests wrongly honoured when printing is disabled
* fix error in websockify error handler
* fix missing matroska container on OSX
* fix Webcam and GTK info scripts on OSX


## [0.17.1] 2016-05-02
* fix SSH error handler
* fix SSH connections with tcsh
* fix launcher GUI with SSH mode
* fix RPM packaging for automatic system installation
* fix / workaround bug in Xorg server 1.18.1 and later
* fix unhelpful systray GDK warning with some desktop environments
* fix duplicate socket paths listed
* fix clipboard issues: timeouts and re-enabling from systray
* fix frame extents warning message to blame the culprit
* fix installation alert message format on Windows XP


## [0.17.0] 2016-04-18
* GStreamer 1.6.x on MS Windows and OSX
* opus is now the default sound codec
* microphone and speaker forwarding no longer cause sound loops
* new sound container formats: matroska, gdp
* much improved shadow servers, especially for OSX and MS Windows
* use newer Plink SSH with Windows Vista onwards
* OSX PKG installer, with file association
* libyu## [] codec for faster colourspace conversion
* NVENC v6, HEVC hardware encoding
* xvid mpeg4 codec
* shadow servers now expose a tray icon and menu
* improved tablet input device support on MS Windows
* improved window geometry handling
* OSX dock clicks now restore existing windows
* OSX clipboard synchronization menu
* new encryption backend: python-cryptography, hardware accelerated AES
* the dbus server can now be started automatically
* support for using /var/run on Linux and multiple sockets
* support for AF_VSOCK virtual networking
* broadcast sessions via mDNS on MS Windows and OSX
* window geometry fixes
* window close event is now configurable, automatically disconnects
* webcam forwarding (limited scope)
* SELinux policy improvements (still incomplete)
* new event based start commands: after connection / on connection
* split file authentication module
* debug logging and message improvements


## [0.16.0] 2015-11-13
* remove more legacy code, cleanups, etc
* switch to GStreamer 1.x on most platforms
* mostly gapless audio playback
* audio-video synchronization
* zero copy memoryview buffers (Python 2.7 and later), safer read-only buffers
* improved vp9 support
* handling of very high client resolutions (8k and above)
* more reliable window positioning and geometry
* add more sanity checks to codecs and csc modules
* network and protocol improvements: safety checks, threading
* encryption improvements: support TCP only encryption, `PKCS#7` padding
* improved printer forwarding
* improved DPI and anti-alias synchronization and handling (incomplete)
* better multi-monitor support
* support for screen capture tools (disabled by default)
* automatic desktop scaling to save bandwidth and CPU (upscale on client)
* support remote SSH start without specifying a display
* support multiple socket directories
* lz4 faster modes with automatic speed tuning
* server file upload from system tray
* new subcommand: "xpra showconfig"
* option to select a specific clipboard to synchronize with (MS Windows only)
* faster OpenGL screen updates: group screen updates
* dbus server for easier runtime control
* replace calls to setxkbmap with native X11 API
* XShm for override-redirect windows and shadow servers
* faster X11 shadow servers
* XShape forwarding for X11 clients
* improved logging and debugging tools, fault injection
* more robust error handling and recovery from client errors
* NVENC support for MS Windows shadow servers


## [0.15.8] 2015-11-10
* fix missing files from build clean target
* fix unnecessary auto-refresh events
* fix x265 encoder
* fix libvpx bitrate calculations, reduce logging spam
* fix validation of mmap security token
* fix handling of file transfers before authentication (disallowed)
* fix handling of requests to open files (honour command line / config flag)
* fix MS Windows multiple monitor bug (when primary monitor is re-added)
* fix video encoding automatic selection for encoders that accept RGB directly
* fix the session info sound graphs when sound stops
* fix RPM packaging of the cups backend
* fix the speed and quality values reported to the clients for x264 encoder
* fix OSX El Capitan sound compatibility issue
* fix codec import error handler
* fix compatibility with Python Pillow 3.0.0 (logging issue)
* fix support for Ubuntu Vivid (Xorg still unusable)
* fix batch delay heuristics during resizing and queue overload
* fix "always batch" mode
* fix missing network-send-speed accounting
* fix error in override redirect window geometry handling
* fix invalid error logging call
* fix error in XSettings handling causing connection failures
* fix race condition causing corrupted video streams
* fix unnecessary double refresh on client decoding error
* fix encoding bug triggered when dependencies are missing
* fix window size hints handling
* support Xorg location and arguments required by Arch Linux
* improved lz4 version detection workaround code
* support Xft/DPI
* safer OSX power event handling code
* workaround clients supplying a password when none is required
* log OpenGL driver information
* clamp desktop size to the maximum screen size
* avoid potential errors with bytes-per-pixel confusion with rgb modes
* disable workspace support by default (compatibility issues with some WM)
* always watch for property changes, even without workspace support
* workaround clients supplying a password when none is required
* export shadow servers flag
* run the window opengl cleanup code


## [0.15.7] 2015-10-13
* fix inband info requests
* fix monitor hotplugging workaround code
* fix OSX menus which should not be shown
* fix cursor lookup by name in local theme
* fix max-size support on MS Windows
* fix max-size handling for windows without any constraints (all platforms)
* fix repaint when using the magic key to toggle window borders
* fix iconification handling
* fix connection error when there are XSettings already present
* fix parsing of invalid display structures
* fix video region detection after resize
* fix vpx quality setting
* fix cursor crashes on Ubuntu
* don't show opengl toggle menu if opengl is not supported
* add new common X11 modes (4k, 5k, etc)
* add missing logging category for x265 (fixes warnings on start)


## [0.15.6] 2015-09-13
* fix missing auth argument with Xdummy
* fix oversize print jobs causing disconnections
* fix server-side copy of the client's desktop dimensions
* fix X11 client errors when window managers clear the window state
* fix spurious warnings if X11 desktop properties are not present
* fix server failing to report sound failures (dangling process)
* fix paint errors with cairo backing
* fix window positioning issues when monitors are added (osx and win32)


## [0.15.5] 2015-08-19
* fix encryption not enabled when pycrypto is missing: error out
* fix encryption information leak, free network packets after use
* fix authentication plugins
* fix latency with many sound codecs: vorbis, flac, opus, speex
* fix the desktop naming code (worked by accident)
* fix OpenGL errors with windows too big for the driver
* fix some subcommands when encryption is enabled
* fix spurious errors on closed connections
* fix incorrect colours using CSC Cython fallback module
* fix size limits on Cython fallback module
* fix some invalid Xorg dummy modelines
* fix aspect ratio not honoured and associated warnings
* fix printing file compression
* fix errors in packet layer accounting
* fix regression in python-lz4 version guessing code
* fix RPM packaging: prefer our private libraries to the system ones
* fix pactl output parsing
* fix error on Posix desktop environments without virtual desktops
* fix unlikely connection closing errors
* fix value overflows when unpremultiplying alpha channel
* ship a default configuration file on OSX
* try not to downscale windows from shadow servers
* add vpx-xpra to the RPM dependency list so we get VPX 1.9 support
* make it possible to generate the EXE installer without running it
* allow the user to remove some atoms from _NET_SUPPORTED
* show maximum OpenGL texture size in diagnostics and bug reports
* minor python3 fixes


## [0.15.4] 2015-08-02
* fix delta compression errors
* fix VP8 and VP9 performance when speed command line option is used
* fix application deadlocks on exit
* fix NVENC on cards with over 4GB of RAM
* fix csc Cython red and blue colours swapped on little endian systems
* fix byteswapping fallback code
* fix cleanup error on MS Windows, preventing process termination
* fix pulseaudio device count reported
* fix timer warnings in GTK2 notifier (mostly used on OSX)
* fix sound communication errors not causing subprocess termination
* fix Xorg path detection for Fedora 22 onwards
* fix invalid list of output colorspaces with x264
* fix bug report tool window so it can be used more than once
* fix bug report tool log file error with Vista onwards
* fix bug report screenshots on MS Windows with multiple screens
* fix shadow mode on MS Windows with multiple screens
* fix OpenCL csc module with Python3
* fix OpenCL platform selection override
* fix Python3 Pillow encoding level (must be an integer)
* fix capture of subprocesses return code
* fix Xvfb dependencies for Ubuntu
* fix ldconfig warning on Debian and Ubuntu
* fix warnings with X11 desktop environments without virtual desktops
* fix use of deprecated ffmpeg enum names
* fix client error if built without webp support
* include the CUDA pre-compiled kernels on Debian / Ubuntu (NVENC)
* packaging fixes for printing on Debian / Ubuntu
* updated dependency list for Debian and Ubuntu distros
* don't require a nonsensical display name on OSX and win32
* safer x264 API initialization call
* safer OpenGL platform checks (prevents crashes with wine)
* safer NVENC API call
* safer lz4 version checking code
* workaround invalid "help" options in config files
* ensure any client decoding errors cause a window refresh
* MS Windows build environment cleanup
* Fedora: update PyOpenGL package dependency


## [0.15.3] 2015-07-07
* fix invalid X11 atom
* fix unhandled failure code from libav
* fix default socket permissions when config file is missing
* fix error handling for missing cuda kernels
* fix OpenGL paint early errors
* fix "print" control command with multiple clients
* skip sending invalid packet to client for the "name" control command
* more helpful dpi warning
* support connecting to named unix domain sockets
* OpenGL option can force enable despite platform checks
* replace unsafe deprecated API call in HTML5 client
* more reliable and clean shutdown of connections and threads
* log internal system failures as errors


## [0.15.2] 2015-06-28
* fix rgb encodings can use speed setting
* fix propagation of dynamic attributes for OR windows
* fix invalid warnings in parsing client connection options
* fix handling of the window decorations flag
* fix missing lock around Python logger callback
* fix size-hints with shadow servers
* fix max-size switch
* fix sound process communication errors during failures
* fix invalid options shown in default config file
* add missing file to clean list
* skip unnecessary workarounds with GTK3 client
* cleaner thread cleanup on server exit
* use the safer and slower code with non-OpenGL clients


## [0.15.1] 2015-06-18
* fix window transparency
* fix displayfd Xorg version check: require version 1.13
* fix GUI debug script on OSX
* fix typo in list of supported X11 atoms
* fix exit-with-children: support sharing mode
* fix html option for client only builds
* fix pulseaudio not killed on exit on Ubuntu
* fix signal leak when client disconnects
* include shared mime info file mapping
* blacklist Ubuntu Vivid, which broke Xdummy, again
* don't reject clients providing a password when none is expected
* raise maximum clipboard requests per second to 20
* remove old VP9 performance warnings


## [0.15.0] 2015-04-28
* printer forwarding
* functional HTML5 client
* add session idle timeout switch
* add html command line switch for easily setting up an HTML5 xpra server
* dropped support for Python 2.5 and older, allowing many code cleanups and improvements
* include manual in html format with MS Windows and OSX builds
* add option to control socket permissions (easier setup of containers)
* client log output forwarding to the server
* fixed workarea coordinates detection for MS Windows clients
* improved video region detection and handling
* more complete support for window states (keep above, below, sticky, etc..) and general window manager responsibilities
* allow environment variables passed to children to be specified in the config files
* faster reformatting of window pixels before compression stage
* support multiple delta regions and expire them (better compression)
* allow new child commands to be started on the fly, also from the client's system tray (disabled by default)
* detect mismatch between some codecs and their shared library dependencies
* NVENC SDK support for versions 4 and 5, YUV444 and lossless mode
* libvpx support for vp9 lossless mode, much improved performance tuning
* add support for child commands that do not interfere with "exit-with-children"
* add scaling command line and config file switch for controlling automatic scaling aggressiveness
* sound processing is now done in a separate process (lower latency, and more reliable)
* add more control over sound command line options, so sound can start disabled and still be turned on manually later
* add command line option for selecting the sound source (pulseaudio, alsa, etc)
* show sound bandwidth usage
* better window icon forwarding, especially for non X11 clients
* optimized OpenGL rendering for X11 clients
* handle screen update storms better
* window group-leader support on MS Windows (correct window grouping in the task bar)
* GTK3 port improvements (still work in progress)
* added unit tests which are run automatically during packaging
* more detailed information in xpra info (cursor, CPU, connection, etc)
* more detailed bug report information
* more minimal MS Windows and OSX builds


## [0.14.0] 2014-08-14
* support for lzo compression
* support for choosing the compressors enabled (lz4, lzo, zlib)
* support for choosing the packet encoders enabled (bencode, rencode, yaml)
* support for choosing the video decoders enabled
* built in bug report tool, capable of collecting debug information
* automatic display selection using Xorg "-displayfd"
* better video region support, increased quality for non-video regions
* more reliable exit and cleanup code, hooks and notifications
* prevent SSH timeouts on login password or passphrase input
* automatic launch the correct tool on MS Windows
* OSX: may use the Application Services folder for a global configuration
* removed python-webm, we now use the native cython codec only
* OpenCL: warn when AMD icd is present (causes problems with signals)
* better avahi mDNS error reporting
* better clipboard compression support
* better packet level network tuning
* support for input methods
* xpra info cleanups and improvements (show children, more versions, etc)
* integrated keyboard layout detection on *nix
* upgrade and shadow now ignore start child
* improved automatic encoding selection, also faster
* keyboard layout selection via system tray on *nix
* more Cython compile time optimizations
* some focus issues fixed


## [0.13.9] 2014-08-13
* fix clipboard on OSX
* fix remote ssh start with start-child issues
* use secure "compare_digest" if available
* fix crashes in codec cleanup
* fix video encoding fallback code
* fix fakeXinerama setup wrongly skipped in some cases
* fix connection failures with large screens and uncompressed RGB
* fix Ubuntu trustyi Xvfb configuration
* fix clipboard errors with no data
* fix opencl platform initialization errors


## [0.13.8] 2014-08-06
* fix server early exit when pulseaudio terminates
* fix SELinux static codec library label (make it persistent)
* fix missed auto-refresh when batching
* fix disabled clipboard packets coming through
* fix cleaner client connection shutdown sequence and exit code
* fix resource leak on connection error
* fix potential bug in fallback encoding selection
* fix deadlock on worker race it was meant to prevent
* fix remote ssh server start timeout
* fix avahi double free on exit
* fix png and jpeg painting via gdk pixbuf (when PIL is missing)
* fix webp refresh loops
* honour lz4-off environment variable
* fix proxy handling of raw RGB data for large screen sizes
* fix potential error from missing data in client packets


## [0.13.7] 2014-07-10
* fix x11 server pixmap memory leak
* fix speed and quality values range (1 to 100)
* fix nvenc device allocation errors
* fix unnecessary refreshes with nvenc
* fix "initenv" compatibility with older servers
* don't start child when upgrading or shadowing


## [0.13.6] 2014-06-14
* fix compatibility older versions of pygtk (centos5)
* fix compatibility with python 2.4 (centos5)
* fix AltGr workaround with win32 clients
* fix some missing keys with 'fr' keyboard layout (win32)
* fix installation on systems without python-glib (centos5)
* fix Xorg version detection for Fedora rawhide


v0.13.5-3 2014-06-14
* re-fix opengl compatibility


## [0.13.5] 2014-06-13
* fix use correct dimensions when evaluating video
* fix invalid latency statistics recording
* fix auto-refresh wrongly cancelled
* fix connection via nested ssh commands
* fix statically linked builds of swscale codec
* fix system tray icons when upgrading server
* fix opengl compatibility with older libraries
* fix ssh connection with shells not starting in home directory
* fix keyboard layout change forwarding


## [0.13.4] 2014-06-10
* fix numeric keypad period key mapping on some non-us keyboards
* fix client launcher GUI on OSX
* fix remote ssh start with clean user account
* fix remote shadow start with automatic display selection
* fix avoid scaling during resize
* fix changes of speed and quality via xpra control (make it stick)
* fix xpra info global batch statistics
* fix focus issue with some applications
* fix batch delay use


## [0.13.3] 2014-06-05
* fix xpra upgrade
* fix xpra control error handling
* fix window refresh on inactive workspace
* fix slow cursor updates
* fix error in rgb strict mode
* add missing x11 server type information


## [0.13.2] 2014-06-01
* fix painting of forwarded tray
* fix initial window workspace
* fix launcher with debug option in config file
* fix compilation of x265 encoder
* fix infinite recursion in cython csc module
* don't include sound utilities when building without sound


## [0.13.1] 2014-05-28
* honour lossless encodings
* fix avcodec2 build for Debian jessie and sid
* fix pam authentication module
* fix proxy server launched without a display
* fix xpra info data format (wrong prefix)
* fix transparency with png/L mode
* fix loss of transparency when toggling OpenGL
* fix re-stride code for compatibility with ancient clients
* fix timer reference leak causing some warnings


## [0.13.0] 2014-05-22
* Python3 / GTK3 client support
* NVENC module included in binary builds
* support for enhanced dummy driver with DPI option
* better build system with features auto-detection
* removed unsupported CUDA csc module
* improved buffer support
* faster webp encoder
* improved automatic encoding selection
* support running MS Windows installer under wine
* support for window opacity forwarding
* fix password mode in launcher
* edge resistance for automatic image downscaling
* increased default memory allocation of the dummy driver
* more detailed version information and tools
* stricter handling of server supplied values


## [0.12.6] 2014-05-16
* fix invalid pixel buffer size causing encoding failures
* fix auto-refresh infinite loop, and honour refresh quality
* fix sound sink with older versions of GStreamer plugins
* fix Qt applications crashes caused by a newline in xsettings..
* fix error with graphics drivers only supporting OpenGL 2.x only
* fix OpenGL crash on OSX with the Intel driver (now blacklisted)
* fix global menu entry text on OSX
* fix error in cairo backing cleanup
* fix RGB pixel data buffer size (re-stride as needed)
* avoid buggy swscale 2.1.0 on Ubuntu


## [0.12.5] 2014-05-03
* fix error when clients supply invalid screen dimensions
* fix MS Windows build without ffmpeg
* fix cairo backing alternative
* fix keyboard and sound test tools initialization and cleanup
* fix gcc version test used for enabling sanitizer build options
* fix exception handling in client when called from the launcher
* fix liba## [] dependencies for Debian and Ubuntu builds


## [0.12.4] 2014-04-23
* fix xpra shadow subcommand
* fix xpra shadow keyboard mapping support for non-posix clients
* avoid Xorg dummy warning in log


## [0.12.3] 2014-04-09
* fix mispostioned windows
* fix quickly disappearing windows (often menus)
* fix server errors when closing windows
* fix NVENC server initialization crash with driver version mismatch
* fix rare invalid memory read with XShm
* fix webp decoder leak
* fix memory leak on client disconnection
* fix focus errors if windows disappear
* fix mmap errors on window close
* fix incorrect x264 encoder speed reported via "xpra info"
* fix potential use of mmap as an invalid fallback for video encoding
* fix logging errors in debug mode
* fix timer expired warning


## [0.12.2] 2014-03-30
* fix switching to RGB encoding via client tray
* fix remote server start via SSH
* fix workspace change detection causing slow screen updates


## [0.12.1] 2014-03-27
* fix 32-bit server timestamps
* fix client PNG handling on installations without PIL / Pillow


## [0.12.0] 2014-03-23
* NVENC support for YUV444 mode, support for automatic bitrate tuning
* NVENC and CUDA load balancing for multiple cards
* proxy encoding: ability to encode on proxy server
* fix fullscreen on multiple monitors via fakeXinerama
* OpenGL rendering improvements (for transparent windows, etc)
* support window grabs (drop down menus, etc)
* support specifying the SSH port number more easily
* enabled TCP_NODELAY socket option by default (lower latency)
* add ability to easily select video encoders and csc modules
* add local unix domain socket support to proxy server instances
* add "xpra control" commands to control encoding speed and quality
* improved handling of window resizing
* improved compatibility with command line tools (xdotool, wmctrl)
* ensure windows on other workspaces do not waste bandwidth
* ensure iconified windows do not waste bandwidth
* ensure maximized and fullscreen windows are prioritised
* ensure we reset xsettings when client disconnects
* better bandwidth utilization of jittery connections
* faster network code (larger receive buffers)
* better automatic encoding selection for smaller regions
* improved command line options (add ability to enable options which are disabled in the config file)
* trimmed all the ugly PyOpenGL warnings on startup
* much improved logging and debugging tools
* make it easier to distinguish xpra windows from local windows (border command line option)
* improved build system: smaller and more correct build output (much smaller OSX images)
* improved MS Windows command wrappers
* improved MS Windows (un)installer checks
* automatically stop remote shadow servers when client disconnects
* MS Windows and OSX build updates: updated Pillow, lz4, etc


## [0.11.6] 2014-03-18
* correct fix for system tray forwarding


## [0.11.5] 2014-03-18
* fix "xpra info" with bencoder
* ensure we re-sanitize window size hints when they change
* workaround applications with nonsensical size hints (ie: handbrake)
* fix 32-bit painting with GTK pixbuf loader (when PIL is not installed or disabled)
* fix system tray forwarding geometry issues
* fix workspace restore
* fix compilation warning
* remove spurious cursor warnings


## [0.11.4] 2014-02-29
* fix NVENC GPU memory leak
* fix video compatibility with ancient clients
* fix vpx decoding in ffmpeg decoders
* fix transparent system tray image with RGB encoding
* fix client crashes with system tray forwarding
* fix webp codec loader error handler


## [0.11.3] 2014-02-14
* fix compatibility with ancient versions of GTK
* fix crashes with malformed socket names
* fix server builds without client modules
* honour mdns flag set in config file
* blacklist VMware OpenGL driver which causes client crashes
* ensure all "control" subcommands run in UI thread


## [0.11.2] 2014-01-29
* fix Cython 0.20 compatibility
* fix OpenGL pixel upload alignment code
* fix xpra command line help page tokens
* fix compatibility with old versions of the python glib library


## [0.11.1] 2014-01-24
* fix compatibility with old/unsupported servers
* fix shadow mode
* fix paint issue with transparent tooltips on OSX and MS Windows
* fix pixel format typo in OpenGL logging


## [0.11.0] 2014-01-20
* NVENC hardware h264 encoding acceleration
* OpenCL and CUDA colourspace conversion acceleration
* proxy server mode for serving multiple sessions through one port
* support for sharing a TCP port with a web server
* server control command for modifying settings at runtime
* server exit command, which leaves Xvfb running
* publish session via mDNS
* faster OSX shadow server
* OSX client two way clipboard support
* OSX keyboard improvements, swap command and control keys
* support for transparency with OpenGL window rendering
* support for transparency with 8-bit PNG modes
* support for more authentication mechanisms
* support remote shadow start via ssh
* support faster lz4 compression
* faster bencoder, rewritten in Cython
* builtin fallback colourspace conversion module
* real time frame latency graphs
* improved system tray forwarding support and native integration
* removed most of the Cython/C code duplication
* stricter and safer value parsing
* more detailed status information via UI and "xpra info"
* experimental HTML5 client
* drop non xpra clients with a more friendly response
* handle non-ASCII characters in output on MS Windows
* libvpx 1.3 and ffmpeg 2.1.3 for OSX, MS Windows and static builds


## [0.10.12] 2014-01-14
* fix missing auto-refresh with lossy colourspace conversion
* fix spurious warning from Nvidia OpenGL driver
* fix OpenGL client crash with some drivers (ie: VirtualBox)
* fix crash in bencoder caused by empty data to encode
* fix OSX popup focus issue
* fix ffmpeg2 h264 decoding (ie: Fedora 20+)
* big warnings about webp leaking memory
* generated debuginfo RPMs


## [0.10.11] 2014-01-07
* fix popup windows focus issue
* fix "xpra upgrade" subcommand
* fix server backtrace in error handler
* restore server target information in tray tooltip
* fix bencoder error with no-windows switch (missing encoding)
* add support for RGBX pixel format required by some clients
* avoid ffmpeg "data is not aligned" warning on client
* ensure x264 encoding is supported on MS Windows shadow servers


## [0.10.10] 2013-12-04
* fix focus regression
* fix MS Windows clipboard copy including null byte
* fix h264 decoding with old versions of avcodec
* fix potential invalid read past the end of the buffer
* fix static vpx build arguments
* fix RGB modes exposed for transparent windows
* fix crash on clipboard loops: detect and disable clipboard
* support for ffmpeg version 2.x
* support for video encoding of windows bigger than 4k
* support video encoders that re-start the stream
* fix crash in decoding error path
* forward compatibility with namespace changes
* forward compatibility with the new generic encoding names


## [0.10.9] 2013-11-05
* fix h264 decoding of padded images
* fix plain RGB encoding with very old clients
* fix "xpra info" error when old clients are connected
* remove warning when "help" is specified as encoding


## [0.10.8] 2013-10-22
* fix misapplied patch breaking all windows with transparency


## [0.10.7] 2013-10-22
* fix client crash on Linux with AMD cards and fglrx driver
* fix MS Windows tray forwarding (was broken by fix from 0.10.6)
* fix missing WM_CLASS on X11 clients
* fix Mac OSX shadow server
* fix "xpra info" on shadow servers
* add usable 1366x768 dummy resolution


## [0.10.6] 2013-10-15
* fix window titles reverting to "unknown host"
* fix tray forwarding bug causing client disconnections
* replace previous rencode fix with warning


## [0.10.5] 2013-10-10
* fix client time out when the initial connection fails
* fix shadow mode
* fix connection failures when some system information is missing
* fix client disconnection requests
* fix encryption cipher error messages
* fix client errors when some features are disabled
* fix potential rencode bug with unhandled data types
* error out if the client requests authentication and none is available


## [0.10.4] 2013-09-10
* fix modifier key handling (was more noticeable with MS Windows clients)
* fix auto-refresh


## [0.10.3] 2013-09-06
* fix transient windows with no parent
* fix metadata updates handling (maximize, etc)


## [0.10.2] 2013-08-29
* fix connection error with unicode user name
* fix vpx compilation warning
* fix python 2.4 compatibility
* fix handling of scaling attribute via environment override
* build fix: ensure all builds include source information


## [0.10.1] 2013-08-20
* fix avcodec buffer pointer errors on some 32-bit Linux
* fix invalid time conversion
* fix OpenGL scaling with fractions
* compilation fix for some newer versions of libav
* disable OpenGL on Ubuntu 12.04 and earlier (non functional)
* honour scaling at high quality settings
* add ability to disable transparency via environment variable
* silence PyOpenGL warnings we can do nothing about
* fix CentOS 6.3 packaging dependencies


## [0.10.0] 2013-08-13
* performance: X11 shared memory (XShm) pixels transfers
* performance: zero-copy window pixels to picture encoders
* performance: zero copy decoded pixels to window (but not with OpenGL..)
* performance: multi-threaded x264 encoding and decoding
* support for speed tuning (latency vs bandwidth) with more encodings (png, jpeg, rgb)
* support for grayscale and palette based png encoding
* support for window and tray transparency
* support webp lossless
* support x264's "ultrafast" preset
* support forwarding of group-leader application window information
* prevent slow encoding from creating backlogs
* OpenGL accelerated client rendering enabled by default wherever supported
* register as a generic URL handler
* fullscreen toggle support
* stricter Cython code
* better handling of sound buffering and overruns
* better OSX support, handle UI stalls more gracefully, system trays
* experimental support for a Qt based client
* support for different window layouts with custom widgets
* basic support of OSX shadow servers
* don't try to synchronize with clipboards that do not exist (for shadow servers mostly)
* refactoring: move features and components to sub-modules
* refactoring: split X11 bindings from pure gtk code
* refactoring: codecs split encoding and decoding side
* refactoring: move more common code to utility classes
* refactoring: remove direct dependency on gobject in many places
* refactoring: platform code better separated
* refactoring: move wimpiggy inside xpra, delete parti
* export and expose more version information (x264/vpx/webp/PIL, OpenGL..)
* export compiler information with build (Cython, C compiler, etc)
* export much more debugging information about system state and statistics
* simplify non-UI subcommands and their packets, also use rencode ("xpra info", "xpra version", etc)


## [0.9.8] 2013-07-29
* fix client workarea size change detection (again)
* fix crashes handling info requests
* fix Ubuntu raring clients: must use Xvfb
* fix server hangs due to sound cleanup deadlock
* use lockless window video decoder cleanup (much faster)
* speedup server startup when no XAUTHORITY file exists yet


## [0.9.7] 2013-07-16
* fix error in sound cleanup code
* fix network threads accounting
* fix missing window icons
* fix client availability of remote session start feature


## [0.9.6] 2013-06-30
* fix client exit lockups on MS Windows
* fix lost clicks on some popup menus (mostly with MS Windows clients)
* fix client workarea size change detection
* fix reading of unique "machine-id" on posix
* fix window reference leak for windows we fail to manage
* fix compatibility with pillow (PIL fork)
* fix session-info window graphs jumping (smoother motion)
* fix webp loading code for non-Linux posix systems
* fix window group-leader attribute setting
* fix man page indentation
* fix variable test vs use (correctness only)
* static binary builds updates: Python 2.7.5, flac 1.3, PyOpenGL 3.1, numpy 1.7.1, webp 0.3.1, liba## [] 9.7
* static binary builds switched to using pillow instead of PIL
* forward compatibility with future "xpra info" namespace changes


## [0.9.5] 2013-06-06
* fix auto-refresh: don't refresh unnecessarily
* fix wrong initial timeout when ssh takes a long time to connect
* fix client monitor/resolution size change detection
* fix attributes reported to clients when encoding overrides are used
* Gentoo ebuild uses virtual to allow one to choose pillow or PIL


## [0.9.4] 2013-05-27
* revert cursor scaling fix which broke other applications
* fix auto refresh mis-firing
* fix type (atom) of the X11 visual property we expose


## [0.9.3] 2013-05-20
* fix clipboard for *nix clients
* fix selection timestamp parsing
* fix crash due to logging code location
* fix pixel area request dimensions for lossless edges
* fix advertised tray visual property
* fix cursors are too small with some applications
* fix crash when low level debug code is enabled
* reset cursors when disabling cursor forwarding
* workaround invalid window size hints


## [0.9.2] 2013-05-13
* fix double error when loading build information (missing about dialog)
* fix and simplify build "clean" subcommand
* fix OpenGL rendering alignment for padded rowstrides case
* fix potential double error when tray initialization fails
* fix window static properties usage


## [0.9.1] 2013-05-08
* honour initial client window's requested position
* fix for hidden appindicator
* fix string formatting error in non-cython fallback math code
* fix error if ping packets fail from the start
* fix for windows without a valid window-type (ie: shadows)
* fix OpenGL missing required feature detection (and add debug)
* add required CentOS RPM libXfont dependency
* tag our /etc configuration files in RPM spec file


## [0.9.0] 2013-04-25
* fix focus problems with old Xvfb display servers
* fix RPM SELinux labelling of static codec builds (CentOS)
* fix CentOS 5.x compatibility
* fix Python 2.4 and 2.5 compatibility (many)
* fix clipboard with MS Windows clients
* fix failed server upgrades killing the virtual display
* fix screenshot command with "OR" windows
* fix support for "OR" windows that move and resize
* IP## [6] server support
* support for many more audio codecs: flac, opus, wavpack, wav, speex
* support starting remote sessions with "xpra start"
* support for Xdummy with CentOS 6.4 onwards
* add --log-file command line option
* add clipboard regex string filtering
* add clipboard transfer in progress animation via system tray
* detect broken/slow connections and temporarily grey out windows
* reduce regular packet header sizes using numeric lookup tables
* allow more options in xpra config and launcher files
* MS Windows fixes for Caps Lock and Num Lock synchronization
* MS Windows and OSX builds trim the amount of GStreamer plugins shipped
* MS Windows, OSX and static codec builds (Ubuntu Lucid, Debian Squeeze) updated to liba## [] 9.4
* MS Windows and OSX builds updated to use Python 2.7.4
* MS Windows library updates (pyasn1, numpy, webp)
* OSX library updates (mpfr, x264, pyasn1, numpy, webp), fixed sound packaging
* safer test for windows to ignore (window IDs starts at 1 again)
* expose more version and statistical data via xpra info
* improved OpenGL client rendering (still disabled by default)
* upgrade to rencode 1.0.2


## [0.8.8] 2013-03-07
* fix server deadlock on dead connections
* fix compatibility with older versions of Python
* fix sound capture script usage via command line
* fix screen number preserve code
* fix error in logs in shadow mode


## [0.8.7] 2013-02-27
* fix x264 crash with older versions of libav
* fix 32-bit builds breakage introduce by python2.4 fix in 0.8.6
* fix missing sound forwarding when using the GUI launcher
* fix microphone forwarding errors
* fix client window properties store
* fix first workspace not preserved and other workspace issues
* fix GStreamer-Info.exe output
* avoid creating unused hidden "group" windows on MS Windows clients


## [0.8.6] 2013-02-22
* fix launcher on MS Windows, better SSH support
* fix python2.4 compatibility in icon grabbing code
* fix liba## [] compatibility on MS Windows with VisualStudio
* fix exit message location
* prevent invalid Python bindings version from being included in the MS Windows installer


## [0.8.5] 2013-02-17
* fix server crash with transient windows


## [0.8.4] 2013-02-13
* fix hello packet encoding bug
* fix colours in launcher and session-info windows


## [0.8.3] 2013-02-12
* Python 2.4 compatibility fixes (CentOS 5.x)
* fix static builds of vpx and x264


## [0.8.2] 2013-02-10
* fix liba## [] uninitialized structure crash
* fix warning on installations without sound libraries
* fix warning when pulseaudio utils are not installed
* fix delta compression race
* fix the return of some ghost windows
* stop pulseaudio on exit, warn if it fails to start
* re-enable system tray forwarding, fix location conflicts
* osx fixes: encodings wrongly grayed out
* osx features: add sound and speed menus
* remove spurious "too many receivers" warnings


## [0.8.1] 2013-02-04
* fix server daemonize on some platforms
* fix server SSH support on platforms with old versions of glib
* fix "xpra upgrade" closing applications
* fix detection of almost-lossless frames with x264
* fix starting of a duplicate pulseaudio server on upgrade
* fix debian packaging: lint warnings, add missing sound dependencies
* fix compatibility with older versions of pulseaudio (pactl)
* fix session-info window when a tray is being forwarded
* remove warning on builds with limited encoding support
* disable tray forwarding by default as it causes problems with some apps
* rename "Quality" to "Min Quality" in tray menu
* update to Cython 0.18 for binary builds
* fix rpm packaging: remove unusable modules


## [0.8.0] 2013-01-31
* fix modal windows support
* fix default mouse cursor: now uses the client's default cursor
* fix "double-apple" in menu on OSX
* fix short lived windows: avoid doing unnecessary work, avoid re-registering handlers
* fix limit the number of raw packets per client to prevent DoS via memory exhaustion
* fix authentication: ensure salt is per connection
* fix for ubuntu global application menus
* fix proxy handling of deadly signals
* fix pixel queue size calculations used for performance tuning decisions
* fix ^C exit on MS Windows: ensure we do cleanup the system tray on exit
* edge resistance for colourspace conversion level changes to prevent yoyo effect
* more aggressive picture quality tuning
* better CPU utilization
* new command line options and tray menu to trade latency for bandwidth
* x264 disable unnecessary I-frames and avoid IDR frames
* performance and latency optimizations in critical sections
* avoid server loops: prevent the client from connecting to itself
* group windows according to the remote application they belong to
* sound forwarding (initial code, high latency)
* faster and more reliable client and server exit (from signal or otherwise)
* SSH support on MS Windows
* "xpra shadow" mode to clone an existing X11 display (compositors not supported yet)
* support for delta pixels mode (most useful for shadow mode)
* avoid warnings and X11 errors with the screenshot command
* better mouse cursor support: send cursors by name so their size matches the client's settings
* mitigate bandwidth eating cursor change storms: introduce simple cursor update batching
* support system tray icon forwarding (limited)
* preserve window workspace
* AES packet encryption for TCP mode (without key secure exchange for now)
* launcher entry box for username in SSH mode
* launcher improvements: highlight the password field if needed, prevent warnings, etc
* better window manager specification compatibility (for broken applications or toolkits)
* use lossless encoders more aggressively when possible
* new x264 tuning options: profiles to use and thresholds
* better detection of dead server sockets: retry and remove them if needed
* improved session information dialog and graphs
* more detailed hierarchical per-window details via "xpra info"
* send window icons in dedicated compressed packet (smaller new-window packets, faster)
* detect overly large main packets
* partial/initial Java/AWT keyboard support
* py2exe, ebuild and distutils improvements: faster and cleaner builds, discarding unwanted modules
* OSX and MS Windows build updates: newer py2app, gtk-mac-bundler, pywin32 and support libraries
* OSX command line path fix
* updated libx264 and liba## [] on OSX
* updated Cython to 0.17.4 for all binary builds


## [0.7.8] 2013-01-15
* fix xsettings integer parsing
* fix 'quality' command line option availability check
* workaround Ubuntu's global menus
* better compatibility with old servers: don't send new xsettings format
* avoid logging for normal "clipboard is disabled" case


## [0.7.7] 2013-01-03
* fix quality menu
* fix for clients not using rencoder (ie: Java, Android..)
* fix pixel queue size accounting


## [0.7.6] 2013-01-01
* fix tray options meant to be unusable until connected
* fix auto refresh delay
* fix missing first bell in error case
* fix potential DoS in client disconnection accounting
* fix network calls coming from wrong thread in error case
* fix unlikely locking issue and reduce lock hold time
* fix disconnect all connected clients cleanly
* fix clipboard flag handling
* fix Mac OSX path with spaces handling
* fix server minimum window dimensions with video encoders
* don't bother trying to auto-refresh in lossless modes


## [0.7.5] 2012-12-06
* fix crash on empty keysym
* fix potential division by zero
* fix network queue access from invalid thread
* fix cleanup code on upgrade corner cases
* fix keyboard layout change detection
* try harder to apply keymaps when the number of free keycodes are limited


## [0.7.4] 2012-11-16
* avoid crash with configure events on windows being destroyed
* fix 100% cpu usage with python2.6 server started with no child


## [0.7.3] 2012-11-08
* fix crash with unknown X11 keysyms
* avoid error with focus being given to a destroyed window
* honour window aspect ratio


## [0.7.2] 2012-11-07
* fix version string hiding ssh password prompt
* fix focus handling for applications setting XWMHints.input to False (ie: Java)
* fix ssh shared connection mode: do not kill it on Ctrl-C
* fix sanitization of aspect ratio hints
* fix undefined variable exception in window setup/cleanup code
* fix undefined variable exception in window damage code
* fix dimensions used for calculating the optimal picture encoding
* reduce Xdummy memory usage by limiting to lower maximum resolutions


## [0.7.1] 2012-10-21
* fix division by zero in graphs causing displayed information to stall
* fix multiple tray shown when using the launcher and password authentication fails
* fix override redirect windows cleanup code
* fix keyboard mapping for AltGr with old versions of X11 server
* fix for Mac OSX zero keycode (letter 'a')
* fix for invalid modifiers: try harder to apply valid mappings
* fix gtk import warning with text clients (xpra version, xpra info)


## [0.7.0] 2012-10-08
* Mac DMG client download
* Android APK download
* fix "AltGr" key handling with MS Windows clients (and others)
* fix crash with x264 encoding
* fix crash with fast disappearing tooltip windows
* avoid storing password in a file when using the launcher (except on MS Windows)
* many latency fixes and improvements: lower latency, better line congestion handling, etc
* lower client latency: decompress pictures in a dedicated thread (including rgb24+zlib)
* better launcher command feedback
* better automatic compression heuristics
* support for Xdummy on platforms with only a suid binary installed
* support for 'webp' lossy picture encoding (better and faster than jpeg)
* support fixed picture quality with x264, webp and jpeg (via command line and tray menu)
* support for multiple "start-child" options in config files or command line
* more reliable auto-refresh
* performance optimizations: caching results, avoid unnecessary video encoder re-initialization
* faster re-connection (skip keyboard re-configuration)
* better isolation of the virtual display process and child processes
* show performance statistics graphs on session info dialog (click to save)
* start with compression enabled, even for initial packet
* show more version and client information in logs and via "xpra info"
* client launcher improvements: prevent logging conflict, add version info
* large source layout cleanup, compilation warnings fixed


## [0.6.4] 2012-10-05
* fix bencoder to properly handle dicts with non-string keys
* fix swscale bug with windows that are too small by switch encoding
* fix locking of video encoder resizing leading to missing video frames
* fix crash with compression turned off: fix unicode encoding
* fix lack of locking sometimes causing errors with "xpra info"
* fix password file handling: exceptions and ignore carriage returns
* prevent races during setup and cleanup of network connections
* take shortcut if there is nothing to send


## [0.6.3] 2012-09-27
* fix memory leak in server after client disconnection
* fix launcher: clear socket timeout once connected and add missing options
* fix potential bug in network code (prevent disconnection)
* enable auto-refresh by default since we now use a lossy encoder by default


## [0.6.2] 2012-09-25
* fix missing key frames with x264/vpx: always reset the video encoder when we skip some frames (forces a new key frame)
* fix server crash on invalid keycodes (zero or negative)
* fix latency: isolate per-window latency statistics from each other
* fix latency: ensure we never record zero or even negative decode time
* fix refresh: server error was causing refresh requests to be ignored
* fix window options handling: using it for more than one value would fail
* fix video encoder/windows dimensions mismatch causing missing key frames
* fix damage options merge code (options were being squashed)
* ensure that small lossless regions do not cancel the auto-refresh timer
* restore protocol main packet compression and single chunk sending
* drop unnecessary OpenGL dependencies from some deb/rpm packages


## [0.6.1] 2012-09-14
* fix compress clipboard data (previous fix was ineffectual)
* fix missing damage data queue statistics (was causing latency issues)
* use memory aligned allocations for colourspace conversion


## [0.6.0] 2012-09-08
* fix launcher: don't block the UI whilst connecting, and use a lower timeout, fix icon lookup on *nix
* fix clipboard contents too big (was causing connection drops): try to compress them and just drop them if they are still too big
* x264 or vpx are now the default encodings (if available)
* compress rgb24 pixel data with zlib from the damage thread (rather than later in the network layer)
* better build environment detection
* experimental multi-user support (see --enable-sharing)
* better, more accurate "xpra info" statistics (per encoding, etc)
* tidy up main source directory
* simplify video encoders/decoders setup and cleanup code
* many debian build files updates
* remove 'nogil' switch (as 'nogil' is much faster)
* test all socket types with automated tests


## [0.5.4] 2012-09-08
* fix man page typo
* fix non bash login shell compatibility
* fix xpra screenshot argument parsing error handling
* fix video encoding mismatch when switching encoding
* fix ssh mode on OpenBSD


## [0.5.3] 2012-09-05
* zlib compatibility fix: use chunked decompression when supported (newer versions)


## [0.5.2] 2012-08-29
* fix xpra launcher icon lookup on *nix
* fix big clipboard packets causing disconnection: just drop them instead
* fix zlib compression in raw packet mode: ensure we always flush the buffer for each chunk
* force disconnection after irrecoverable network parsing error
* fix window refresh: do not skip all windows after a hidden one!
* Fedora 16 freshrpms spec file fix: build against rpmfusion despite more limited csc features


## [0.5.1] 2012-08-25
* fix xpra_launcher
* fix DPI issue with Xdummy: set virtual screen to 96dpi by default
* avoid looping forever doing maths on 'infinity' value
* fix incomplete cloning of attributes causing default values to be used for batch configuration
* damage data queue batch factor was being calculated but not used
* ensure we update the data we use for calculations (was always using zero value)
* ensure "send_bell" is initialized before use
* add missing path string in warning message
* fix test code compatibility with older xpra versions
* statistics shown for 'damage_packet_queue_pixels' were incorrect


## [0.5.0] 2012-08-20
* new packet encoder written in C (much faster and data is now smaller too)
* read provided /etc/xpra/xpra.conf and user's own ~/.xpra/xpra.conf
* support Xdummy out of the box on platforms with recent enough versions of Xorg (and not installed suid)
* pass dpi to server and allow clients to specify dpi on the command line
* fix xsettings endianness problems
* fix clipboard tokens sent twice on start
* new command line options and UI to disable notifications forwarding, cursors and bell
* MS Windows clients can now choose the remote clipboard they sync with ('clipboard', 'primary' or 'secondary')
* x264: adapt colourspace conversion, encoding speed and picture quality according to link and encoding/decoding performance
* automatically change video encoding: handle small region updates (ie: blinking cursor or spinner) without doing a full video frame refresh
* fairer window batching calculations, better performance over low latency links and bandwidth constrained links
* lower tcp socket connection timeout (10 seconds)
* better compression of cursor data
* log date and time with messages, better log messages (ie: "Ignoring ClientMessage..")
* send more client and server version information (python, gtk, etc)
* build cleanups: let distutils clean take care of removing all generated .c files
* code cleanups: move all win32 specific headers to win32 tree, fix vpx compilation warnings, whitespace, etc
* more reliable MS Windows build: detect missing/wrong DLLs and abort
* removed old "--no-randr" option
* drop compatibility with versions older than 0.3: we now assume the "raw_packets" feature is supported


## [0.4.2] 2012-08-16

* fix clipboard atom packing (was more noticeable with qt and Java applications)
* fix clipboard selection for non X11 clients: only 'multiple' codepath requires X11 bindings
* fix python3 build
* fix potential double free in x264 error path
* fix logging format error on "window dimensions have changed.." (parameter grouping was wrong)
* fix colour bleeding with x264 (ie: green on black text)
* remove incorrect and unnecessary callback to setup_xprops which may have caused the pulseaudio flag to use the wrong value
* delay 'check packet size' to allow the limit to be raised - important over slower links where it triggers more easily


## [0.4.1] 2012-07-31
* fix clipboard bugs
* fix batch delay calculations with multiple windows
* fix tests (update import statements)
* robustify cython version string parsing
* fix source files changed detection during build


## [0.4.0] 2012-07-23
* fix client application resizing its own window
* fix window dimensions hints not applied
* fix memleak in x264 cleanup code
* fix xpra command exit code (more complete fix)
* fix latency bottleneck in processing of damage requests
* fix free uninitialized pointers in video decoder initialization error codepath
* fix x264 related crash when resizing windows to one pixel width or height
* fix accounting of client decode time: ignore figure in case of decoding error
* fix subversion build information detection on MS Windows
* fix some binary packages which were missing some menu icons
* restore keyboard compatibility code for MS Windows and OSX clients
* use padded buffers to prevent colourspace conversion from reading random memory
* release Python's GIL during vpx and x264 compression and colourspace conversion
* better UI launcher: UI improvements, detect encodings, fix standalone/win32 usage, minimize window once the client has started
* "xpra stop" disconnects all potential clients cleanly before exiting
* x264 uses memory aligned buffer for better performance
* avoid vpx/x264 overhead for very small damage regions
* detect dead connection with ping packets: disconnect if echo not received
* force a full refresh when the encoding is changed
* more dynamic framerate performance adjustments, based on more metrics
* new menu option to toggle keyboard sync at runtime
* vpx/x264 runtime imports: detect broken installations and warn, but ignore when the codec is simply not installed
* enable environment debugging for damage batching via "XPRA_DEBUG_LATENCY" en## [] variable
* simplify build by using setup file to generate all constants
* text clients now ignore packets they are not meant to handle
* removed compression menu since the default is good enough
* "xpra info" reports all build version information
* report server pygtk/gtk versions and show them on session info dialog and "xpra info"
* ignore dependency issues during sdist/clean phase of build
* record more statistics (mostly latency) in test reports
* documentation and logging added to code, moved test code out of main packages
* better MS Windows installer graphics
* include distribution name in RPM version/filename
* CentOS 6 RPMs now depends on libvpx rather than a statically linked library
* CentOS static ffmpeg build with memalign for better performance
* debian: build with hardening features
* debian: don't record as modified the files we know we modify during debian build
* MS Windows build: allow user to set --without-vpx / --without-x264 in the batch file
* MS Windows build fix: simpler/cleaner build for vpx/x264's codec.pyd
* no longer bundle parti window manager


## [0.3.3] 2012-07-10
* do not try to free the empty x264/vpx buffers after a decompression failure
* fix xpra command exit code (zero) when no error occurred
* fix Xvfb deadlock on shutdown
* fix wrongly removing unix domain socket on startup failure
* fix wrongly killing Xvfb on startup failure
* fix race in network code and meta data packets
* ensure clients use raw_packets if the server supports it (fixes 'gibberish' compressed packet errors)
* fix screen resolution reported by the server
* fix maximum packet size check wrongly dropping valid connections
* honour the --no-tray command line argument
* detect Xvfb startup failures and avoid taking over other displays
* don't record invalid placeholder value for "server latency"
* fix missing "damage-sequence" packet for sequence zero
* fix window focus with some Tk based application (ie: git gui)
* prevent large clipboard packets from causing the connection to drop
* fix for connection with older clients and server without raw packet support and rgb24 encoding
* high latency fix: reduce batch delay when screen updates slow down
* non-US keyboard layout fix
* correctly calculate min_batch_delay shown in statistics via "xpra info"
* require x264-libs for x264 support on Fedora


## [0.3.2] 2012-06-04
* fix missing 'a' key using OS X clients
* fix debian packaging for xpra_launcher
* fix unicode decoding problems in window title
* fix latency issue


## [0.3.1] 2012-05-29
* fix DoS in network connections setup code
* fix for non-ascii characters in source file
* log remote IP or socket address
* more graceful disconnection of invalid clients
* updates to the man page and xpra command help page
* support running the automated tests against older versions
* "xpra info" to report the number of clients connected
* use xpra's own icon for its own windows (about and info dialogs)


## [0.3.0] 2012-05-20
* zero-copy network code, per packet compression
* fix race causing DoS in threaded network protocol setup
* fix vpx encoder memory leak
* fix vpx/x264 decoding: recover from frame failures
* fix small per-window memory leak in server
* per-window update batching auto-tuning, which is fairer
* windows update batching now takes into account the number of pixels rather than just the number of regions to update
* support --socket-dir option over ssh
* IP## [6] support using the syntax: ssh/::ffff:192.168.1.100/10 or tcp/::ffff:192.168.1.100/10000
* all commands now return a non-zero exit code in case of failure
* new "xpra info" command to report server statistics
* prettify some of the logging and error messages
* avoid doing most of the keyboard setup code when clients are in read-only mode
* Solaris build files
* automated regression and performance tests
* remove compatibility code for versions older than 0.1


## [0.2.0] 2012-04-20
* x264 and vpx video encoding support
* gtk3 and python 3 partial support (client only - no keyboard support)
* detect missing X11 server extensions and exit with error
* X11 server no longer listens on a TCP port
* clipboard fixes for Qt/KDE applications
* option for clients not to supply any keyboard mapping data (the server will no longer complain)
* show more system version information in session information dialog
* hide window decorations for openoffice splash screen (workaround)


## [0.1.0] 2012-03-21
* security: strict filtering of packet handlers until connection authenticated
* prevent DoS: limit number of concurrent connections attempting login 20
* prevent DoS: limit initial packet size (memory exhaustion: 32KB)
* mmap: options to place sockets in /tmp and share mmap area across users via unix groups
* remove large amount of compatibility code for older versions
* fix for Mac OS X clients sending hexadecimal keysyms
* fix for clipboard sharing and some applications (ie: Qt)
* notifications systems with dbus: re-connect if needed
* notifications: try not to interfere with existing notification services
* mmap: check for protected file access and ignore rather than error out (oops)
* clipboard: handle empty data rather than timing out
* spurious warnings: remove many harmless stacktraces/error messages
* detect and discard broken windows with invalid atoms, avoids vfb + xpra crash
* unpress keys all keys on start (if any)
* fix screen size check: also check vertical size is sufficient
* fix for invisible 0 by 0 windows: restore a minimum size
* fix for window dimensions causing enless resizing or missing window contents
* toggle cursors, bell and notifications by telling the server not to bother sending them, saves bandwidth
* build/deploy: don't modify file in source tree, generate it at build time only
* add missing GPL2 license file to show in about dialog
* Python 2.5: workarounds to restore support
* turn off compression over local connections (when mmap is enabled)
* Android fixes: locking, maximize, focus, window placement, handle rotation, partial non-soft keyboard support
* clients can specify maximum refresh rate and screen update batching options


## [0.0.7.36] 2012-02-09
* fix clipboard bug which was causing Java applications to crash
* ensure we always properly disconnect previous client when new connection is accepted
* avoid warnings with Java applications, focus errors, etc


## [0.0.7.35] 2012-02-01
* ssh password input fix
* osx dock_menu fixed
* ability to take screenshots ("xpra screenshot")
* report server version ("xpra version")
* slave windows (drop down menus, etc) now move with their parent window
* show more session statistics: damage regions per second
* posix clients no longer interfere with the GTK/X11 main loop
* ignore missing properties when they are changed, and report correct source of the problem
* code style cleanups and improvements


## [0.0.7.34] 2012-01-19
* security: restrict access to run-xpra script (chmod)
* security: cursor data sent to the client was too big (exposing server memory)
* fix thread leak - properly this time, SIGUSR1 now dumps all threads
* off-by-one keyboard mapping error could cause modifiers to be lost
* pure python/cython method for finding modifier mappings (faster and more reliable)
* retry socket read/write after temporary error EINTR
* avoid warnings when asked to refresh windows which are now hidden
* auto-refresh was using an incorrect window size
* logging formatting fixes (only shown with logging on)
* hide picture encoding menu when mmap in use (since it is then ignored)


## [0.0.7.33] 2012-01-13
* readonly command line option
* correctly stop all network related threads on disconnection
* faster pixel data transfers for large areas via mmap
* fix auto-refresh jpeg quality
* fix on-the-fly change of pixel encoding
* fix potential exhaustion of mmap area
* fix potential race in packet compression setup code
* keyboard: better modifiers detection, synchronization of capslock and numlock
* keyboard: support all modifiers correctly with and without keyboard-sync option


## [0.0.7.32] 2011-12-08
* bug fix: disconnection could leave the server (and X11 server) in a broken state due to threaded UI calls
* bug fix: don't remove window focus when just any connection is lost, only when the real client goes away
* bug fix: initial windows should get focus (partial fix)
* bug fix: correctly clear focus when a window goes away
* support key repeat latency workaround without needing raw keycodes (OS X and MS Windows)
* command line switch to enable client side key repeat: "--no-keyboard-sync" (for high latency/jitter links)
* session info dialog: shows realtime connection and server details
* menu entry in system tray to raise all managed windows
* key mappings: try harder to unpress all keys before setting the new keymap
* key mappings: try to reset modifier keys as well as regular keys
* key mappings: apply keymap using Cython code rather than execing xmodmap
* key mappings: fire change callbacks only once when all the work is done
* use dbus for tray notifications if available, preferred to pynotify
* show full version information in about dialog


## [0.0.7.31] 2011-11-28
* threaded server for much lower latency
* fast memory mapped transfers for local connections
* adaptive damage batching, fixes window refresh
* xpra "detach" command
* fixed system tray for Ubuntu clients
* fixed maximized windows on Ubuntu clients


## [0.0.7.30] 2011-11-01
* fix for update batching causing screen corruption
* fix AttributeError jpegquality: make PIL (aka python-imaging) truly optional
* fix for jitter compensation code being a little bit too trigger-happy


## [0.0.7.29] 2011-10-25
* fix partial packets on boundary causing connection to drop
* clipboard support on MS Windows
* support ubuntu's appindicator (yet another system tray implementation)
* improve disconnection diagnostic messages
* scale cursor down to the client's default size
* better handling of right click on system tray icon
* posix: detect when there is no DISPLAY and error out
* remove harmless warnings about missing properties on startup


## [0.0.7.28] 2011-10-18
* much more efficient and backwards compatible network code, prevents a CPU bottleneck on the client
* forwarding of system notifications, system bell and custom cursors
* system tray menu to make it easier to change settings and disconnect
* automatically resize Xdummy to match the client's screen size whenever it changes
* PNG image compression support
* JPEG and PNG compression are now optional, only available if the Python Imaging Library is installed
* scale window icons before sending if they are too big
* fixed keyboard mapping for OSX and MS Windows clients
* compensate for line jitter causing keys to repeat
* fixed cython warnings, unused variables, etc


## [0.0.7.27] 2011-09-20
* compatibility fix for python 2.4 (remove "with" statement)
* slow down updates from windows that refresh continuously


## [0.0.7.26] 2011-09-20
* minor changes to support the Android client (work in progress)
* allow keyboard shortcuts to be specified, default is meta+shift+F4 to quit (disconnects client)
* clear modifiers when applying new keymaps to prevent timeouts
* reduce context switching in the network read loop code
* try harder to close connections cleanly
* removed some unused code, fixed some old test code


## [0.0.7.25] 2011-08-31
* Proper keymap and modifiers support


## [0.0.7.24] 2011-08-15
* Use raw keycodes whenever possible, should fix keymapping issues for all Unix-like clients
* Keyboard fixes for AltGr and special keys for non Unix-like clients


v0.0.7.23-2 2011-07-27
* More keymap fixes..


## [0.0.7.23] 2011-07-20
* Try to use setxkbmap before xkbcomp to setup the matching keyboard layout
* Handle keyval level (shifted keys) explicitly, should fix missing key mappings
* More generic option for setting window titles
* Exit if the server dies


## [0.0.7.22] 2011-06-02
* minor fixes: jpeg, man page, etc


## [0.0.7.21] 2011-05-24
  New features:
* Adaptive JPEG mode (bandwidth constrained)
* Use an existing display
* Disable randr


## [0.0.7.20] 2011-05-04
* more reliable fix for keyboard mapping issues


## [0.0.7.19] 2011-04-25
* xrandr support when running against Xdummy, screen resizes on demand
* fixes for keyboard mapping issues: multiple keycodes for the same key


v0.0.7.18-2 2011-04-04
* Fix for older distros (like CentOS) with old versions of pycairo


## [0.0.7.18] 2011-03-28
* Fix jpeg compression on MS Windows
* Add ability to disable clipboard code
* Updated man page


## [0.0.7.17] 2011-04-04
* Honour the pulseaudio flag on client


## [0.0.7.16] 2010-08-25
* Merged upstream changes


## [0.0.7.15] 2010-07-01
* Add option to disable Pulseaudio forwarding as this can be a real network hog
* Use logging rather than print statements


## [0.0.7.13] 2010-05-04
* Ignore minor version differences in the future (must bump to 0.0.8 to cause incompatibility error)


## [0.0.7.12] 2010-03-13
* bump screen resolution


## [0.0.7.11] 2010-01-11
* first rpm spec file


## [v0.0.7.x] 2009
* Start of this fork
* Password file support
* Better OSX/win32 support
* JPEG compression
* Lots of small fixes


## [0.0.6] 2009-03-22
### Xpra New features:
* Clipboard sharing (with full X semantics).
* Icon support.
* Support for raw TCP sockets. Insecure if you don't know what
you are doing.

### Xpra Bug fixes:
* Xvfb doesn't support mouse wheels, so they still don't work in
xpra. But now xpra doesn't crash if you try.
* Running FSF Emacs under xpra no longer creates an infinite loop.
* The directory that xpra was launched from is now correctly
saved in ~/.xpra/run-xpra.
* Work around PyGtk weirdness that caused the server and client
to sometimes ignore control-C.
* The client correctly notices keyboard layout changes.
* The client no longer crashes on keymaps in which unnamed keys
are bound to modifiers.
* Workarounds are included for several buggy versions of Pyrex.

### Wimpiggy:
* Assume that EWMH-style icons have non-premultiplied alpha.

### Other:
* Add copyright comments to all source files.


## [0.0.5] 2008-11-02
This release primarily contains cleanups and bugfixes for xpra.

### General:
* Logging cleanup -- all logging now goes through the Python
logging framework instead of using raw 'prints'.  By default
debug logging is suppressed, but can be enabled in a fine- or
coarse-grained way.

### Xpra:
* Protocol changes; ## [0.0.5] clients can only be used with v0.0.5
servers, and vice-versa.  Use 'xpra upgrade' to upgrade old
servers without losing your session state.
* Man page now included.
### Important bug fixes:
* Qt apps formerly could not receive keyboard input due to a focus
handling bug; now fixed.
* Fedora's pygtk2 has mysterious local hacks that broke xpra;
a workaround is now included.
### UI improvements:
* 'xpra attach ssh:machine' now works out-of-the-box even if xpra
is not present in the remote machine's PATH, or requires
PYTHONPATH tweaks, or whatever.  (The server does still need to
be running on the remote machine, though, of course.)
* Commands that connect to a running xpra server ('attach', 'stop',
etc.) now can generally be used without specifying the name of
the server, assuming only one server is running.  (E.g., instead
of 'xpra attach :10', you can use 'xpra attach'; ditto for remote
hosts, you can now use plain 'xpra attach ssh:remote'.)
* Mouse scroll wheels now supported.
* 'xpra start' can now spawn child programs directly (--with-child)
and exit automatically when these children have exited
(--exit-with-children).
### Other:
* More robust strategy for handling window stacking order.
(Side-effect: the xpra client no longer requires you to be using
an EWMH-compliant window manager.)
* The xpra client no longer crashes when receiving an unknown key
event (e.g. a multimedia key).
* Very brief transient windows (e.g., tooltips) no longer create
persistent "litter" on the screen.
* Windows with non-empty X borders (e.g., xterm popup menus) are
now handled properly.
* Withdrawn windows no longer reappear after 'xpra upgrade'.

### Wimpiggy:
* Do not segfault when querying the tree structure of destroyed
windows.
* Other bugfixes.

### Parti:
* No changes.

## [0.0.4] 2008-04-04
### Xpra:
* Protocol changes break compatibility with 0.0.3, but:
* New command 'xpra upgrade', to restart/upgrade an xpra server
without losing any client state.  (Won't work when upgrading from
0.0.3, unfortunately, but you're covered going forward.)
* Fix bug that left stray busy-looping processes behind on server
when using ssh connections.
* Export window class/instance hints (patch from Ethan Blanton).
* Hack to make backspace key work (full support for keyboard maps
still TBD).
* Added discussion of xmove to README.xpra.

### Wimpiggy:
* Make compatible with current Pyrex releases (thanks to many
 people for reporting this).
* Work around X server bug #14648 (thanks to Ethan Blanton for help
 tracking this down).  This improves speed dramatically.
* Reverse-engineer X server lifetime rules for NameWindowPixmap,
 and handle it properly.  Also handle it lazily.  This fixes the
 bug where window contents stop updating.
* Avoid crashing when acknowledging damage against an
 already-closed window.
* Improve server extension checking (thanks to 'moreilcon' for the
 report).
* Remove spurious (and harmless) assertion messages when a window
 closes.
* Make manager selection handling fully ICCCM-compliant (in
 particular, we now pause properly while waiting for a previous
 window manager to exit).
* Make algorithm for classifying unmapped client windows fully
 correct.
* Reduce required version of Composite extension to 0.2.

### Parti:
* Remove a stale import that caused a crash at runtime (thanks to
 'astronouth7303' for the report).

### General:
* Error out build with useful error message if required packages
 are missing.

## Parti 0.0.3 2008-02-20
Massive refactoring occurred for this release.

### wimpiggy:
The WM backend parts of Parti have been split off into a
separate package known as wimpiggy.  As compared to the corresponding
code in 0.0.2, wimpiggy 0.0.3 adds:
* Compositing support
* Model/view separation for client windows (based on compositing
 support)
* Improved client hint support, including icon handling, strut
 handling, and more correct geometry handling.
* Keybinding support
* Event dispatching that doesn't leak memory
* Better interaction with already running window managers (i.e., a
 --replace switch as seen in metacity etc.)

### parti:
This package will eventually become the real window manager,
but for now is essentially a testbed for wimpiggy.

### xpra:
This is a new, independent program dependent on wimpiggy (which
is why wimpiggy had to be split out).  It implements 'screen for X' --
letting one run applications remotely that can be detached and then
re-attached without losing state.  This is the first release, but
while not perfect, it is substantially usable.

### general:
The test runner was hacked to share a single X/D-Bus session
across multiple tests.  This speeds up the test suite by a factor of
~3, but seems to be buggy and fragile and may be reverted in the
future.


## Parti 0.0.2 2007-10-26
This release adds a mostly comprehensive test suite, plus fixes a lot
of bugs.  Still only useful for experimentation and hacking.

'python setup.py sdist' sort of works now.


## Parti 0.0.1 2007-08-10
Initial release.

Contains basic window manager functionality, including a fair amount
of compliance to ICCCM/EWMH, focus handling, etc., and doesn't seem to
crash in basic testing.

Doesn't do much useful with this; only a simple placeholder layout
manager is included, and only skeleton of virtual desktop support is
yet written.
