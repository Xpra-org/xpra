#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def main():
    import sys
    from xpra.platform import program_context, command_error
    with program_context("Webcam", "Webcam"):
        from xpra.log import Logger, add_debug_category
        log = Logger("webcam")
        if "-v" in sys.argv or "--verbose" in sys.argv:
            add_debug_category("webcam")
            log.enable_debug()
        try:
            import cv2
        except ImportError as e:
            command_error("Error: no opencv support module: %s" % e)
            return 1
        device = 0
        if len(sys.argv)==2:
            try:
                device = int(sys.argv[1])
            except:
                command_error("Warning: failed to parse value as a device number: '%s'" % sys.argv[1])
        try:
            cap = cv2.VideoCapture(device)
        except Exception as e:
            command_error("Error: failed to capture video using device %s:\n%s" % (device, e))
            return 1
        log.info("capture device for %i: %s", device, cap)
        while True:
            ret, frame = cap.read()
            if not ret:
                command_error("Error: frame capture failed using device %s" % device)
                return 1
            cv2.imshow('frame', frame)
            if cv2.waitKey(10) & 0xFF in (ord('q'), 27):
                break
        cap.release()
        cv2.destroyAllWindows()
        return 0

if __name__ == "__main__":
    import sys
    v = main()
    sys.exit(v)
