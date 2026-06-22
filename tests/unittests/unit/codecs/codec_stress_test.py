#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Stress/abuse harness for video encoders and decoders.
# ABOUTME: Each codec x scenario runs in a forked child so a hard crash
# ABOUTME: (SIGSEGV/SIGABRT) or a hang is reported instead of killing the run.
#
# This hunts for the bug class behind #4886 (vpl): error and teardown paths
# that are rarely exercised by the happy-path selftests - mis-classified status
# codes, frees that race an internal worker thread, unchecked sizes, decoding of
# malformed bitstreams, and out-of-order lifecycle calls. The signal we care
# about is a *crash or hang*: a clean Python exception on bad input is correct
# behaviour and is reported as a pass.
#
# Standalone:
#   PYTHONPATH=. python3 unit/codecs/codec_stress_test.py            # all codecs
#   PYTHONPATH=. python3 unit/codecs/codec_stress_test.py enc_vpl dec_jpeg
#   XPRA_CODEC_STRESS_FULL=1 PYTHONPATH=. python3 unit/codecs/codec_stress_test.py
#
# As a unit test (quick subset, all available codecs):
#   python3 setup.py unittests unit.codecs.codec_stress_test

import os
import sys
import time
import enum
import signal
import random
import logging
import tempfile
import traceback
import unittest

from xpra.util.objects import typedict
from xpra.codecs import loader
from xpra.codecs.checks import make_test_image, TEST_COMPRESSED_DATA

# full mode does more iterations, larger sizes and every scenario:
FULL = os.environ.get("XPRA_CODEC_STRESS_FULL", "0") == "1"
# per-(codec, scenario) wall-clock budget before we treat it as a hang:
TIMEOUT = int(os.environ.get("XPRA_CODEC_STRESS_TIMEOUT", "120"))
SEED = 0x5EED


class SkipScenario(Exception):
    """raised by a scenario when it does not apply to this codec"""


# ── spec / size helpers ────────────────────────────────────────────────

def _g(spec, attr, default):
    v = getattr(spec, attr, default)
    return default if v is None else v


def _mask_align(mask: int) -> int:
    # a mask like 0xFFFE keeps even values: the alignment is 2
    return (((~mask) + 1) & 0xFFFF) or 1


def _valid_dim(v: int, mask: int, lo: int, hi: int) -> int:
    a = _mask_align(mask)
    lo_a = ((lo + a - 1) // a) * a
    hi_a = max(lo_a, (hi // a) * a)
    v = (max(lo, min(hi, v)) // a) * a
    return max(lo_a, min(hi_a, v))


def _limits(spec):
    cap = 8192 if FULL else 2048
    return {
        "min_w": _g(spec, "min_w", 16), "min_h": _g(spec, "min_h", 16),
        "max_w": min(_g(spec, "max_w", 8192), cap),
        "max_h": min(_g(spec, "max_h", 8192), cap),
        "wmask": _g(spec, "width_mask", 0xFFFF), "hmask": _g(spec, "height_mask", 0xFFFF),
    }


def _base_size(spec):
    L = _limits(spec)
    w = _valid_dim(256, L["wmask"], L["min_w"], L["max_w"])
    h = _valid_dim(192, L["hmask"], L["min_h"], L["max_h"])
    return w, h


def _wrong_format(cs: str) -> str:
    for cand in ("YUV420P", "BGRX", "NV12", "YUV444P", "RGB"):
        if cand != cs:
            return cand
    return "BGRX"


# ── encoder plumbing ───────────────────────────────────────────────────

def _enc_spec(mod):
    specs = mod.get_specs() if hasattr(mod, "get_specs") else ()
    for spec in specs or ():
        if hasattr(_g(spec, "codec_class", None), "init_context"):
            return spec
    raise SkipScenario("not a stateful (init_context) encoder")


def _init_encoder(e, spec, w, h, **opts):
    coptions = typedict({
        "dst-formats": list(_g(spec, "output_colorspaces", ())),
        "quality": 50,
        "speed": 50,
    })
    coptions.update(opts)
    e.init_context(spec.encoding, w, h, spec.input_colorspace, coptions)


def _new_encoder(mod, spec, w, h, **opts):
    e = spec.codec_class()
    _init_encoder(e, spec, w, h, **opts)
    return e


def _encode(e, cs: str, w: int, h: int, **opts):
    img = make_test_image(cs, w, h)
    try:
        return e.compress_image(img, typedict(opts))
    finally:
        _free(img)


def _free(img):
    try:
        img.free()
    except Exception:
        pass


def _safe_clean(obj):
    try:
        obj.clean()
    except Exception:
        pass


# ── encoder scenarios ──────────────────────────────────────────────────

def enc_resize_churn(mod):
    """rapid create -> encode -> destroy across many valid sizes (#4886 trigger)"""
    spec = _enc_spec(mod)
    cs = spec.input_colorspace
    L = _limits(spec)
    rnd = random.Random(SEED)
    for _ in range(40 if FULL else 12):
        w = _valid_dim(rnd.randint(L["min_w"], L["max_w"]), L["wmask"], L["min_w"], min(L["max_w"], 1024))
        h = _valid_dim(rnd.randint(L["min_h"], L["max_h"]), L["hmask"], L["min_h"], min(L["max_h"], 768))
        e = _new_encoder(mod, spec, w, h)
        try:
            _encode(e, cs, w, h)
            _encode(e, cs, w, h)
        finally:
            e.clean()


def enc_error_teardown(mod):
    """encode an image the codec must reject, then tear down at once (#4886)"""
    spec = _enc_spec(mod)
    cs = spec.input_colorspace
    w, h = _base_size(spec)
    wrong = _wrong_format(cs)
    ww, hh = max(2, w & ~1), max(2, h & ~1)
    for _ in range(40 if FULL else 15):
        e = _new_encoder(mod, spec, w, h)
        try:
            try:
                e.compress_image(make_test_image(wrong, ww, hh), typedict())
            except Exception:
                pass        # rejecting the wrong format is correct
        finally:
            e.clean()       # the teardown that raced the worker in vpl


def enc_boundary_sizes(mod):
    """init at min, just-below-min, off-alignment and max sizes"""
    spec = _enc_spec(mod)
    cs = spec.input_colorspace
    L = _limits(spec)
    aw, ah = _mask_align(L["wmask"]), _mask_align(L["hmask"])
    candidates = (
        (L["min_w"], L["min_h"]),
        (L["min_w"] - aw, L["min_h"]),
        (L["min_w"], L["min_h"] - ah),
        (L["min_w"] + 1, L["min_h"] + 1),
        (_valid_dim(L["max_w"], L["wmask"], L["min_w"], L["max_w"]),
         _valid_dim(L["max_h"], L["hmask"], L["min_h"], L["max_h"])),
    )
    for w, h in candidates:
        if w < 2 or h < 2:
            continue
        try:
            e = _new_encoder(mod, spec, w, h)
        except Exception:
            continue        # refusing an out-of-range size is correct
        try:
            ew, eh = max(2, w & ~1), max(2, h & ~1)
            try:
                _encode(e, cs, ew, eh)
            except Exception:
                pass
        finally:
            e.clean()


def enc_param_churn(mod):
    """drive quality/speed to extremes and flip them per frame"""
    spec = _enc_spec(mod)
    cs = spec.input_colorspace
    w, h = _base_size(spec)
    e = _new_encoder(mod, spec, w, h)
    try:
        for q in (0, 100, 50, -1, 101, 1000, 0, 100, 1, 99):
            try:
                _encode(e, cs, w, h, quality=q)
            except Exception:
                pass
        for s in (0, 100, -1, 101):
            try:
                _encode(e, cs, w, h, speed=s)
            except Exception:
                pass
        for setter in ("set_encoding_quality", "set_encoding_speed"):
            fn = getattr(e, setter, None)
            if not fn:
                continue
            for v in (0, 100, 50, -1, 101):
                try:
                    fn(v)
                    _encode(e, cs, w, h)
                except Exception:
                    pass
    finally:
        e.clean()


def enc_state_abuse(mod):
    """call the lifecycle methods out of order"""
    spec = _enc_spec(mod)
    cs = spec.input_colorspace
    w, h = _base_size(spec)

    # double init on one instance
    e = spec.codec_class()
    try:
        _init_encoder(e, spec, w, h)
        try:
            _init_encoder(e, spec, w, h)
        except Exception:
            pass
    finally:
        _safe_clean(e)

    # encode after clean
    e = _new_encoder(mod, spec, w, h)
    e.clean()
    try:
        e.compress_image(make_test_image(cs, w, h), typedict())
    except Exception:
        pass

    # double clean
    e = _new_encoder(mod, spec, w, h)
    e.clean()
    e.clean()

    # flush without encode, and flush after clean
    e = _new_encoder(mod, spec, w, h)
    fl = getattr(e, "flush", None)
    if fl:
        try:
            fl(0)
        except Exception:
            pass
    e.clean()
    if fl:
        try:
            fl(0)
        except Exception:
            pass


def enc_concurrency(mod):
    """several threads each churning their own encoder instance"""
    import threading
    spec = _enc_spec(mod)
    cs = spec.input_colorspace
    w, h = _base_size(spec)

    def worker():
        for _ in range(8):
            e = _new_encoder(mod, spec, w, h)
            try:
                _encode(e, cs, w, h)
            finally:
                _safe_clean(e)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ── decoder plumbing ───────────────────────────────────────────────────

def _dec_spec(mod):
    specs = mod.get_specs() if hasattr(mod, "get_specs") else ()
    if not specs:
        raise SkipScenario("no decoder specs")
    return specs[0]


def _dec_size(mod, spec):
    mw, mh = 16, 16
    try:
        mw, mh = mod.get_min_size(spec.encoding)
    except Exception:
        pass
    return max(mw, 256), max(mh, 128)


def _new_decoder(mod, spec, w, h):
    d = mod.Decoder()
    d.init_context(spec.encoding, w, h, spec.input_colorspace, typedict())
    return d


def _junk(rnd):
    return (
        b"",
        b"\x00",
        b"junk",
        b"\xff" * 1024,
        bytes(rnd.randrange(256) for _ in range(64)),
        bytes(rnd.randrange(256) for _ in range(4096)),
        b"\x00\x00\x00\x01" + bytes(rnd.randrange(256) for _ in range(512)),   # fake NAL
    )


def _try_decode(d, data):
    try:
        img = d.decompress_image(data, typedict())
        if img is not None:
            _free(img)
    except Exception:
        pass        # rejecting junk is correct


def _ref_frames(spec):
    cs_map = TEST_COMPRESSED_DATA.get(spec.encoding, {})
    for cs in (spec.input_colorspace, *cs_map.keys()):
        for (w, h), frames in cs_map.get(cs, {}).items():
            if frames:
                return cs, w, h, [f[0] for f in frames]
    return None


# ── decoder scenarios ──────────────────────────────────────────────────

def dec_garbage(mod):
    """feed empty / random / fake-header payloads to a fresh context"""
    spec = _dec_spec(mod)
    w, h = _dec_size(mod, spec)
    rnd = random.Random(SEED)
    d = _new_decoder(mod, spec, w, h)
    try:
        for data in _junk(rnd):
            _try_decode(d, data)
    finally:
        d.clean()


def dec_truncated(mod):
    """feed truncated and bit-flipped copies of a known-good frame"""
    spec = _dec_spec(mod)
    ref = _ref_frames(spec)
    if not ref:
        raise SkipScenario("no reference frames for this encoding")
    cs, w, h = ref[0], ref[1], ref[2]
    frames = ref[3]
    rnd = random.Random(SEED)
    d = mod.Decoder()
    d.init_context(spec.encoding, w, h, cs, typedict())
    try:
        for fr in frames:
            if not fr:
                continue
            for cut in (1, len(fr) // 2, len(fr) - 1):
                if cut >= 1:
                    _try_decode(d, fr[:cut])
            for _ in range(4):
                b = bytearray(fr)
                b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
                _try_decode(d, bytes(b))
    finally:
        d.clean()


def dec_error_teardown(mod):
    """decode junk (rejected), then tear down at once - decoder side of #4886"""
    spec = _dec_spec(mod)
    w, h = _dec_size(mod, spec)
    for _ in range(40 if FULL else 15):
        d = _new_decoder(mod, spec, w, h)
        try:
            _try_decode(d, b"\x00\x00\x00\x01not-a-real-bitstream")
        finally:
            d.clean()


def dec_state_abuse(mod):
    """decode after clean, double clean, clean without decode"""
    spec = _dec_spec(mod)
    w, h = _dec_size(mod, spec)

    d = _new_decoder(mod, spec, w, h)
    d.clean()
    _try_decode(d, b"junk")

    d = _new_decoder(mod, spec, w, h)
    d.clean()
    d.clean()

    d = _new_decoder(mod, spec, w, h)
    d.clean()


def dec_concurrency(mod):
    """several threads each churning their own decoder instance"""
    import threading
    spec = _dec_spec(mod)
    w, h = _dec_size(mod, spec)

    def worker():
        for _ in range(8):
            d = _new_decoder(mod, spec, w, h)
            try:
                _try_decode(d, b"junkjunkjunkjunk")
            finally:
                _safe_clean(d)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


ENCODER_SCENARIOS = {
    "resize_churn": enc_resize_churn,
    "error_teardown": enc_error_teardown,
    "boundary_sizes": enc_boundary_sizes,
    "param_churn": enc_param_churn,
    "state_abuse": enc_state_abuse,
    "concurrency": enc_concurrency,
}
DECODER_SCENARIOS = {
    "garbage": dec_garbage,
    "truncated": dec_truncated,
    "error_teardown": dec_error_teardown,
    "state_abuse": dec_state_abuse,
    "concurrency": dec_concurrency,
}
# fast subset for the default (non-FULL) unit test run:
QUICK = ("error_teardown", "state_abuse", "garbage")


# ── fork isolation ─────────────────────────────────────────────────────

class Result(enum.Enum):
    OK = "ok"
    SKIP = "skip"
    RAISED = "raised"      # clean Python exception escaped (informational)
    CRASH = "CRASHED"      # killed by a signal - the bug we hunt
    HANG = "HANG"          # exceeded the timeout - likely a deadlock


def _load_module(name: str):
    loader.RUN_SELF_TESTS = False
    loader.load_codec(name)
    mod = loader.get_codec(name)
    if mod is None:
        raise SkipScenario(f"{name} not available")
    init = getattr(mod, "init_module", None)
    if init:
        init({})
    return mod


def _signame(sig: int) -> str:
    try:
        return signal.Signals(sig).name
    except ValueError:
        return f"SIG{sig}"


def _read_capture(cap) -> str:
    try:
        cap.seek(0)
        data = cap.read()
    except Exception:
        return ""
    finally:
        try:
            cap.close()
        except Exception:
            pass
    return data.decode("utf-8", "replace")[-2500:] if data else ""


def run_isolated(name: str, scenario_fn, timeout: int):
    """run one scenario in a forked child; classify by how it died"""
    cap = tempfile.TemporaryFile()
    pid = os.fork()
    if pid == 0:                                    # ---- child ----
        os.dup2(cap.fileno(), 1)
        os.dup2(cap.fileno(), 2)
        logging.disable(logging.CRITICAL)           # codecs are noisy on bad input
        try:
            scenario_fn(_load_module(name))
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
        except SkipScenario as e:
            sys.stderr.write(f"skip: {e}\n")
            sys.stderr.flush()
            os._exit(4)
        except BaseException:
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(3)

    deadline = time.monotonic() + timeout           # ---- parent ----
    while True:
        wpid, status = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            break
        if time.monotonic() > deadline:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            os.waitpid(pid, 0)
            return Result.HANG, _read_capture(cap)
        time.sleep(0.05)

    out = _read_capture(cap)
    if os.WIFSIGNALED(status):
        sig = os.WTERMSIG(status)
        return Result.CRASH, f"signal {sig} ({_signame(sig)})\n{out}"
    code = os.WEXITSTATUS(status)
    return {0: Result.OK, 4: Result.SKIP}.get(code, Result.RAISED), out


# ── battery driver ─────────────────────────────────────────────────────

def _env_codecs():
    v = os.environ.get("XPRA_TEST_CODECS")
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def run_battery(codecs=None, scenarios=None):
    # the stateful init_context/compress/clean API (and the #4886 bug class)
    # lives in the *video* codec lists; picture codecs use a different API.
    if codecs:
        encoders = [n for n in codecs if n.startswith("enc") or n in loader.ENCODER_VIDEO_CODECS]
        decoders = [n for n in codecs if n.startswith("dec") or n in loader.DECODER_VIDEO_CODECS]
    else:
        encoders = list(loader.ENCODER_VIDEO_CODECS)
        decoders = list(loader.DECODER_VIDEO_CODECS)

    results = {}
    for kind, names, table in (
        ("encoder", encoders, ENCODER_SCENARIOS),
        ("decoder", decoders, DECODER_SCENARIOS),
    ):
        if names:
            print(f"\n== {kind}s ==")
        for name in names:
            cells = []
            for sname, fn in table.items():
                if scenarios and sname not in scenarios:
                    continue
                res, detail = run_isolated(name, fn, TIMEOUT)
                results[(kind, name, sname)] = (res, detail)
                tag = res.value if res in (Result.OK, Result.SKIP, Result.RAISED) else f"** {res.value} **"
                cells.append(f"{sname}={tag}")
                if res in (Result.CRASH, Result.HANG):
                    print(f"  {name:16} {sname}: {res.value}")
                    for line in detail.strip().splitlines()[-6:]:
                        print(f"      {line}")
            print(f"  {name:16} " + "  ".join(cells))
    return results


def _summary(results) -> int:
    bad = {k: v for k, v in results.items() if v[0] in (Result.CRASH, Result.HANG)}
    print("\n" + "=" * 60)
    if not bad:
        ran = sum(1 for v in results.values() if v[0] != Result.SKIP)
        print(f"no crashes or hangs across {ran} codec/scenario runs")
        return 0
    print(f"FOUND {len(bad)} crash/hang:")
    for (kind, name, sname), (res, _) in bad.items():
        print(f"  {res.value:8} {kind} {name} / {sname}")
    return 1


# ── unittest wrapper ───────────────────────────────────────────────────

class CodecStressTest(unittest.TestCase):

    def test_stress(self):
        scenarios = None if FULL else QUICK
        results = run_battery(codecs=_env_codecs(), scenarios=scenarios)
        bad = {k: v for k, v in results.items() if v[0] in (Result.CRASH, Result.HANG)}
        if bad:
            report = "\n".join(
                f"{r.value} in {kind} {name} / {s}:\n{d}"
                for (kind, name, s), (r, d) in bad.items()
            )
            self.fail(f"codec stress found {len(bad)} crash/hang:\n{report}")


def main(argv) -> int:
    codecs = [a for a in argv[1:] if not a.startswith("-")] or _env_codecs()
    results = run_battery(codecs=codecs)
    return _summary(results)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
