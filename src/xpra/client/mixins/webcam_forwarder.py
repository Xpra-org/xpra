# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from threading import RLock

from xpra.log import Logger
log = Logger("webcam")

from xpra.scripts.config import FALSE_OPTIONS
from xpra.net import compression
from xpra.os_util import BytesIOClass, monotonic_time, WIN32, BITS
from xpra.util import envint, envbool, csv
from xpra.client.mixins.stub_client_mixin import StubClientMixin


WEBCAM_ALLOW_VIRTUAL = envbool("XPRA_WEBCAM_ALLOW_VIRTUAL", False)
WEBCAM_TARGET_FPS = max(1, min(50, envint("XPRA_WEBCAM_FPS", 20)))


"""
Utility superclass for clients that forward webcams
"""
class WebcamForwarder(StubClientMixin):

    __signals__ = ["webcam-changed"]

    def __init__(self):
        StubClientMixin.__init__(self)
        #webcam:
        self.webcam_option = ""
        self.webcam_forwarding = False
        self.webcam_device = None
        self.webcam_device_no = -1
        self.webcam_last_ack = -1
        self.webcam_ack_check_timer = None
        self.webcam_send_timer = None
        self.webcam_lock = RLock()
        self.server_webcam = False
        self.server_virtual_video_devices = 0
        if not hasattr(self, "send"):
            self.send = self.noop

    def noop(self, *_args):
        pass


    def cleanup(self):
        self.stop_sending_webcam()


    def init(self, opts):
        self.webcam_option = opts.webcam
        self.webcam_forwarding = self.webcam_option.lower() not in FALSE_OPTIONS
        self.server_webcam = False
        self.server_virtual_video_devices = 0
        if self.webcam_forwarding:
            try:
                import cv2
                from PIL import Image
                assert cv2 and Image
            except ImportError as e:
                log("init webcam failure", exc_info=True)
                if WIN32 and BITS==32:
                    log.info("32-bit builds do not support webcam forwarding")
                else:
                    log.warn("Warning: failed to import opencv:")
                    log.warn(" %s", e)
                    log.warn(" webcam forwarding is disabled")
                self.webcam_forwarding = False
        log("webcam forwarding: %s", self.webcam_forwarding)


    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.server_webcam = c.boolget("webcam")
        self.server_webcam_encodings = c.strlistget("webcam.encodings", ("png", "jpeg"))
        self.server_virtual_video_devices = c.intget("virtual-video-devices")
        log("webcam server support: %s (%i devices, encodings: %s)", self.server_webcam, self.server_virtual_video_devices, csv(self.server_webcam_encodings))
        if self.webcam_forwarding and self.server_webcam and self.server_virtual_video_devices>0:
            if self.webcam_option=="on" or self.webcam_option.find("/dev/video")>=0:
                self.start_sending_webcam()
        return True


    def webcam_state_changed(self):
        self.idle_add(self.emit, "webcam-changed")


    ######################################################################
    def start_sending_webcam(self):
        with self.webcam_lock:
            self.do_start_sending_webcam(self.webcam_option)

    def do_start_sending_webcam(self, device_str):
        assert self.server_webcam
        device = 0
        virt_devices, all_video_devices, non_virtual = {}, {}, {}
        try:
            from xpra.platform.webcam import get_virtual_video_devices, get_all_video_devices
            virt_devices = get_virtual_video_devices()
            all_video_devices = get_all_video_devices()
            non_virtual = dict([(k,v) for k,v in all_video_devices.items() if k not in virt_devices])
            log("virtual video devices=%s", virt_devices)
            log("all_video_devices=%s", all_video_devices)
            log("found %s known non-virtual video devices: %s", len(non_virtual), non_virtual)
        except ImportError as e:
            log("no webcam_util: %s", e)
        log("do_start_sending_webcam(%s)", device_str)
        if device_str in ("auto", "on", "yes", "off", "false", "true"):
            if len(non_virtual)>0:
                device = tuple(non_virtual.keys())[0]
        else:
            log("device_str: %s", device_str)
            try:
                device = int(device_str)
            except:
                p = device_str.find("video")
                if p>=0:
                    try:
                        log("device_str: %s", device_str[p:])
                        device = int(device_str[p+len("video"):])
                    except:
                        device = 0
        if device in virt_devices:
            log.warn("Warning: video device %s is a virtual device", virt_devices.get(device, device))
            if WEBCAM_ALLOW_VIRTUAL:
                log.warn(" environment override - this may hang..")
            else:
                log.warn(" corwardly refusing to use it")
                log.warn(" set WEBCAM_ALLOW_VIRTUAL=1 to force enable it")
                return
        import cv2
        log("do_start_sending_webcam(%s) device=%i", device_str, device)
        self.webcam_frame_no = 0
        try:
            #test capture:
            webcam_device = cv2.VideoCapture(device)        #0 -> /dev/video0
            ret, frame = webcam_device.read()
            log("test capture using %s: %s, %s", webcam_device, ret, frame is not None)
            assert ret, "no device or permission"
            assert frame is not None, "no data"
            assert frame.ndim==3, "unexpected  number of dimensions: %s" % frame.ndim
            w, h, Bpp = frame.shape
            assert Bpp==3, "unexpected number of bytes per pixel: %s" % Bpp
            assert frame.size==w*h*Bpp
            self.webcam_device_no = device
            self.webcam_device = webcam_device
            self.send("webcam-start", device, w, h)
            self.webcam_state_changed()
            log("webcam started")
            if self.send_webcam_frame():
                delay = 1000//WEBCAM_TARGET_FPS
                log("webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                self.cancel_webcam_send_timer()
                self.webcam_send_timer = self.timeout_add(delay, self.may_send_webcam_frame)
        except Exception as e:
            log.warn("webcam test capture failed: %s", e)

    def cancel_webcam_send_timer(self):
        wst = self.webcam_send_timer
        if wst:
            self.webcam_send_timer = None
            self.source_remove(wst)

    def cancel_webcam_check_ack_timer(self):
        wact = self.webcam_ack_check_timer
        if wact:
            self.webcam_ack_check_timer = None
            self.source_remove(wact)

    def webcam_check_acks(self, ack=0):
        self.webcam_ack_check_timer = None
        log("check_acks: webcam_last_ack=%s", self.webcam_last_ack)
        if self.webcam_last_ack<ack:
            log.warn("Warning: no acknowledgements received from the server for frame %i, stopping webcam", ack)
            self.stop_sending_webcam()

    def stop_sending_webcam(self):
        log("stop_sending_webcam()")
        with self.webcam_lock:
            self.do_stop_sending_webcam()

    def do_stop_sending_webcam(self):
        self.cancel_webcam_send_timer()
        self.cancel_webcam_check_ack_timer()
        wd = self.webcam_device
        log("do_stop_sending_webcam() device=%s", wd)
        if not wd:
            return
        self.send("webcam-stop", self.webcam_device_no)
        assert self.server_webcam
        self.webcam_device = None
        self.webcam_device_no = -1
        self.webcam_frame_no = 0
        self.webcam_last_ack = -1
        try:
            wd.release()
        except Exception as e:
            log.error("Error closing webcam device %s: %s", wd, e)
        self.webcam_state_changed()

    def may_send_webcam_frame(self):
        self.webcam_send_timer = None
        if self.webcam_device_no<0 or not self.webcam_device:
            return False
        not_acked = self.webcam_frame_no-1-self.webcam_last_ack
        #not all frames have been acked
        latency = 100
        if len(self.server_ping_latency)>0:
            l = [x for _,x in tuple(self.server_ping_latency)]
            latency = int(1000 * sum(l) / len(l))
        #how many frames should be in flight
        n = max(1, latency // (1000//WEBCAM_TARGET_FPS))    #20fps -> 50ms target between frames
        if not_acked>0 and not_acked>n:
            log("may_send_webcam_frame() latency=%i, not acked=%i, target=%i - will wait for next ack", latency, not_acked, n)
            return False
        log("may_send_webcam_frame() latency=%i, not acked=%i, target=%i - trying to send now", latency, not_acked, n)
        return self.send_webcam_frame()

    def send_webcam_frame(self):
        if not self.webcam_lock.acquire(False):
            return False
        log("send_webcam_frame() webcam_device=%s", self.webcam_device)
        try:
            assert self.webcam_device_no>=0, "device number is not set"
            assert self.webcam_device, "no webcam device to capture from"
            from xpra.codecs.pillow.encode import get_encodings
            client_webcam_encodings = get_encodings()
            common_encodings = list(set(self.server_webcam_encodings).intersection(client_webcam_encodings))
            log("common encodings (server=%s, client=%s): %s", csv(self.server_encodings), csv(client_webcam_encodings), csv(common_encodings))
            if not common_encodings:
                log.error("Error: cannot send webcam image, no common formats")
                log.error(" the server supports: %s", csv(self.server_webcam_encodings))
                log.error(" the client supports: %s", csv(client_webcam_encodings))
                self.stop_sending_webcam()
                return False
            preferred_order = ["jpeg", "png", "png/L", "png/P", "webp"]
            formats = [x for x in preferred_order if x in common_encodings] + common_encodings
            encoding = formats[0]
            start = monotonic_time()
            import cv2
            ret, frame = self.webcam_device.read()
            assert ret, "capture failed"
            assert frame.ndim==3, "invalid frame data"
            h, w, Bpp = frame.shape
            assert Bpp==3 and frame.size==w*h*Bpp
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            end = monotonic_time()
            log("webcam frame capture took %ims", (end-start)*1000)
            start = monotonic_time()
            from PIL import Image
            image = Image.fromarray(rgb)
            buf = BytesIOClass()
            image.save(buf, format=encoding)
            data = buf.getvalue()
            buf.close()
            end = monotonic_time()
            log("webcam frame compression to %s took %ims", encoding, (end-start)*1000)
            frame_no = self.webcam_frame_no
            self.webcam_frame_no += 1
            self.send("webcam-frame", self.webcam_device_no, frame_no, encoding, w, h, compression.Compressed(encoding, data))
            self.cancel_webcam_check_ack_timer()
            self.webcam_ack_check_timer = self.timeout_add(10*1000, self.webcam_check_acks)
            return True
        except Exception as e:
            log.error("webcam frame %i failed", self.webcam_frame_no, exc_info=True)
            log.error("Error sending webcam frame: %s", e)
            self.stop_sending_webcam()
            try:
                from xpra.notifications.common import XPRA_WEBCAM_NOTIFICATION_ID
            except ImportError:
                log("no notifications")
            else:
                summary = "Webcam forwarding has failed"
                body = "The system encountered the following error:\n" + \
                    ("%s\n" % e)
                self.may_notify(XPRA_WEBCAM_NOTIFICATION_ID, summary, body, expire_timeout=10*1000, icon_name="webcam")
            return False
        finally:
            self.webcam_lock.release()


    ######################################################################
    #packet handlers
    def _process_webcam_stop(self, packet):
        device_no = packet[1]
        if device_no!=self.webcam_device_no:
            return
        self.stop_sending_webcam()

    def _process_webcam_ack(self, packet):
        log("process_webcam_ack: %s", packet)
        with self.webcam_lock:
            if self.webcam_device:
                frame_no = packet[2]
                self.webcam_last_ack = frame_no
                if self.may_send_webcam_frame():
                    self.cancel_webcam_send_timer()
                    delay = 1000//WEBCAM_TARGET_FPS
                    log("new webcam timer with delay=%ims for %i fps target)", delay, WEBCAM_TARGET_FPS)
                    self.webcam_send_timer = self.timeout_add(delay, self.may_send_webcam_frame)


    def init_authenticated_packet_handlers(self):
        log("init_authenticated_packet_handlers()")
        self.set_packet_handlers(self._ui_packet_handlers, {
            "webcam-stop":          self._process_webcam_stop,
            "webcam-ack":           self._process_webcam_ack,
            })
