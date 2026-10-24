# CVEs

Every vulnerability matched against the [SBOM](https://en.wikipedia.org/wiki/Software_supply_chain) of the MS Windows builds,
since 2026-10-22 for the stable builds (the beta and LTS builds will be added later).

The [SBOM vulnerabilities workflow](../../.github/workflows/sbom.yml) scans the latest builds every day,
using the CPE and PURL references maintained by MSYS2 ([`msys2_sbom.py`](../../packaging/MSWindows/msys2_sbom.py)),
and fails when it finds a vulnerability which is not recorded below,
unless it only affects one of the [ignored packages](#ignored-packages).

| Column | |
|---|---|
| `CVE` | the vulnerability, in numerical order |
| `Package` | the packages it was matched against |
| `Severity` | as reported by the scanner |
| `Issue` | short description |
| `Upstream fix` | the first upstream version that fixes it, when known |
| `Live` | `🔴 on` if it applies to our builds, `off` if it does not (false positive, code we do not use, etc - say why in `Notes`): the scans no longer report it |
| `First xpra version` | the xpra version(s) where it was first found |
| `Fixed in xpra` | the first xpra version(s) with the fix |
| `Ticket` | link to the issue tracking it, if needed |
| `Notes` | analysis |

## Ignored packages

Some libraries are only bundled because another library we need links against them,
but the code paths that would use them are never reached.
The scans ignore every vulnerability found in these packages.

| Package | Reason |
|---|---|
| `libssh2` | only used by `curl` for `scp://` and `sftp://` URLs, which nothing gives it: xpra's own ssh connections use `paramiko` or the bundled OpenSSH |
| `p11-kit` | `gnutls` links against it, but its PKCS#11 modules are not bundled (`BUILD.py` deletes `lib/p11-kit*`), so there is nothing to load or talk to |

## Vulnerabilities

New vulnerabilities are added with:
```shell
curl -sSfLO https://xpra.org/stable/windows/Xpra-x86_64_6.5.5-r0.json
python3 packaging/MSWindows/msys2_sbom.py Xpra-x86_64_6.5.5-r0.json sbom.json
GRYPE_MATCH_PYTHON_USING_CPES=true GRYPE_MATCH_RUST_USING_CPES=true grype sbom:sbom.json --by-cve -o json > grype.json
python3 packaging/MSWindows/sbom_vulnerabilities.py --scan 6.5.5-r0 grype.json --update
```

| CVE | Package | Severity | Issue | Upstream fix | Live | First xpra version | Fixed in xpra | Ticket | Notes |
|---|---|---|---|---|---|---|---|---|---|
| CVE-2005-2975 | gdk-pixbuf2 | High | io-xpm.c in the gdk-pixbuf XPM image rendering library in GTK+ before 2.8.7 allows attackers to cause a denial of service (infinite loop) via a crafted XPM... |  | off | 6.5.5-r0 |  |  | GTK+ 2.x XPM loader bug, fixed in 2005: NVD's CPE has no version bound |
| CVE-2005-3186 | gdk-pixbuf2 | High | Integer overflow in the GTK+ gdk-pixbuf XPM image rendering library in GTK+ 2.4.0 allows attackers to execute arbitrary code via an XPM file with a number... |  | off | 6.5.5-r0 |  |  | GTK+ 2.x XPM loader bug, fixed in 2005: NVD's CPE has no version bound |
| CVE-2021-30473 | aom | Critical | aom_image.c in libaom in AOMedia before 2021-04-07 frees memory that is not located on the heap. | 2021-04-07 | off | 6.5.5-r0 |  |  | fixed in 2021, the scanner compares our version with a date |
| CVE-2021-30474 | aom | Critical | aom_dsp/grain_table.c in libaom in AOMedia before 2021-03-30 has a use-after-free. | 2021-03-30 | off | 6.5.5-r0 |  |  | fixed in 2021, the scanner compares our version with a date |
| CVE-2021-30475 | aom | Critical | aom_dsp/noise_model.c in libaom in AOMedia before 2021-03-24 has a buffer overflow. | 2021-03-24 | off | 6.5.5-r0 |  |  | fixed in 2021, the scanner compares our version with a date |
| CVE-2022-45142 | heimdal-libs | High | The fix for CVE-2022-3437 included changing memcmp to be constant time and a workaround for a compiler bug by adding "!= 0" comparisons to the result of memcmp. | unreleased | off | 6.5.5-r0 |  |  | the inverted RC4-HMAC checksum checks are present in heimdal 7.8.0 and MSYS2 does not patch them, but these libraries are only bundled for `ssh.exe`, and the OpenSSH client only creates GSSAPI tokens: it never verifies or unwraps any, unless patched for `gssapi-keyex`, which MSYS2's OpenSSH is not |
| CVE-2023-4039 | gcc-libs | Medium | **DISPUTED**A failure in the -fstack-protector feature in GCC-based toolchains that target AArch64 allows an attacker to exploit an existing buffer overflow... | 2023-09-12 | off | 6.5.5-r0 |  |  | AArch64 only, disputed, and the scanner compares our version with a date |
| CVE-2023-37769 | pixman | Medium | stress-test master commit e4c878 was discovered to contain a FPE vulnerability via the component combine_inner at /pixman-combine-float.c. |  | off | 6.5.5-r0 |  |  | in pixman's `stress-test` program, not in the library |
| CVE-2023-39327 | openjpeg2 | Medium | Maliciously constructed pictures can cause the program to enter a large loop and continuously print warning messages on the terminal. | [unreleased](https://github.com/uclouvain/openjpeg/pull/1616) | off | 6.5.5-r0 |  |  | no fix upstream and MSYS2 does not patch them, NVD's CPE has no version bound, but nothing reaches the decoder: Pillow is the only user of libopenjp2 and `BUILD.py` deletes its `Jpeg2KImagePlugin`, and xpra only accepts png, jpeg and webp image data anyway |
| CVE-2023-39328 | openjpeg2 | Medium | A vulnerability was found in OpenJPEG similar to CVE-2019-6988. This flaw allows an attacker to bypass existing protections and cause an application crash... | unreleased | off | 6.5.5-r0 |  |  | no fix upstream and MSYS2 does not patch them, NVD's CPE has no version bound, but nothing reaches the decoder: Pillow is the only user of libopenjp2 and `BUILD.py` deletes its `Jpeg2KImagePlugin`, and xpra only accepts png, jpeg and webp image data anyway |
| CVE-2023-39329 | openjpeg2 | Medium | A resource exhaustion can occur in the opj_t1_decode_cblks function in tcd.c through a crafted image file, causing a denial of service. | unreleased | off | 6.5.5-r0 |  |  | no fix upstream and MSYS2 does not patch them, NVD's CPE has no version bound, but nothing reaches the decoder: Pillow is the only user of libopenjp2 and `BUILD.py` deletes its `Jpeg2KImagePlugin`, and xpra only accepts png, jpeg and webp image data anyway |
| CVE-2023-50979 | crypto++ | Medium | Crypto++ (aka cryptopp) through 8.9.0 has a Marvin side channel during decryption with PKCS#1 v1.5 padding. |  | off | 6.5.5-r0 |  |                                     | unused, removed from the next release |
| CVE-2023-50980 | crypto++ | High | gf2n.cpp in Crypto++ (aka cryptopp) through 8.9.0 allows attackers to cause a denial of service (application crash) via DER public-key data for an F(2^m)... |  | off | 6.5.5-r0 |  | | unused, removed from the next release |
| CVE-2023-50981 | crypto++ | High | ModularSquareRoot in Crypto++ (aka cryptopp) through 8.9.0 allows attackers to cause a denial of service (infinite loop) via crafted DER public-key data... |  | off | 6.5.5-r0 |  | | unused, removed from the next release |
| CVE-2025-6021 | libxml2 | High | A flaw was found in libxml2's xmlBuildQName function, where integer overflows in buffer size calculations can lead to a stack-based buffer overflow. | 2.14.4 | off | 6.5.5-r0 |  |  | false positive: NVD lists every version from 2.0.0 onwards as affected, but the [fix](https://gitlab.gnome.org/GNOME/libxml2/-/issues/926) is in libxml2 2.14.4 and the stable builds ship 2.15.4 |
| CVE-2025-6170 | libxml2 | Low | A flaw was found in the interactive shell of the xmllint command-line tool, used for parsing XML files. |  | off | 6.5.5-r0 |  |  | in the interactive shell of `xmllint`, which we do not ship |
| CVE-2025-15367 | python | Medium | The poplib module, when passed a user-controlled command, can have additional commands injected using newlines. | 3.15.0a6 | off | 6.5.5-r0 |  |  | unused and unreachable: xpra does not use the `poplib` module |
| CVE-2025-32989 | gnutls | Medium | A heap-buffer-overread vulnerability was found in GnuTLS in how it handles the Certificate Transparency (CT) Signed Certificate Timestamp (SCT) extension... | 3.8.10 | off | 6.5.5-r0 |  |  | false positive: NVD lists every version as affected, but the fix ([GNUTLS-SA-2025-07-07-1](https://gnutls.org/security-new.html#GNUTLS-SA-2025-07-07-1)) is in gnutls 3.8.10 and the stable builds ship 3.8.13 |
| CVE-2025-32990 | gnutls | High | A heap-buffer-overflow (off-by-one) flaw was found in the GnuTLS software in the template parsing logic within the certtool utility. |  | off | 6.5.5-r0 |  |  | in the `certtool` utility, which we do not ship |
| CVE-2025-50422 | cairo | Low | Cairo through 1.18.4, as used in Poppler through 25.08.0, has an "unscaled->face == NULL" assertion failure for _cairo_ft_unscaled_font_fini in cairo-ft-font.c. |  | off | 6.6-r41819, 7.0-r42750 |  |  | unreachable: it needs a malformed font, xpra only renders text with the fonts installed on the system, it never loads fonts from the peer and `librsvg` does not load `@font-face` web fonts (the stable builds ship cairo 1.18.6) |
| CVE-2026-1584 | gnutls | High | A flaw was found in gnutls. A remote, unauthenticated attacker can exploit this vulnerability by sending a specially crafted ClientHello message with an... |  | off | 6.5.5-r0 |  |  | unreachable: gnutls is never used as a TLS server, it is only loaded as a client library by `python-gssapi` (via `shishi`) and `curl` (via `ngtcp2`) |
| CVE-2026-3832 | gnutls | Low | A flaw was found in gnutls. A remote attacker could exploit this vulnerability by presenting a specially crafted Online Certificate Status Protocol (OCSP)... |  | 🔴 on | 6.5.5-r0 |  |  |  |
| CVE-2026-3833 | gnutls | High | A flaw was found in gnutls. This vulnerability occurs because gnutls performs case-sensitive comparisons of `nameConstraints` labels, specifically for... |  | 🔴 on | 6.5.5-r0 |  |  |  |
| CVE-2026-4775 | libtiff | High | A flaw was found in the libtiff library. A remote attacker could exploit a signed integer overflow vulnerability in the putcontig8bitYCbCr44tile function by... |  | 🔴 on | 6.5.5-r0 |  |  | the TIFF decoder is blocked on MS Windows, but MacOS uses it for clipboard images and ships an affected libtiff |
| CVE-2026-5201 | gdk-pixbuf2 | High | A flaw was found in the gdk-pixbuf library. This heap-based buffer overflow vulnerability occurs in the JPEG image loader due to improper validation of... |  | 🔴 on | 6.5.5-r0 |  |  | [#5092](https://github.com/Xpra-org/xpra/issues/5092) |  |
| CVE-2026-12345 | python | Medium | The cleanup of tempfile.TemporaryDirectory is vulnerable to a race condition. An attacker who can modify the tree during cleanup can replace a directory... | 3.15.0rc3 | off | 6.5.5-r0 |  |  | `tempfile.TemporaryDirectory` is only used by our tests, which are not shipped |
| CVE-2026-12891 | gst-plugins-ugly, gstreamer | Medium | A flaw was found in the GStreamer gst-plugins-bad package. When processing a malformed H.266/VVC video stream with a crafted aspect ratio indicator value,... |  | off | 6.5.5-r0 |  |  | in the gst-plugins-bad codec parsers, matched against other gstreamer packages via the shared CPE: the MS Windows builds do not include the GStreamer video codecs, GStreamer is only used for audio, and `BUILD.py` now deletes the codec parsers library and the GStreamer video elements |
| CVE-2026-12892 | gst-plugins-ugly, gstreamer | Medium | A flaw was found in GStreamer's gst-plugins-bad package. When processing a specially crafted H.264 video file containing malformed MVC or SVC extension... |  | off | 6.5.5-r0 |  |  | in the gst-plugins-bad codec parsers, matched against other gstreamer packages via the shared CPE: the MS Windows builds do not include the GStreamer video codecs, GStreamer is only used for audio, and `BUILD.py` now deletes the codec parsers library and the GStreamer video elements |
| CVE-2026-33845 | gnutls | Critical | A flaw in GnuTLS DTLS handshake parsing allows malformed fragments with zero length and non-zero offset, leading to an integer underflow during reassembly... |  | off | 6.5.5-r0 |  |  | unreachable: nothing we bundle uses DTLS, `gnutls` is only loaded as a TLS client library by `python-gssapi` (via `shishi`) and `curl` (via `ngtcp2`) |
| CVE-2026-42009 | gnutls | High | A flaw was found in gnutls. A remote attacker could exploit an issue in the Datagram Transport Layer Security (DTLS) packet reordering logic. |  | off | 6.5.5-r0 |  |  | unreachable: nothing we bundle uses DTLS, `gnutls` is only loaded as a TLS client library by `python-gssapi` (via `shishi`) and `curl` (via `ngtcp2`) |
| CVE-2026-42010 | gnutls | Critical | A flaw was found in gnutls. Servers configured with RSA-PSK (Rivest–Shamir–Adleman – Pre-Shared Key) wrongfully matched usernames containing a NUL character... |  | off | 6.5.5-r0 |  |  | unreachable: gnutls is never used as a TLS server, it is only loaded as a client library by `python-gssapi` (via `shishi`) and `curl` (via `ngtcp2`) |
| CVE-2026-49264 | python-oauthlib | Medium | OAuthLib is an implementation of the OAuth request-signing logic for Python 3.6+. | 4.0.0 | off | 6.5.5-r0 |  |  | we only use `oauthlib` as an OAuth client, the vulnerability is in the server side endpoints |
| CVE-2026-49265 | python-oauthlib | Medium | OAuthLib is an implementation of the OAuth request-signing logic for Python 3.6+. | 4.0.0 | off | 6.5.5-r0 |  |  | we only use `oauthlib` as an OAuth client, the vulnerability is in the server side endpoints |
| CVE-2026-85091 | zlib | High | zlib versions 1.3.1.2 through 1.3.2 contain a heap buffer overflow vulnerability in the gz_vacate() function when processing non-blocking gzwrite()... |  | off | 6.5.5-r0 |  |  | only in the `gzFile` API, when writing in non-blocking mode: nothing we bundle writes `gzFile` streams, Python's `zlib` and `gzip` modules, libpng, freetype and cairo only use `deflate` / `inflate` |
| CVE-2026-92392 | curl | High | During an upload, curl mishandles HTTP/2 `RST_STREAM` received from the server (with reason `HTTP_1_1_REQUIRED` or `REFUSED_STREAM`) leading to a use after... | 8.23.0 | off | 6.5.5-r0 |  |  | unreachable: the only thing loading `libcurl` is `libproxy`, which xpra uses to find the proxy settings, and it only downloads PAC files - it never uploads anything (the `gstcurl` plugins are not bundled) |
