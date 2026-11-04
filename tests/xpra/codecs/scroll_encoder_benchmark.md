# Scroll input tuning measurements

Feature: [#5118](https://github.com/Xpra-org/xpra/issues/5118).

Measured on 2026-11-04, Intel Core i7-6700K, Fedora 44, Python 3.14.8, libx264 0.165.3222 and libvpx 1.15.0. Both Cython wrappers were rebuilt with GCC and `-O3`.

The selected x264 setting is UMH with `me-range=64`. For VP9, CPUUSED drops by two with a floor of 6; existing CPUUSED values of 6 or lower are preserved. VP8 retains its normal settings. An absent hint restores normal motion settings on the next encoded frame. The server sends `scroll-age-ms` only for `0 <= age < 1000` milliseconds, and never sends it when no scroll event has been recorded.

## Method

Two deterministic generated streams contain text or a browser-like page with text and pictures, with stationary window chrome. Each has 96 frames at a simulated 20 fps: eight initial idle frames, 24 frames scrolling 12 pixels per frame, 16 stationary frames, 16 frames with 64/96/128/192-pixel jumps, then 32 stationary frames. The final stop lasts long enough to exercise expiry. A hint is renewed on each moving frame.

Input generation and RGB-to-YUV420P conversion occur before timing. All frames are decoded. The tables exclude the first eight frames and include encoding plus any live reconfiguration. PSNR measures decoded luma against the encoder input, including stationary chrome. These are generated workloads, rather than recordings of applications.

The final comparison uses 1280x720, quality 65, speeds 50/80/100 and the normal encoder thread defaults (x264: 8 at speed 50 and 4 at 80/100; libvpx: 3). Each pair is repeated three times in deterministically shuffled order. Values below are medians across runs; mean and p95 refer to per-frame encode latency within each run. The benchmarks run sequentially, without simultaneous compilation or test runs.

## Selected settings with normal thread defaults

| Encoder | Stream | Speed | Bytes, normal → scroll | Saved | Mean encode ms, normal → scroll | p95 ms, normal → scroll | Luma PSNR change |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| x264 | text | 50 | 574,832 → 222,119 | 61.4% | 3.74 → 2.96 | 7.40 → 5.12 | +2.41 dB |
| x264 | text | 80 | 747,514 → 289,811 | 61.2% | 1.88 → 1.81 | 3.28 → 2.85 | +0.40 dB |
| x264 | text | 100 | 1,256,508 → 564,914 | 55.0% | 1.40 → 1.37 | 1.92 → 2.04 | +1.38 dB |
| x264 | browser | 50 | 255,166 → 134,498 | 47.3% | 3.69 → 3.87 | 5.03 → 6.40 | +0.25 dB |
| x264 | browser | 80 | 297,133 → 176,278 | 40.7% | 2.03 → 2.01 | 2.90 → 3.16 | +0.13 dB |
| x264 | browser | 100 | 447,390 → 307,813 | 31.2% | 1.57 → 1.62 | 1.99 → 2.31 | +0.09 dB |
| VP9 | text | 50 | 184,649 → 184,649 | 0.0% | 5.76 → 6.04 | 11.07 → 10.69 | +0.00 dB |
| VP9 | text | 80 | 276,119 → 200,195 | 27.5% | 4.67 → 6.33 | 9.05 → 12.89 | -0.06 dB |
| VP9 | text | 100 | 315,551 → 215,202 | 31.8% | 3.57 → 5.65 | 6.57 → 11.83 | +0.14 dB |
| VP9 | browser | 50 | 180,737 → 180,737 | 0.0% | 5.75 → 6.07 | 11.30 → 12.53 | +0.00 dB |
| VP9 | browser | 80 | 220,035 → 179,924 | 18.2% | 5.20 → 5.70 | 9.34 → 10.55 | +0.13 dB |
| VP9 | browser | 100 | 232,683 → 192,793 | 17.1% | 4.53 → 6.47 | 7.03 → 12.46 | +0.07 dB |

## Smooth scrolling and large jumps

Size changes below are the range across both streams and all three speeds. A negative value means fewer bytes. This separates smooth scrolling from the larger jumps.

| Encoder | Phase | Size change range |
| --- | --- | ---: |
| x264 | smooth | -47.2% to -16.0% |
| x264 | jump | -67.5% to -48.2% |
| VP9 | smooth | -29.8% to +2.7% |
| VP9 | jump | -38.7% to +0.0% |

## Exploratory sweeps

- At 800x448, quality 65 and speeds 50/80, x264 UMH ranges 16/32/64 were compared with normal search; 64 gave the strongest compression on both streams.
- At 1280x720, qualities 50/80 and speeds 50/90/100, UMH/64 saved 34–77% of bytes. Mean encoding time ranged from 25% faster to 11% slower. These exploratory runs used `XPRA_X264_THREADS=1` (speed 50 still selected 8 automatic threads).
- VP8 reductions of 1/2/4 in CPUUSED yielded identical luma PSNR and essentially unchanged size (the 720p differences were under 0.01%). It does not consume the hint.
- Unbounded VP9 CPUUSED reductions could cross below 5: for example, CPUUSED=4 at speed 50 produced roughly 2.6–2.9 times the bytes and around three times the encoding time on the text stream in the 720p sweep.
- An intermediate VP9 candidate with a floor of 5 at 720p, qualities 50/80 and speeds 50/80/90/100 saved 15–72% of bytes, adding 0.6–3.8 ms to mean encoding time. Luma PSNR changes ranged from -0.18 to +0.42 dB. These runs used one libvpx thread.
- With normal libvpx thread defaults, that intermediate floor of 5 caused a regression on text at quality 65 and speed 50: mean encoding increased from 6.15 to 11.45 ms and p95 from 10.81 to 32.75 ms, for a 15% size saving. The final floor of 6 avoids this transition.

## Reproduction

Build the modified x264 and libvpx wrappers, then run from the repository root. The benchmark requires Pillow, NumPy, libyuv, the x264/libvpx encoders and OpenH264/libvpx decoders.

```sh
PYTHONPATH=. python3 tests/xpra/codecs/benchmark_scroll_encoders.py \
    --width=1280 --height=720 --quality=65 --speed=50,80,100 \
    --encodings=h264,vp9 --repeat=3 --output=/tmp/xpra-scroll-selected.json
```

To compare alternative bounded candidates, add `--x264-ranges=0,16,32,64` and `--vpx-deltas=0,1,2`. `--threads=1` controls libvpx threads; `XPRA_X264_THREADS` controls the x264 wrapper. The JSON includes the active and restored motion settings, thread counts, codec versions and every repetition.

The runtime tuning can be adjusted with `XPRA_X264_SCROLL_ME_RANGE` (default 64, 0 disables) and `XPRA_VPX_SCROLL_CPUUSED_DELTA` (default 2, 0 disables).
