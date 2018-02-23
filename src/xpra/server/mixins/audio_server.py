# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path

from xpra.log import Logger
log = Logger("server")
soundlog = Logger("sound")

from xpra.os_util import pollwait, monotonic_time, bytestostr, osexpand, OSX, POSIX
from xpra.util import typedict, envbool, csv
from xpra.platform import get_username
from xpra.platform.paths import get_icon_filename
from xpra.scripts.parsing import sound_option
from xpra.server.mixins.stub_server_mixin import StubServerMixin


PRIVATE_PULSEAUDIO = envbool("XPRA_PRIVATE_PULSEAUDIO", POSIX and not OSX)


"""
Mixin for servers that handle audio forwarding.
"""
class AudioServer(StubServerMixin):

    def __init__(self):
        self.pulseaudio = False
        self.pulseaudio_command = None
        self.pulseaudio_configure_commands = []
        self.pulseaudio_proc = None
        self.pulseaudio_private_dir = None
        self.pulseaudio_private_socket = None
        self.sound_source_plugin = None
        self.supports_speaker = False
        self.supports_microphone = False
        self.speaker_codec_str = ""
        self.microphone_codec_str = ""
        self.sound_properties = typedict()

    def init(self, opts):
        self.sound_source_plugin = opts.sound_source
        self.supports_speaker = sound_option(opts.speaker) in ("on", "off")
        self.supports_microphone = sound_option(opts.microphone) in ("on", "off")
        self.pulseaudio = opts.pulseaudio
        self.pulseaudio_command = opts.pulseaudio_command
        self.pulseaudio_configure_commands = opts.pulseaudio_configure_commands

    def setup(self, _opts):
        self.init_pulseaudio()
        self.init_sound_options()

    def cleanup(self):
        self.cleanup_pulseaudio()


    def init_pulseaudio(self):
        soundlog("init_pulseaudio() pulseaudio=%s, pulseaudio_command=%s", self.pulseaudio, self.pulseaudio_command)
        if self.pulseaudio is False:
            return
        if not self.pulseaudio_command:
            soundlog.warn("Warning: pulseaudio command is not defined")
            return
        #environment initialization:
        # 1) make sure that the sound subprocess will use the devices
        #    we define in the pulseaudio command
        #    (it is too difficult to parse the pulseaudio_command,
        #    so we just hope that it matches this):
        #    Note: speaker is the source and microphone the sink,
        #    because things are reversed on the server.
        os.environ.update({
            "XPRA_PULSE_SOURCE_DEVICE_NAME" : "Xpra-Speaker",
            "XPRA_PULSE_SINK_DEVICE_NAME"   : "Xpra-Microphone",
            })
        # 2) whitelist the env vars that pulseaudio may use:
        PA_ENV_WHITELIST = ("DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_SESSION_BUS_WINDOWID",
                            "DISPLAY", "HOME", "HOSTNAME", "LANG", "PATH",
                            "PWD", "SHELL", "XAUTHORITY",
                            "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
                            "XPRA_PULSE_SOURCE_DEVICE_NAME", "XPRA_PULSE_SINK_DEVICE_NAME",
                            )
        env = dict((k,v) for k,v in self.get_child_env().items() if k in PA_ENV_WHITELIST)
        # 3) use a private pulseaudio server, so each xpra
        #    session can have its own server,
        #    create a directory for each display:
        if PRIVATE_PULSEAUDIO:
            from xpra.platform.xposix.paths import _get_xpra_runtime_dir
            xpra_rd = _get_xpra_runtime_dir()
            if xpra_rd:
                display = os.environ.get("DISPLAY")
                self.pulseaudio_private_dir = osexpand(os.path.join(xpra_rd, "pulse-%s" % display))
                if not os.path.exists(self.pulseaudio_private_dir):
                    os.mkdir(self.pulseaudio_private_dir, 0o700)
                env["XDG_RUNTIME_DIR"] = self.pulseaudio_private_dir
                self.pulseaudio_private_socket = os.path.join(self.pulseaudio_private_dir, "pulse", "native")
                os.environ["XPRA_PULSE_SERVER"] = self.pulseaudio_private_socket
        import shlex
        cmd = shlex.split(self.pulseaudio_command)
        cmd = list(osexpand(x) for x in cmd)
        #find the absolute path to the command:
        pa_cmd = cmd[0]
        if not os.path.isabs(pa_cmd):
            pa_path = None
            for x in os.environ.get("PATH", "").split(os.path.pathsep):
                t = os.path.join(x, pa_cmd)
                if os.path.exists(t):
                    pa_path = t
                    break
            if not pa_path:
                msg = "pulseaudio not started: '%s' command not found" % pa_cmd
                if self.pulseaudio is None:
                    soundlog.info(msg)
                else:
                    soundlog.warn(msg)
                return
            cmd[0] = pa_cmd
        started_at = monotonic_time()
        def pulseaudio_warning():
            soundlog.warn("Warning: pulseaudio has terminated shortly after startup.")
            soundlog.warn(" pulseaudio is limited to a single instance per user account,")
            soundlog.warn(" and one may be running already for user '%s'.", get_username())
            soundlog.warn(" To avoid this warning, either fix the pulseaudio command line")
            soundlog.warn(" or use the 'pulseaudio=no' option.")
        def pulseaudio_ended(proc):
            soundlog("pulseaudio_ended(%s) pulseaudio_proc=%s, returncode=%s, closing=%s", proc, self.pulseaudio_proc, proc.returncode, self._closing)
            if self.pulseaudio_proc is None or self._closing:
                #cleared by cleanup already, ignore
                return
            elapsed = monotonic_time()-started_at
            if elapsed<2:
                self.timeout_add(1000, pulseaudio_warning)
            else:
                soundlog.warn("Warning: the pulseaudio server process has terminated after %i seconds", int(elapsed))
            self.pulseaudio_proc = None
        import subprocess
        try:
            soundlog("pulseaudio cmd=%s", " ".join(cmd))
            soundlog("pulseaudio env=%s", env)
            self.pulseaudio_proc = subprocess.Popen(cmd, stdin=None, env=env, shell=False, close_fds=True)
        except Exception as e:
            soundlog("Popen(%s)", cmd, exc_info=True)
            soundlog.error("Error: failed to start pulseaudio:")
            soundlog.error(" %s", e)
            return
        self.add_process(self.pulseaudio_proc, "pulseaudio", cmd, ignore=True, callback=pulseaudio_ended)
        if self.pulseaudio_proc:
            soundlog.info("pulseaudio server started with pid %s", self.pulseaudio_proc.pid)
            if self.pulseaudio_private_socket:
                soundlog.info(" private server socket path:")
                soundlog.info(" '%s'", self.pulseaudio_private_socket)
                os.environ["PULSE_SERVER"] = "unix:%s" % self.pulseaudio_private_socket
            def configure_pulse():
                p = self.pulseaudio_proc
                if p is None or p.poll() is not None:
                    return
                for i, x in enumerate(self.pulseaudio_configure_commands):
                    proc = subprocess.Popen(x, stdin=None, env=env, shell=True, close_fds=True)
                    self.add_process(proc, "pulseaudio-configure-command-%i" % i, x, ignore=True)
            self.timeout_add(2*1000, configure_pulse)

    def cleanup_pulseaudio(self):
        proc = self.pulseaudio_proc
        if not proc:
            return
        soundlog("cleanup_pa() process.poll()=%s, pid=%s", proc.poll(), proc.pid)
        if self.is_child_alive(proc):
            self.pulseaudio_proc = None
            soundlog.info("stopping pulseaudio with pid %s", proc.pid)
            try:
                #first we try pactl (required on Ubuntu):
                import subprocess
                cmd = ["pactl", "exit"]
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.add_process(proc, "pactl exit", cmd, True)
                r = pollwait(proc)
                #warning: pactl will return 0 whether it succeeds or not...
                #but we can't kill the process because Ubuntu starts a new one
                if r!=0 and self.is_child_alive(proc):
                    #fallback to using SIGINT:
                    proc.terminate()
            except Exception as e:
                soundlog.warn("cleanup_pulseaudio() error stopping %s", proc, exc_info=True)
                #only log the full stacktrace if the process failed to terminate:
                if self.is_child_alive(proc):
                    soundlog.error("Error: stopping pulseaudio: %s", e, exc_info=True)
        try:
            if self.pulseaudio_private_socket and os.path.exists(self.pulseaudio_private_socket):
                try:
                    os.unlink(self.pulseaudio_private_socket)
                except Exception as e:
                    soundlog("failed to remove private socket '%s'", self.pulseaudio_private_socket, exc_info=True)
            if self.pulseaudio_private_dir:
                pulse = os.path.join(self.pulseaudio_private_dir, "pulse")
                native = os.path.join(self.pulseaudio_private_dir, "pulse", "native")
                for x in (native, pulse, self.pulseaudio_private_dir):
                    soundlog("removing private directory '%s'", x)
                    if os.path.exists(x) and os.path.isdir(x):
                        os.rmdir(x)
        except Exception as e:
            soundlog("cleanup_pulseaudio() error cleaning up private directory", exc_info=True)
            

    def init_sound_options(self):
        def sound_option_or_all(*_args):
            return []
        if self.supports_speaker or self.supports_microphone:
            try:
                from xpra.sound.common import sound_option_or_all
                from xpra.sound.wrapper import query_sound
                self.sound_properties = query_sound()
                assert self.sound_properties, "query did not return any data"
                def vinfo(k):
                    val = self.sound_properties.listget(k)
                    assert val, "%s not found in sound properties" % bytestostr(k)
                    return ".".join(bytestostr(x) for x in val[:3])
                bits = self.sound_properties.intget("python.bits", 32)
                soundlog.info("GStreamer version %s for Python %s %i-bit", vinfo("gst.version"), vinfo("python.version"), bits)
            except Exception as e:
                soundlog("failed to query sound", exc_info=True)
                soundlog.error("Error: failed to query sound subsystem:")
                soundlog.error(" %s", e)
                self.speaker_allowed = False
                self.microphone_allowed = False
        encoders = self.sound_properties.strlistget("encoders", [])
        decoders = self.sound_properties.strlistget("decoders", [])
        self.speaker_codecs = sound_option_or_all("speaker-codec", self.speaker_codec_str, encoders)
        self.microphone_codecs = sound_option_or_all("microphone-codec", self.microphone_codec_str, decoders)
        if not self.speaker_codecs:
            self.supports_speaker = False
        if not self.microphone_codecs:
            self.supports_microphone = False
        if bool(self.sound_properties):
            try:
                from xpra.sound.pulseaudio.pulseaudio_util import set_icon_path, get_info as get_pa_info
                pa_info = get_pa_info()
                soundlog("pulseaudio info=%s", pa_info)
                self.sound_properties.update(pa_info)
                set_icon_path(get_icon_filename("xpra.png"))
            except ImportError as e:
                if POSIX and not OSX:
                    log.warn("Warning: failed to set pulseaudio tagging icon:")
                    log.warn(" %s", e)
        soundlog("init_sound_options speaker: supported=%s, encoders=%s", self.supports_speaker, csv(self.speaker_codecs))
        soundlog("init_sound_options microphone: supported=%s, decoders=%s", self.supports_microphone, csv(self.microphone_codecs))
        soundlog("init_sound_options sound properties=%s", self.sound_properties)

    def get_pulseaudio_info(self):
        info = {
            "command"               : self.pulseaudio_command,
            "configure-commands"    : self.pulseaudio_configure_commands,
            }
        if self.pulseaudio_proc and self.pulseaudio_proc.poll() is None:
            info["pid"] = self.pulseaudio_proc.pid
        if self.pulseaudio_private_dir and self.pulseaudio_private_socket:
            info["private-directory"] = self.pulseaudio_private_dir
            info["private-socket"] = self.pulseaudio_private_socket
        return info

    def get_info(self):
        info = {}
        if self.pulseaudio:
            info["pulseaudio"] = self.get_pulseaudio_info()
        if self.sound_properties:
            info["sound"] = self.sound_properties
        return {}


    def _process_sound_control(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.sound_control(*packet[1:])

    def _process_sound_data(self, proto, packet):
        ss = self._server_sources.get(proto)
        if ss:
            ss.sound_data(*packet[1:])


    def init_packet_handlers(self):
        self._authenticated_ui_packet_handlers.update({
            "sound-control":                        self._process_sound_control,
            "sound-data":                           self._process_sound_data,
            })
