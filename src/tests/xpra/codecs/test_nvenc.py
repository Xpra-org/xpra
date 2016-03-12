#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import random
import threading
from tests.xpra.codecs.test_encoder import test_encoder, gen_src_images, do_test_encoder, test_encoder_dimensions, test_performance
from xpra.codecs.cuda_common.cuda_context import init_all_devices, get_device_info

from xpra.log import Logger
log = Logger("encoder", "test", "nvenc")

#TEST_DIMENSIONS = ((32, 32), (1920, 1080), (512, 512))
#TEST_DIMENSIONS = ((4096, 2560), (3960, 2060), (1920, 1080), (512, 512), (32, 32))
TEST_DIMENSIONS = ((1920, 1080), (512, 512), (32, 32))


encoder_module = None
def set_encoder_module(module):
    global encoder_module
    encoder_module = module


def test_encode_one():
    log("test_encode_one()")
    test_encoder(encoder_module)

def test_context_leak():
    def do_test_context_leak():
        N = 50
        info = threading.current_thread()
        for i in range(N):
            log.info("%s of %s (%s)", i, N, info)
            test_encoder(encoder_module)
    #not threaded:
    do_test_context_leak()
    #threads:
    thread1 = threading.Thread(target=do_test_context_leak)
    thread2 = threading.Thread(target=do_test_context_leak)
    thread1.start()
    thread2.start()
    thread1.join()
    thread2.join()

def test_memleak():
    log.info("test_memleak()")
    from pycuda import driver
    #use the first device for this test
    start_free_memory = None
    for i in range(100):
        d = driver.Device(0)
        context = d.make_context(flags=driver.ctx_flags.SCHED_AUTO | driver.ctx_flags.MAP_HOST)
        if start_free_memory is None:
            start_free_memory, _ = driver.mem_get_info()
        free_memory, total_memory = driver.mem_get_info()
        log.info("%s%% free_memory: %s MB, total_memory: %s MB", str(i).rjust(3), free_memory/1024/1024, total_memory/1024/1024)
        context.pop()
        context.detach()
        w = random.randint(16, 128)*8
        h = random.randint(16, 128)*8
        n = random.randint(2, 10)
        test_encoder(encoder_module, options={}, dimensions=[(w, h)], n_images=n)

    d = driver.Device(0)
    context = d.make_context(flags=driver.ctx_flags.SCHED_AUTO | driver.ctx_flags.MAP_HOST)
    end_free_memory, _ = driver.mem_get_info()
    context.pop()
    context.detach()
    log.info("memory lost: %s MB", (start_free_memory-end_free_memory)/1024/1024)


def test_perf():
    test_performance(encoder_module, options={"video_separateplane" : True})

def test_dimensions():
    test_encoder_dimensions(encoder_module)

def test_encode_all_GPUs():
    cuda_devices = encoder_module.get_cuda_devices()
    log("")
    log.info("test_parallel_encode() will test one encoder on each of %s sequentially" % cuda_devices)
    TEST_DIMENSIONS = [(32, 32)]
    for device_id, info in cuda_devices.items():
        options = {"cuda_device" : device_id}
        log("")
        log("**********************************")
        log("**********************************")
        log.info("testing on  %s : %s" % (device_id, info))
        test_encoder(encoder_module, options, TEST_DIMENSIONS)
    log("")

def test_context_limits():
    log.info("test_context_limits()")
    #figure out how many contexts we can have on each card:
    cuda_devices = init_all_devices()
    ec = getattr(encoder_module, "Encoder")
    MAX_ENCODER_CONTEXTS_PER_DEVICE = 64
    log("")
    for encoding in encoder_module.get_encodings():
        log.info("test_context_limits() with %s", encoding)
        for w,h in TEST_DIMENSIONS:
            log("test_context_limits() %s @ %sx%s" % (encoding, w, h))
            src_format = encoder_module.get_input_colorspaces(encoding)[0]
            dst_formats = encoder_module.get_output_colorspaces(encoding, src_format)
            for device_id in cuda_devices:
                device_info = get_device_info(device_id)
                options = {"cuda_device" : device_id}
                encoders = []
                for i in range(MAX_ENCODER_CONTEXTS_PER_DEVICE):
                    e = ec()
                    encoders.append(e)
                    try:
                        e.init_context(w, h, src_format, dst_formats, encoding, 20, 0, None, options)
                    except Exception as e:
                        log.warn("failed to create context %s on %s: %s", i, device_info, e)
                        break
                log.info("device %s managed %s contexts at %sx%s", device_info, len(encoders)-1, w, h)
                for encoder in encoders:
                    try:
                        encoder.clean()
                    except Exception as e:
                        log("encoder cleanup error: %s" % e)
    log("")

def test_reconfigure():
    def reconfigure_cb(encoder):
        frame_no = encoder.get_info().get("frames", 0)
        newq = min(100, max(0, (frame_no * 30) % 110))
        log.info("reconfigure frame %i: set new quality: %s", frame_no, newq)
        encoder.set_encoding_quality(newq)
    test_encoder(encoder_module, n_images=5, after_encode_cb=reconfigure_cb)


def test_parallel_encode():
    cuda_devices = init_all_devices()
    ec = getattr(encoder_module, "Encoder")
    encoding = encoder_module.get_encodings()[0]
    log("")
    log.info("test_parallel_encode() will test one %s encoder using %s encoding on each of %s in parallel", ec, encoding, cuda_devices)
    w, h = 1280, 720
    IMAGE_COUNT = 40
    ENCODER_CONTEXTS_PER_DEVICE = 10
    src_format = encoder_module.get_input_colorspaces()[0]
    dst_formats = encoder_module.get_output_colorspaces(encoding, src_format)
    log("generating %s images..." % IMAGE_COUNT)
    images = []
    for _ in range(IMAGE_COUNT):
        images += gen_src_images(src_format, w, h, 1)
    log("%s images generated", IMAGE_COUNT)
    encoders = []
    for device_id in cuda_devices:
        device_info = get_device_info(device_id)
        options = {"cuda_device" : device_id}
        for i in range(ENCODER_CONTEXTS_PER_DEVICE):
            e = ec()
            e.init_context(w, h, src_format, dst_formats, encoding, 0, 100, None, options)
            log("encoder %s for device %s initialized", i, device_id)
            info = "%s / encoder %s" % (device_info, i)
            encoders.append((info, e, images))
    log("%s encoders initialized: %s", len(encoders), [e[1] for e in encoders])
    threads = []
    i = 0
    for info, encoder, images in encoders:
        name = "Context %s : %s" % (i, info)
        thread = threading.Thread(target=encoding_thread, name=name, args=(encoder, src_format, w, h, images, name))
        threads.append(thread)
        i += 1
    log("%s threads created: %s", len(threads), threads)
    log("starting all threads")
    log("")
    for thread in threads:
        thread.start()
    log("%s threads started - waiting for completion", len(threads))
    for thread in threads:
        thread.join()
    log("all threads ended")
    for _, encoder, _ in encoders:
        encoder.clean()
    log("")


def encoding_thread(encoder, src_format, w, h, images, info):
    #log("encoding_thread(%s, %s, %s, %s, %s, %s)" % (encoder, src_format, w, h, images, info))
    log("%s started" % info)
    do_test_encoder(encoder, src_format, w, h, images, name=info, log=log, pause=0.005)
