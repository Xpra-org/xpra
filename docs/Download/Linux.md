---
title: Download Xpra for Linux
---
<script>document.documentElement.classList.add("js")</script>
{%- assign dl = site.data.downloads %}

[← all platforms](README.md)

# Xpra for Linux

Xpra is installed from the xpra.org package repositories, which also provide the dependencies
your distribution is missing.

{% include download-picker.html name="method" label="Installation method" items=dl.linux.methods %}

<div class="dl-select dl-cond" data-method="deb">
<label for="dl-deb"><strong>Distribution</strong></label><br>
<select id="dl-deb" data-key="deb">
{%- for d in dl.linux.deb %}
<option value="{{ d.id }}">{{ d.name }}</option>
{%- endfor %}
</select>
</div>

<div class="dl-select dl-cond" data-method="rpm">
<label for="dl-rpm"><strong>Distribution</strong></label><br>
<select id="dl-rpm" data-key="rpm">
{%- for d in dl.linux.rpm %}
<option value="{{ d.id }}">{{ d.name }}</option>
{%- endfor %}
</select>
</div>

<div class="dl-cond" data-method="quick deb rpm">
{% include download-picker.html name="channel" label="Channel" items=dl.channels %}
</div>

<div class="dl-results">
{%- for ch in dl.channels %}
<section class="dl-result dl-cond" data-method="quick" data-channel="{{ ch.id }}">
<h4>Automatic setup · {{ ch.name }} <code>{{ ch.version }}</code></h4>
<p>For Fedora, RHEL and its clones, Debian, Ubuntu and Linux Mint, this script installs the {{ ch.name }} repository and the <code>xpra</code> package:</p>
<pre><code>curl https://xpra.org/get-xpra.sh | {% if ch.id != "stable" %}REPO={{ ch.repo }} {% endif %}bash</code></pre>
<p>Or, from a source checkout:</p>
<pre><code>git clone https://github.com/Xpra-org/xpra
cd xpra
./setup.py install-{% if ch.id != "stable" %}{{ ch.id }}-{% endif %}repo</code></pre>
<p>Then install <code>xpra</code> using your package manager.</p>
</section>
{%- endfor %}

{%- for d in dl.linux.deb %}
{%- for ch in dl.channels %}
<section class="dl-result dl-cond dl-jsonly" data-method="deb" data-deb="{{ d.id }}" data-channel="{{ ch.id }}">
<h4><a href="{{ d.url }}">{{ d.name }}</a> · {{ ch.name }} <code>{{ ch.version }}</code></h4>
{%- if d.channels contains ch.id %}
<p>Run as a regular user with <code>sudo</code> access:</p>
<pre><code>sudo apt update
sudo apt install ca-certificates wget
sudo wget -O /usr/share/keyrings/xpra.asc {{ dl.signing.key }}
sudo wget -O /etc/apt/sources.list.d/{{ ch.repo }}.sources \
  {{ dl.repos }}/{{ d.id }}/{{ ch.repo }}.sources
sudo apt update
sudo apt install xpra</code></pre>
<p class="dl-extra">Repository file: <a href="{{ dl.repos }}/{{ d.id }}/{{ ch.repo }}.sources">{{ ch.repo }}.sources</a>
{%- if d.notes %} · {{ d.notes }}{% endif %}</p>
{%- else %}
<p>The {{ ch.name }} channel is not available for {{ d.name }}{% if d.notes %}: {{ d.notes }}{% endif %}.</p>
{%- endif %}
</section>
{%- endfor %}
{%- endfor %}

{%- for d in dl.linux.rpm %}
{%- for ch in dl.channels %}
<section class="dl-result dl-cond dl-jsonly" data-method="rpm" data-rpm="{{ d.id }}" data-channel="{{ ch.id }}">
<h4><a href="{{ d.url }}">{{ d.name }}</a> · {{ ch.name }} <code>{{ ch.version }}</code></h4>
{%- if d.channels contains ch.id %}
<p>Run as a regular user with <code>sudo</code> access:</p>
<pre><code>{% for cmd in d.prepare %}{{ cmd | xml_escape }}
{% endfor %}sudo curl -o /etc/yum.repos.d/{{ ch.repo }}.repo \
  {{ dl.repos }}/{{ d.dir }}/{{ ch.repo }}.repo
sudo dnf install xpra</code></pre>
<p class="dl-extra">Repository file: <a href="{{ dl.repos }}/{{ d.dir }}/{{ ch.repo }}.repo">{{ ch.repo }}.repo</a>
· some codecs come from <a href="https://rpmfusion.org/">rpmfusion</a>
{%- if d.notes %} · {{ d.notes | markdownify | remove: "<p>" | remove: "</p>" | strip }}{% endif %}</p>
{%- else %}
<p>The {{ ch.name }} channel is not available for {{ d.name }}.</p>
{%- endif %}
</section>
{%- endfor %}
{%- endfor %}

<section class="dl-result dl-cond" data-method="other">
<h4>Other distributions</h4>
<ul>
<li>unreleased distributions (ie: Fedora Rawhide, Debian Sid) should use the beta repositories</li>
<li>distributions derived from Debian, Ubuntu or RHEL can usually use the repository of the distribution they are based on</li>
<li>many distributions ship their own <code>xpra</code> package, but some of these are <a href="https://github.com/Xpra-org/xpra/wiki/Distribution-Packages">old or broken</a></li>
<li>or <a href="Other.html">install from source</a></li>
</ul>
</section>
</div>

<noscript markdown="1">
**DEB repositories**: install the key with
`sudo wget -O /usr/share/keyrings/xpra.asc https://xpra.org/xpra.asc`
then download the repository file for your distribution into `/etc/apt/sources.list.d/` and run `sudo apt update ; sudo apt install xpra`.

**RPM repositories**: enable [rpmfusion](https://rpmfusion.org/) (and `crb` + `EPEL` on RHEL and its clones),
download the repository file for your distribution into `/etc/yum.repos.d/` and run `sudo dnf install xpra`.

The repository files for each distribution are listed on the [all downloads](All.md#linux) page.
</noscript>

## Sub-packages

Starting with version 6, the xpra packages are split into [sub-packages](../Build/Packaging.md).
As long as you avoid [buggy downstream packages](https://github.com/Xpra-org/xpra/wiki/Distribution-Packages),
installing `xpra` installs the client and server components, as well as most picture codecs and audio support.

## Repository contents

Many distributions do not ship all of the libraries that xpra needs, or only ship versions that are too old
or built without the features required.
These dependencies are rebuilt and shipped from the same repositories, so that installing `xpra` pulls in
everything it needs:

* `Fedora` already provides almost everything, so only a handful of packages are added
* the `RHEL` clones (`AlmaLinux`, `RockyLinux`, `OracleLinux`, `CentOS Stream`) need many more,
  and the version 9 builds also target a newer interpreter (`python3.12`), so every Python module has to be rebuilt for it
* `Debian` and `Ubuntu` need very few extra packages

Because these packages are built specifically for xpra, they may be more recent than the ones from your
distribution and your package manager will usually prefer them.

<details markdown="1">
<summary>Examples of packages provided</summary>

| Package(s) | Used for |
| --- | --- |
| `python3-aioquic`, `python3-pylsqpack` | [QUIC transport](../Network/QUIC.md) |
| `python3-pycuda`, `python3-pynvml` | [NVIDIA hardware accelerated encoders](../Usage/NVENC.md) |
| `python3-pyopengl` | [client OpenGL rendering](../Usage/Client-OpenGL.md) |
| `python3-fido2`, `python3-pyu2f` | [authentication modules](../Usage/Authentication.md) |
| `python3-pillow`, `python3-numpy` | picture [encodings](../Usage/Encodings.md) |
| `python3-cairo`, `pygobject3`, `python3-pyxdg`, `python3-dbus` | GTK client and server |
| `python3-uinput` | virtual input devices |
| `openh264`, `libyuv` | video encoding and colourspace conversion |
| `xorg-x11-drv-dummy` / `xserver-xorg-video-dummy` | the patched [dummy driver](../Usage/Xdummy.md) used by seamless and desktop servers |
| `gstreamer1-plugin-timestamp` | extracting monotonic timestamps from audio buffers |

The exact list of packages built for each RPM target can be found in
[`packaging/rpm/distros`](https://github.com/Xpra-org/xpra/tree/master/packaging/rpm/distros).
</details>

The same repositories also provide other [Xpra-org](https://github.com/Xpra-org) projects:
[`xpra-html5`](https://github.com/Xpra-org/xpra-html5) (usually installed with `xpra`),
[`go-xpra`](https://github.com/Xpra-org/go-xpra) and [`rust-xpra`](https://github.com/Xpra-org/rust-xpra),
see the [client comparison](../Usage/Clients.md).

## Notes

* the DEB repositories may require the `universe` repository to be enabled to get all the features
* for [rather tedious reasons](https://github.com/Xpra-org/xpra/issues/3446), Debian systems may need two almost identical versions of the signing key,
  and if `/usr/share/keyrings/xpra.asc` already exists you may [hit some problems](https://github.com/orgs/Xpra-org/discussions/3960#discussioncomment-6703203)
* you can also build your own [RPM](../Build/RPM.md) or [DEB](../Build/Debian.md) packages

{% include download-banner.html %}

<script src="{{ '/assets/js/download.js' | relative_url }}"></script>
