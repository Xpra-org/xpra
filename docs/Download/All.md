---
title: All Xpra downloads
---
{%- assign dl = site.data.downloads %}

[← all platforms](README.md)

# All downloads

Each file has a `.gpg` signature next to it, see [signatures](#signatures).
Older versions can be found by browsing the [LTS](https://xpra.org/lts/), [stable](https://xpra.org/stable/) and [beta](https://xpra.org/beta/) directories.

{%- assign platforms = "windows,macos" | split: "," %}
{% for platform in platforms %}
{%- assign p = dl[platform] %}
{%- if platform == "windows" %}
## MS Windows
{%- else %}
## macOS
{%- endif %}

<table>
<thead><tr><th>Channel</th><th>Arch</th><th>Build</th>{% for f in p.formats %}<th>{{ f.name }}</th>{% endfor %}{% if p.sbom %}<th>SBOM</th>{% endif %}</tr></thead>
<tbody>
{%- for ch in dl.channels %}
{%- for arch in p.arches %}
{%- for build in dl.builds %}
{%- assign dir = dl.base | append: "/" | append: ch.id | append: "/" | append: p.dir | append: "/" | append: arch.id | append: "/" %}
{%- capture combo %}{{ ch.id }}/{{ arch.id }}/{{ build.id }}{% endcapture %}
<tr><td>{{ ch.name }}</td><td><code>{{ arch.name }}</code></td><td>{{ build.name }}</td>
{%- for f in p.formats %}{% assign file = f[build.id] %}
<td><a href="{{ dir }}{{ file }}">{{ file }}</a> (<a href="{{ dir }}{{ file }}.gpg">sig</a>)</td>
{%- endfor %}
{%- if p.sbom %}<td>{% unless p.no_sbom contains combo %}<a href="{{ dir }}{{ p.sbom[build.id] }}">json</a>{% endunless %}</td>{% endif %}</tr>
{%- endfor %}
{%- endfor %}
{%- endfor %}
</tbody>
</table>
{% endfor %}

## Linux

See the [Linux page](Linux.md) for the installation steps.

### RPM repository files

Save the file in `/etc/yum.repos.d/`.

<table>
<thead><tr><th>Distribution</th>{% for ch in dl.channels %}<th>{{ ch.name }}</th>{% endfor %}<th>Notes</th></tr></thead>
<tbody>
{%- for d in dl.linux.rpm %}
<tr><td><a href="{{ d.url }}">{{ d.name }}</a></td>
{%- for ch in dl.channels %}
<td>{% if d.channels contains ch.id %}<a href="{{ dl.repos }}/{{ d.dir }}/{{ ch.repo }}.repo">{{ ch.repo }}.repo</a>{% else %}not available{% endif %}</td>
{%- endfor %}
<td>{% if d.notes %}{{ d.notes | markdownify | remove: "<p>" | remove: "</p>" | strip }}{% endif %}</td></tr>
{%- endfor %}
</tbody>
</table>

### DEB repository files

Save the file in `/etc/apt/sources.list.d/` and the [signing key](https://xpra.org/xpra.asc) as `/usr/share/keyrings/xpra.asc`.

<table>
<thead><tr><th>Distribution</th>{% for ch in dl.channels %}<th>{{ ch.name }}</th>{% endfor %}</tr></thead>
<tbody>
{%- for d in dl.linux.deb %}
<tr><td><a href="{{ d.url }}">{{ d.name }}</a></td>
{%- for ch in dl.channels %}
<td>{% if d.channels contains ch.id %}<a href="{{ dl.repos }}/{{ d.id }}/{{ ch.repo }}.sources">{{ ch.repo }}.sources</a>{% else %}not available{% endif %}</td>
{%- endfor %}
</tr>
{%- endfor %}
</tbody>
</table>

## Source

[PyPI](https://pypi.org/project/xpra/#history), [xpra.org](https://xpra.org/src/), [GitHub releases](https://github.com/Xpra-org/xpra/releases).

## Signatures

Signing key: [xpra.asc]({{ dl.signing.key }}), key ID `{{ dl.signing.id }}`, fingerprint `{{ dl.signing.fingerprint }}`.
