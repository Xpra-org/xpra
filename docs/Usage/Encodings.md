# Encodings

Xpra supports a wide variety of picture and video encodings for sending window
contents to the client quickly and efficiently. For background information on
picture encodings, see [images.guide](https://images.guide/).

Choosing an encoding is best left to the Xpra engine. It considers the window’s
characteristics, network performance, user preferences, client and server
capabilities, and available processing power.

If tuning is needed, use `min-speed` and `min-quality` before overriding the
`encodings` or `encoding` options. The `xpra configure encodings` tool is
designed to help with this; use it first and try other options only later.

<div class="docs-section-heading" markdown="1">

## Available encodings

These encodings control how Xpra selects and compresses screen updates.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card docs-card-wide" markdown="1">

### Pseudo encodings

Pseudo encodings control which actual encodings the engine may select:

- **`auto`** — the default; allows all options
- **`grayscale`** — allows all options without sending colours, which can save
  bandwidth
- **`scroll`** — tries harder to send screen updates using motion vectors; see
  [the `scroll` encoding](../Subsystems/Window.md#the-scroll-encoding) for the
  semantics client implementations must honour

Select one with `--encoding=ENC`.

</section>

<section class="docs-card" markdown="1">

### Local and raw pixels

- **`mmap`** — all bit depths; fastest; only available with local connections
  and selected automatically
- **`rgb`** — all bit depths; very fast; raw RGB pixels, potentially compressed
  with a stream compressor such as `lz4`

</section>

<section class="docs-card" markdown="1">

### Compressed picture encodings

- **`webp`** — 24 / 32 bit; good; fast, with transparency and lossy or lossless
  modes
- **`jpeg`** — 24 bit; fast and easy to support
- **`avif`** — 24 bit; average; limited support
- **`png`** — 24 / 32 bit; slow and easy to support
- **`png/P`** — 8 bit; slow; useful for 8-bit [desktop mode](Desktop.md)
- **`png/L`** — 8 bit; slow; greyscale

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Video encodings

Video streams are often the most efficient way to send large amounts of screen
updates without consuming too much bandwidth. Xpra automatically detects when
switching to a video codec makes sense.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### VP8 and VP9

- **`vp8`** — 24 bit; fast but less efficient
- **`vp9`** — 24 / 30 bit; more efficient but somewhat slower

</section>

<section class="docs-card" markdown="1">

### H.264 and HEVC

- **`h264`** — 24 / 30 bit; licensing issues
- **`hevc`** — 24 / 30 bit; licensing issues and usually slower

</section>

<section class="docs-card" markdown="1">

### AV1

**`av1`** supports 24-bit colour. It is the most efficient video encoding, but
does not provide a lossless mode.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Video encoders

Xpra ships these encoder modules. Availability and supported encodings can vary
with the Xpra version, build options, and hardware capabilities.

- **`vpx`** — `vp8`, `vp9`
- **`x264`** — `h264`; fast
- **[`nvenc`](NVENC.md)** — `h264`, `hevc`, `av1`; fastest, requires hardware

Choose which modules are loaded at runtime with `video-encoders`.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Colorspace conversion

Some video encoders require a colorspace conversion step. These modules can:

- convert pixels received by the server into a format consumed by video
  encoders
- convert decoded pixels into a format that can paint the client window
- scale pixels up or down when needed

Available modules include:

- **`cython`** — `r210`, `BGR48`, `GBRP10`, `YUV444P10`; slow but useful for
  high-bit-depth modes
- **`libyuv`** — `BGRX`, `YUV420P`, `NV12`; fastest

Choose loaded modules at runtime with `csc-modules`.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Video decoders

Xpra ships these decoder modules:

- **`openh264`** — `h264`
- **`vpx`** — `vp8`, `vp9`
- **`aom`** — `av1`

Choose which modules are loaded at runtime with `video-decoders`.

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Diagnostics

Use these commands to see which encodings, codecs, and conversion modules are
available in the current installation.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card" markdown="1">

### List available encodings

```shell
xpra encoding
```

On Windows and macOS, you can also use the `Encodings_info` wrapper.

</section>

<section class="docs-card" markdown="1">

### List video codecs and conversion modules

```shell
xpra video
```

</section>

<section class="docs-card" markdown="1">

### List client encodings

```shell
xpra attach --encoding=help
```

</section>

<section class="docs-card" markdown="1">

### List server encodings

```shell
xpra seamless --encoding=help
```

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Enable encoding debug logs

```shell
xpra seamless -d damage,compress,encoding
```

</section>
</div>

<div class="docs-section-heading" markdown="1">

## Tuning

Tuning is often misused and can make performance worse. Start with the
automatic selection and minimum quality or speed settings before forcing a
specific encoding.

</div>

<div class="docs-grid" markdown="1">
<section class="docs-card docs-card-wide" markdown="1">

### Prevent blurry screen updates

Rather than selecting a lossless picture encoding, which may use too much
bandwidth and cause performance issues:

- make sure applications are detected correctly using the
  [content-type](https://github.com/Xpra-org/xpra/tree/master/fs/etc/xpra/content-type)
  and
  [content-categories](https://github.com/Xpra-org/xpra/tree/master/fs/etc/xpra/content-categories/10_default.conf)
  mappings
- raise `min-quality` and/or lower `min-speed`
- consider lowering the `auto-refresh` delay, while remembering that lossless
  refreshes can be costly

</section>

<section class="docs-card" markdown="1">

### Quality

Values range from 1 (lowest) to 100 (lossless). Rather than tuning `quality`,
use `min-quality`. Lower values save bandwidth and CPU but may make updates
more blurry.

</section>

<section class="docs-card" markdown="1">

### Speed

Values range from 1 (lowest) to 100 (lossless). Rather than tuning `speed`, use
`min-speed`. Lower values use more CPU, reducing bandwidth consumption but
possibly lowering the framerate.

</section>

<section class="docs-card" markdown="1">

### Best performance

Use [NVENC](NVENC.md) or another hardware encoder supported by `libva` when
available. Hardware encoders compress very well and do so extremely quickly.

</section>

<section class="docs-card docs-card-wide" markdown="1">

### Further reading

- [x264 tradeoffs](http://alax.info/blog/1394)
- [FPS versus noise](http://blog.malayter.com/2010/12/presets-versus-quality-in-x264-encoding.html)
- [FPS versus size](http://blogs.motokado.com/yoshi/2011/06/25/comparison-of-x264-presets/)
- [Falsehoods programmers believe about video](https://haasn.xyz/posts/2016-12-25-falsehoods-programmers-believe-about-%5Bvideo-stuff%5D.html)

When comparing performance, use the right metrics. Updates per second (`fps`)
are not always meaningful: many small regions can make a high or low count
misleading.

</section>
</div>
