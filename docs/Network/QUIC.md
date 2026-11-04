# QUIC Transport

See also [network](README.md)

***

<div class="docs-section-heading" markdown="1">

## Overview

</div>

QUIC is a new low-latency encrypted transport protocol, built on top of UDP.

<div class="docs-section-heading" markdown="1">

## Packaging

</div>
The [xpra.org RPM repositories](https://xpra-org.github.io/xpra/Download/Linux.html) include the dependencies required
for running QUIC servers and clients for most distributions, namely `aioquic` and its dependencies.

---

Some distributions (ie: [RHEL 8 / 9](https://github.com/Xpra-org/xpra/issues/4670)) may lack some of the dependencies,
in which case you may need to install them using pip:
```shell
pip3.XX install certifi pyOpenSSL cryptography
```
(be aware that these packages will not receive security updates from your package manager)

<div class="docs-section-heading" markdown="1">

## SSL Options

</div>
SSL encryption is built into the QUIC protocol, so you need to provide the same
configuration options as [SSL](SSL.md).

<div class="docs-section-heading" markdown="1">

## Datagrams

</div>
QUIC can also carry unreliable datagrams, which are never retransmitted:
a lost datagram does not delay the packets that follow it.
Xpra uses them for packets that are self-contained and tolerate loss, by default only `audio-data`,
which works best with the loss-tolerant `opus+rtp` audio codec.
* each side advertises the packet types it accepts as datagrams, only for connections that can receive them (not WebTransport)
* datagrams are only accepted once the peer's `hello` has been processed
* each datagram must contain a complete packet, larger packets are sent on the regular stream instead
* invalid datagrams are dropped, they do not close the connection
* the start and end of audio streams are always sent on the regular stream (see `audio-stream` packets)
* xpra's own [encryption](Encryption.md) cannot be used with QUIC, which is already encrypted

Video frames can also be sent as datagrams, using `window-draw-fragment` packets (experimental, not enabled by default):
* the `h264` encoders (`x264` and `openh264`) limit the size of their slices so that each one fits in a datagram
* the frames are split into fragments on the slice boundaries, large slices are split into a group of fragments
* keyframes and frames that would need too many fragments are sent whole, on the regular stream
* the client re-assembles the fragments, it waits up to `XPRA_DRAW_FRAGMENT_TIMEOUT` for the missing ones,
then decodes the slices it did receive, or skips the frame if there are none
* the decoder conceals the missing slices (`openh264` decoder only, `XPRA_OPENH264_ERROR_CONCEALMENT`)
* the client tells the server which frames were damaged or lost (`window-ack` packets),
so that the encoder stops referencing them: `x264` invalidates the damaged reference frames, `openh264` sends a keyframe

Environment variables:
* `XPRA_QUIC_DATAGRAM_PACKET_TYPES`: the packet types to send as datagrams, if the peer accepts them (default: `audio-data`),
add `window-draw-fragment` to send video frames as datagrams
* `XPRA_DATAGRAM_ACCEPT_PACKET_TYPES`: the packet types we accept as datagrams (default: `audio-data,window-draw-fragment`)
* `XPRA_QUIC_DATAGRAM_DROP_PCT`: discard this percentage of the outgoing datagrams, to test loss tolerance (default: `0`)
* `XPRA_VIDEO_DATAGRAM_SIZE`: the maximum size of the video slices and fragments,
`-1` to use the largest that fits in a datagram (default), `0` to disable video datagrams
* `XPRA_DRAW_FRAGMENT_OVERHEAD`: the space reserved for the `window-draw-fragment` packet headers (default: `192` bytes)
* `XPRA_MAX_DRAW_FRAGMENTS`: frames that need more fragments than this are sent on the stream (default: `64`)
* `XPRA_DRAW_FRAGMENT_TIMEOUT`: how long the client waits for the missing fragments of a frame (default: `50` ms)

<div class="docs-section-heading" markdown="1">

## Notes

</div>
* QUIC is UDP based, you need to open the UDP port of your choosing on your firewall.
* [some tuning](https://github.com/Xpra-org/xpra/issues/3376#issuecomment-1311271256) may be needed
* xpra version 5.0 or later is required
* the client supports both plain quic URIs (ie: `xpra attach quic://HOST:port/`) and WebTransport connections (ie: `xpra attach wt://HOST:port/`)
