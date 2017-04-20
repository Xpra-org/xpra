# This file is part of Xpra.
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal
import os
import sys
import socket
import binascii
import string
from xpra.gtk_common.gobject_compat import import_gobject, import_glib
gobject = import_gobject()

from xpra.log import Logger
log = Logger("client")
printlog = Logger("printing")
filelog = Logger("file")
netlog = Logger("network")
authlog = Logger("auth")

from xpra.scripts.config import InitExit
from xpra.child_reaper import getChildReaper, reaper_cleanup
from xpra.net import compression
from xpra.net.protocol import Protocol, get_network_caps, sanity_checks
from xpra.net.crypto import crypto_backend_init, get_iterations, get_iv, get_salt, choose_padding, get_digest_module, \
    ENCRYPTION_CIPHERS, ENCRYPT_FIRST_PACKET, DEFAULT_IV, DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING, DEFAULT_PADDING, ALL_PADDING_OPTIONS, PADDING_OPTIONS
from xpra.version_util import version_compat_check, get_version_info, XPRA_VERSION
from xpra.platform.info import get_name
from xpra.os_util import get_machine_id, get_user_uuid, load_binary_file, SIGNAMES, strtobytes, bytestostr, memoryview_to_bytes
from xpra.util import flatten_dict, typedict, updict, xor, repr_ellipsized, nonl, envbool, disconnect_is_an_error, dump_all_frames
from xpra.net.file_transfer import FileTransferHandler

from xpra.exit_codes import (EXIT_OK, EXIT_CONNECTION_LOST, EXIT_TIMEOUT, EXIT_UNSUPPORTED,
        EXIT_PASSWORD_REQUIRED, EXIT_PASSWORD_FILE_ERROR, EXIT_INCOMPATIBLE_VERSION,
        EXIT_ENCRYPTION, EXIT_FAILURE, EXIT_PACKET_FAILURE,
        EXIT_NO_AUTHENTICATION, EXIT_INTERNAL_ERROR)

try:
    from xpra.codecs.xor.cyxor import xor_str           #@UnresolvedImport
    xor = xor_str
except:
    pass


EXTRA_TIMEOUT = 10
ALLOW_UNENCRYPTED_PASSWORDS = envbool("XPRA_ALLOW_UNENCRYPTED_PASSWORDS", False)
ALLOW_LOCALHOST_PASSWORDS = envbool("XPRA_ALLOW_LOCALHOST_PASSWORDS", True)
DETECT_LEAKS = envbool("XPRA_DETECT_LEAKS", False)
DELETE_PRINTER_FILE = envbool("XPRA_DELETE_PRINTER_FILE", True)
SKIP_STOPPED_PRINTERS = envbool("XPRA_SKIP_STOPPED_PRINTERS", True)


class XpraClientBase(FileTransferHandler):
    """ Base class for Xpra clients.
        Provides the glue code for:
        * sending packets via Protocol
        * handling packets received via _process_packet
        For an actual implementation, look at:
        * GObjectXpraClient
        * xpra.client.gtk2.client
        * xpra.client.gtk3.client
    """

    def __init__(self):
        FileTransferHandler.__init__(self)
        #this may be called more than once,
        #skip doing internal init again:
        if not hasattr(self, "exit_code"):
            self.defaults_init()

    def defaults_init(self):
        #skip warning when running the client
        from xpra import child_reaper
        child_reaper.POLL_WARNING = False
        getChildReaper()
        log("XpraClientBase.defaults_init() os.environ:")
        for k,v in os.environ.items():
            log(" %s=%s", k, nonl(v))
        #client state:
        self.exit_code = None
        self.exit_on_signal = False
        self.display_desc = {}
        #connection attributes:
        self.hello_extra = {}
        self.compression_level = 0
        self.display = None
        self.username = None
        self.password = None
        self.password_file = None
        self.password_sent = False
        self.encryption = None
        self.encryption_keyfile = None
        self.server_padding_options = [DEFAULT_PADDING]
        self.quality = -1
        self.min_quality = 0
        self.speed = 0
        self.min_speed = -1
        self.printer_attributes = []
        self.send_printers_timer = None
        self.exported_printers = None
        #protocol stuff:
        self._protocol = None
        self._priority_packets = []
        self._ordinary_packets = []
        self._mouse_position = None
        self._aliases = {}
        self._reverse_aliases = {}
        #server state and caps:
        self.server_capabilities = None
        self._remote_machine_id = None
        self._remote_uuid = None
        self._remote_version = None
        self._remote_revision = None
        self._remote_platform = None
        self._remote_platform_release = None
        self._remote_platform_platform = None
        self._remote_platform_linux_distribution = None
        self.uuid = get_user_uuid()
        self.init_packet_handlers()
        sanity_checks()

    def init(self, opts):
        self.compression_level = opts.compression_level
        self.display = opts.display
        self.username = opts.username
        self.password = opts.password
        self.password_file = opts.password_file
        self.encryption = opts.encryption or opts.tcp_encryption
        if self.encryption:
            crypto_backend_init()
        self.encryption_keyfile = opts.encryption_keyfile or opts.tcp_encryption_keyfile
        self.quality = opts.quality
        self.min_quality = opts.min_quality
        self.speed = opts.speed
        self.min_speed = opts.min_speed
        #printing and file transfer:
        FileTransferHandler.init_opts(self, opts)

        if DETECT_LEAKS:
            from xpra.util import detect_leaks
            detailed = []
            #example: warning, uses ugly direct import:
            #try:
            #    from xpra.x11.bindings.ximage import XShmImageWrapper       #@UnresolvedImport
            #    detailed.append(XShmImageWrapper)
            #except:
            #    pass
            print_leaks = detect_leaks(log, detailed)
            self.timeout_add(10*1000, print_leaks)


    def timeout_add(self, *args):
        raise Exception("override me!")

    def idle_add(self, *args):
        raise Exception("override me!")

    def source_remove(self, *args):
        raise Exception("override me!")


    def install_signal_handlers(self):
        def deadly_signal(signum, frame):
            sys.stderr.write("\ngot deadly signal %s, exiting\n" % SIGNAMES.get(signum, signum))
            sys.stderr.flush()
            self.cleanup()
            os._exit(128 + signum)
        def app_signal(signum, frame):
            sys.stderr.write("\ngot signal %s, exiting\n" % SIGNAMES.get(signum, signum))
            sys.stderr.flush()
            signal.signal(signal.SIGINT, deadly_signal)
            signal.signal(signal.SIGTERM, deadly_signal)
            self.signal_cleanup()
            self.timeout_add(0, self.signal_disconnect_and_quit, 128 + signum, "exit on signal %s" % SIGNAMES.get(signum, signum))
        if sys.version_info[0]<3:
            #breaks GTK3..
            signal.signal(signal.SIGINT, app_signal)
        signal.signal(signal.SIGTERM, app_signal)

    def signal_disconnect_and_quit(self, exit_code, reason):
        log("signal_disconnect_and_quit(%s, %s) exit_on_signal=%s", exit_code, reason, self.exit_on_signal)
        if not self.exit_on_signal:
            #if we get another signal, we'll try to exit without idle_add...
            self.exit_on_signal = True
            self.idle_add(self.disconnect_and_quit, exit_code, reason)
            self.idle_add(self.quit, exit_code)
            self.idle_add(self.exit)
            return
        #warning: this will run cleanup code from the signal handler
        self.disconnect_and_quit(exit_code, reason)
        self.quit(exit_code)
        self.exit()
        os._exit(exit_code)

    def signal_cleanup(self):
        #placeholder for stuff that can be cleaned up from the signal handler
        #(non UI thread stuff)
        pass

    def disconnect_and_quit(self, exit_code, reason):
        #make sure that we set the exit code early,
        #so the protocol shutdown won't set a different one:
        if self.exit_code is None:
            self.exit_code = exit_code
        #try to tell the server we're going, then quit
        log("disconnect_and_quit(%s, %s)", exit_code, reason)
        p = self._protocol
        if p is None or p._closed:
            self.quit(exit_code)
            return
        def protocol_closed():
            log("disconnect_and_quit: protocol_closed()")
            self.idle_add(self.quit, exit_code)
        if p:
            p.flush_then_close(["disconnect", reason], done_callback=protocol_closed)
        self.timeout_add(1000, self.quit, exit_code)

    def exit(self):
        sys.exit()


    def client_type(self):
        #overriden in subclasses!
        return "Python"

    def get_scheduler(self):
        raise NotImplementedError()

    def setup_connection(self, conn):
        netlog("setup_connection(%s) timeout=%s", conn, conn.timeout)
        self._protocol = Protocol(self.get_scheduler(), conn, self.process_packet, self.next_packet)
        self._protocol.large_packets.append("keymap-changed")
        self._protocol.large_packets.append("server-settings")
        self._protocol.large_packets.append("logging")
        self._protocol.set_compression_level(self.compression_level)
        self._protocol.receive_aliases.update(self._aliases)
        self._protocol.enable_default_encoder()
        self._protocol.enable_default_compressor()
        if self.encryption and ENCRYPT_FIRST_PACKET:
            key = self.get_encryption_key()
            self._protocol.set_cipher_out(self.encryption, DEFAULT_IV, key, DEFAULT_SALT, DEFAULT_ITERATIONS, INITIAL_PADDING)
        self.have_more = self._protocol.source_has_more
        if conn.timeout>0:
            self.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)
        process = getattr(conn, "process", None)        #ie: ssh is handled by anotherprocess
        if process:
            proc, name, command = process
            getChildReaper().add_process(proc, name, command, ignore=True, forget=False)
        netlog("setup_connection(%s) protocol=%s", conn, self._protocol)


    def remove_packet_handlers(self, *keys):
        for k in keys:
            for d in (self._packet_handlers, self._ui_packet_handlers):
                try:
                    del d[k]
                except:
                    pass

    def set_packet_handlers(self, to, defs):
        """ configures the given packet handlers,
            and make sure we remove any existing ones with the same key
            (which can be useful for subclasses, not here)
        """
        log("set_packet_handlers(%s, %s)", to, defs)
        self.remove_packet_handlers(*defs.keys())
        for k,v in defs.items():
            to[k] = v

    def init_packet_handlers(self):
        self._packet_handlers = {}
        self._ui_packet_handlers = {}
        self.set_packet_handlers(self._packet_handlers, {"hello" : self._process_hello})
        self.set_packet_handlers(self._ui_packet_handlers, {
            "challenge":                self._process_challenge,
            "disconnect":               self._process_disconnect,
            "set_deflate":              self._process_set_deflate,
            "startup-complete":         self._process_startup_complete,
            Protocol.CONNECTION_LOST:   self._process_connection_lost,
            Protocol.GIBBERISH:         self._process_gibberish,
            Protocol.INVALID:           self._process_invalid,
            })

    def init_authenticated_packet_handlers(self):
        self.set_packet_handlers(self._packet_handlers, {
                                                         "send-file"        : self._process_send_file,
                                                         "ack-file-chunk"   : self._process_ack_file_chunk,
                                                         "send-file-chunk"  : self._process_send_file_chunk,
                                                         })


    def init_aliases(self):
        packet_types = list(self._packet_handlers.keys())
        packet_types += list(self._ui_packet_handlers.keys())
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            self._reverse_aliases[key] = i
            i += 1

    def has_password(self):
        return self.password or self.password_file or os.environ.get('XPRA_PASSWORD')

    def send_hello(self, challenge_response=None, client_salt=None):
        try:
            hello = self.make_hello_base()
            if self.has_password() and not challenge_response:
                #avoid sending the full hello: tell the server we want
                #a packet challenge first
                hello["challenge"] = True
            else:
                hello.update(self.make_hello())
        except InitExit as e:
            log.error("error preparing connection:")
            log.error(" %s", e)
            self.quit(EXIT_INTERNAL_ERROR)
            return
        except Exception as e:
            log.error("error preparing connection: %s", e, exc_info=True)
            self.quit(EXIT_INTERNAL_ERROR)
            return
        if challenge_response:
            assert self.has_password(), "got a password challenge response but we don't have a password! (malicious or broken server?)"
            hello["challenge_response"] = challenge_response
            if client_salt:
                hello["challenge_client_salt"] = client_salt
        log("send_hello(%s) packet=%s", binascii.hexlify(strtobytes(challenge_response or "")), hello)
        self.send("hello", hello)

    def verify_connected(self):
        if self.server_capabilities is None:
            #server has not said hello yet
            self.warn_and_quit(EXIT_TIMEOUT, "connection timed out")


    def make_hello_base(self):
        capabilities = flatten_dict(get_network_caps())
        import struct
        bits = struct.calcsize("P") * 8
        capabilities.update({
                "version"               : XPRA_VERSION,
                "encoding.generic"      : True,
                "namespace"             : True,
                "hostname"              : socket.gethostname(),
                "uuid"                  : self.uuid,
                "username"              : self.username,
                "name"                  : get_name(),
                "client_type"           : self.client_type(),
                "python.version"        : sys.version_info[:3],
                "python.bits"           : bits,
                "compression_level"     : self.compression_level,
                "argv"                  : sys.argv,
                })
        capabilities.update(self.get_file_transfer_features())
        if self.display:
            capabilities["display"] = self.display
        def up(prefix, d):
            updict(capabilities, prefix, d)
        up("build",     self.get_version_info())
        mid = get_machine_id()
        if mid:
            capabilities["machine_id"] = mid

        if self.encryption:
            assert self.encryption in ENCRYPTION_CIPHERS
            iv = get_iv()
            key_salt = get_salt()
            iterations = get_iterations()
            padding = choose_padding(self.server_padding_options)
            up("cipher", {
                    ""                      : self.encryption,
                    "iv"                    : iv,
                    "key_salt"              : key_salt,
                    "key_stretch_iterations": iterations,
                    "padding"               : padding,
                    "padding.options"       : PADDING_OPTIONS,
                    })
            key = self.get_encryption_key()
            if key is None:
                self.warn_and_quit(EXIT_ENCRYPTION, "encryption key is missing")
                return
            self._protocol.set_cipher_in(self.encryption, iv, key, key_salt, iterations, padding)
            netlog("encryption capabilities: %s", dict((k,v) for k,v in capabilities.items() if k.startswith("cipher")))
        capabilities.update(self.hello_extra)
        return capabilities

    def get_version_info(self):
        return get_version_info()

    def make_hello(self):
        capabilities = {
                        "randr_notify"        : False,        #only client.py cares about this
                        "windows"            : False,        #only client.py cares about this
                       }
        if self._reverse_aliases:
            capabilities["aliases"] = self._reverse_aliases
        return capabilities

    def compressed_wrapper(self, datatype, data, level=5):
        #FIXME: ugly assumptions here, should pass by name!
        zlib = "zlib" in self.server_compressors and compression.use_zlib
        lz4 = "lz4" in self.server_compressors and compression.use_lz4
        lzo = "lzo" in self.server_compressors and compression.use_lzo
        if level>0 and len(data)>=256 and (zlib or lz4 or lzo):
            cw = compression.compressed_wrapper(datatype, data, level=level, zlib=zlib, lz4=lz4, lzo=lzo, can_inline=False)
            if len(cw)<len(data):
                #the compressed version is smaller, use it:
                return cw
        #we can't compress, so at least avoid warnings in the protocol layer:
        return compression.Compressed("raw %s" % datatype, data, can_inline=True)


    def send(self, *parts):
        self._ordinary_packets.append(parts)
        self.have_more()

    def send_now(self, *parts):
        self._priority_packets.append(parts)
        self.have_more()

    def send_positional(self, packet):
        self._ordinary_packets.append(packet)
        self._mouse_position = None
        self.have_more()

    def send_mouse_position(self, packet):
        self._mouse_position = packet
        self.have_more()

    def have_more(self):
        #this function is overridden in setup_protocol()
        p = self._protocol
        if p and p.source:
            p.source_has_more()

    def next_packet(self):
        if self._priority_packets:
            packet = self._priority_packets.pop(0)
        elif self._ordinary_packets:
            packet = self._ordinary_packets.pop(0)
        elif self._mouse_position is not None:
            packet = self._mouse_position
            self._mouse_position = None
        else:
            packet = None
        has_more = packet is not None and \
                (bool(self._priority_packets) or bool(self._ordinary_packets) \
                 or self._mouse_position is not None)
        return packet, None, None, has_more


    def cleanup(self):
        reaper_cleanup()
        #we must clean printing before FileTransferHandler, which turns the printing flag off!
        self.cleanup_printing()
        FileTransferHandler.cleanup(self)
        p = self._protocol
        log("XpraClientBase.cleanup() protocol=%s", p)
        if p:
            log("calling %s", p.close)
            p.close()
            self._protocol = None
        log("cleanup done")
        dump_all_frames()


    def glib_init(self):
        glib = import_glib()
        glib.threads_init()

    def run(self):
        self._protocol.start()

    def quit(self, exit_code=0):
        raise Exception("override me!")

    def warn_and_quit(self, exit_code, message):
        log.warn(message)
        self.quit(exit_code)


    def _process_disconnect(self, packet):
        #ie: ("disconnect", "version error", "incompatible version")
        reason = bytestostr(packet[1])
        info = packet[2:]
        s = nonl(reason)
        if len(info):
            s += " (%s)" % (", ".join([nonl(bytestostr(x)) for x in info]))
        if self.server_capabilities is None or len(self.server_capabilities)==0:
            #server never sent hello to us - so disconnect is an error
            #(but we don't know which one - the info message may help)
            log.warn("server failure: disconnected before the session could be established")
            e = EXIT_FAILURE
        elif disconnect_is_an_error(reason):
            log.warn("server failure: %s", reason)
            e = EXIT_FAILURE
        else:
            if self.exit_code is None:
                #we're not in the process of exiting already,
                #tell the user why the server is disconnecting us
                log.info("server requested disconnect: %s", s)
            self.quit(EXIT_OK)
            return
        self.warn_and_quit(e, "server requested disconnect: %s" % s)

    def _process_connection_lost(self, packet):
        p = self._protocol
        if p and p.input_raw_packetcount==0:
            props = p.get_info()
            c = props.get("compression", "unknown")
            e = props.get("encoder", "unknown")
            netlog.error("Error: failed to receive anything, not an xpra server?")
            netlog.error("  could also be the wrong protocol, username, password or port")
            if c!="unknown" or e!="unknown":
                netlog.error("  or maybe this server does not support '%s' compression or '%s' packet encoding?", c, e)
        if self.exit_code!=0:
            self.warn_and_quit(EXIT_CONNECTION_LOST, "Connection lost")

    def _process_challenge(self, packet):
        authlog("processing challenge: %s", packet[1:])
        def warn_server_and_exit(code, message, server_message="authentication failed"):
            authlog.error("Error: authentication failed:")
            authlog.error(" %s", message)
            self.disconnect_and_quit(code, server_message)
        if not self.has_password():
            warn_server_and_exit(EXIT_PASSWORD_REQUIRED, "this server requires authentication, please provide a password", "no password available")
            return
        password = self.load_password()
        if not password:
            warn_server_and_exit(EXIT_PASSWORD_FILE_ERROR, "failed to load password from file %s" % self.password_file, "no password available")
            return
        server_salt = packet[1]
        if self.encryption:
            assert len(packet)>=3, "challenge does not contain encryption details to use for the response"
            server_cipher = typedict(packet[2])
            key = self.get_encryption_key()
            if key is None:
                warn_server_and_exit(EXIT_ENCRYPTION, "the server does not use any encryption", "client requires encryption")
                return
            if not self.set_server_encryption(server_cipher, key):
                return
        #all server versions support a client salt,
        #they also tell us which digest to use:
        digest = packet[3]
        client_salt = get_salt(len(server_salt))
        #TODO: use some key stretching algorigthm? (meh)
        salt = xor(server_salt, client_salt)
        if digest.startswith(b"hmac"):
            import hmac
            digestmod = get_digest_module(digest)
            if not digestmod:
                log("invalid digest module '%s': %s", digest)
                warn_server_and_exit(EXIT_UNSUPPORTED, "server requested digest '%s' but it is not supported" % digest, "invalid digest")
                return
            password = strtobytes(password)
            salt = memoryview_to_bytes(salt)
            challenge_response = hmac.HMAC(password, salt, digestmod=digestmod).hexdigest()
            authlog("hmac.HMAC(%s, %s)=%s", binascii.hexlify(password), binascii.hexlify(salt), challenge_response)
        elif digest==b"xor":
            #don't send XORed password unencrypted:
            encrypted = self._protocol.cipher_out or self._protocol.get_info().get("type")=="ssl"
            local = self.display_desc.get("local", False)
            authlog("xor challenge, encrypted=%s, local=%s", encrypted, local)
            if local and ALLOW_LOCALHOST_PASSWORDS:
                pass
            elif not encrypted and not ALLOW_UNENCRYPTED_PASSWORDS:
                warn_server_and_exit(EXIT_ENCRYPTION, "server requested digest %s, cowardly refusing to use it without encryption" % digest, "invalid digest")
                return
            salt = salt[:len(password)]
            challenge_response = strtobytes(xor(password, salt))
        else:
            warn_server_and_exit(EXIT_PASSWORD_REQUIRED, "server requested an unsupported digest: %s" % digest, "invalid digest")
            return
        if digest:
            authlog("%s(%s, %s)=%s", digest, binascii.hexlify(password), binascii.hexlify(salt), challenge_response)
        self.password_sent = True
        self.remove_packet_handlers("challenge")
        self.send_hello(challenge_response, client_salt)

    def set_server_encryption(self, caps, key):
        cipher = caps.strget("cipher")
        cipher_iv = caps.strget("cipher.iv")
        key_salt = caps.strget("cipher.key_salt")
        iterations = caps.intget("cipher.key_stretch_iterations")
        padding = caps.strget("cipher.padding", DEFAULT_PADDING)
        #server may tell us what it supports,
        #either from hello response or from challenge packet:
        self.server_padding_options = caps.strlistget("cipher.padding.options", [DEFAULT_PADDING])
        if not cipher or not cipher_iv:
            self.warn_and_quit(EXIT_ENCRYPTION, "the server does not use or support encryption/password, cannot continue with %s cipher" % self.encryption)
            return False
        if cipher not in ENCRYPTION_CIPHERS:
            self.warn_and_quit(EXIT_ENCRYPTION, "unsupported server cipher: %s, allowed ciphers: %s" % (cipher, ", ".join(ENCRYPTION_CIPHERS)))
            return False
        if padding not in ALL_PADDING_OPTIONS:
            self.warn_and_quit(EXIT_ENCRYPTION, "unsupported server cipher padding: %s, allowed ciphers: %s" % (padding, ", ".join(ALL_PADDING_OPTIONS)))
            return False
        p = self._protocol
        if not p:
            return False
        p.set_cipher_out(cipher, cipher_iv, key, key_salt, iterations, padding)
        return True


    def get_encryption_key(self):
        key = load_binary_file(self.encryption_keyfile)
        if not key:
            key = os.environ.get('XPRA_ENCRYPTION_KEY')
        if not key:
            raise InitExit(1, "no encryption key")
        return key.strip("\n\r")

    def load_password(self):
        if self.password:
            return self.password
        if not self.password_file:
            return os.environ.get('XPRA_PASSWORD')
        filename = os.path.expanduser(self.password_file)
        password = load_binary_file(filename)
        netlog("password read from file %s is %s", self.password_file, "".join(["*" for _ in (password or "")]))
        return password

    def _process_hello(self, packet):
        if not self.password_sent and self.has_password():
            self.warn_and_quit(EXIT_NO_AUTHENTICATION, "the server did not request our password")
            return
        try:
            self.server_capabilities = typedict(packet[1])
            netlog("processing hello from server: %s", self.server_capabilities)
            self.server_connection_established()
        except Exception as e:
            netlog.info("error in hello packet", exc_info=True)
            self.warn_and_quit(EXIT_FAILURE, "error processing hello packet from server: %s" % e)

    def capsget(self, capabilities, key, default):
        v = capabilities.get(strtobytes(key), default)
        if sys.version >= '3' and type(v)==bytes:
            v = bytestostr(v)
        return v


    def server_connection_established(self):
        netlog("server_connection_established()")
        if not self.parse_version_capabilities():
            netlog("server_connection_established() failed version capabilities")
            return False
        if not self.parse_server_capabilities():
            netlog("server_connection_established() failed server capabilities")
            return False
        if not self.parse_network_capabilities():
            netlog("server_connection_established() failed network capabilities")
            return False
        if not self.parse_encryption_capabilities():
            netlog("server_connection_established() failed encryption capabilities")
            return False
        self.parse_printing_capabilities()
        self.parse_logging_capabilities()
        self.parse_file_transfer_caps(self.server_capabilities)
        #raise packet size if required:
        if self.file_transfer:
            self._protocol.max_packet_size = max(self._protocol.max_packet_size, self.file_size_limit*1024*1024)
        netlog("server_connection_established() adding authenticated packet handlers")
        self.init_authenticated_packet_handlers()
        return True

    def parse_logging_capabilities(self):
        pass

    def parse_printing_capabilities(self):
        printlog("parse_printing_capabilities() client printing support=%s", self.printing)
        if self.printing:
            server_printing = self.server_capabilities.boolget("printing")
            printlog("parse_printing_capabilities() server printing support=%s", server_printing)
            if server_printing:
                self.printer_attributes = self.server_capabilities.strlistget("printer.attributes", ["printer-info", "device-uri"])
                self.timeout_add(1000, self.init_printing)

    def init_printing(self):
        try:
            from xpra.platform.printing import init_printing
            printlog("init_printing=%s", init_printing)
            init_printing(self.send_printers)
        except Exception as e:
            printlog.error("Error initializing printing support:")
            printlog.error(" %s", e)
            self.printing = False
        try:
            self.do_send_printers()
        except Exception:
            printlog.error("Error sending the list of printers:", exc_info=True)
            self.printing = False
        printlog("init_printing() enabled=%s", self.printing)

    def cleanup_printing(self):
        printlog("cleanup_printing() printing=%s", self.printing)
        if not self.printing:
            return
        self.cancel_send_printers_timer()
        try:
            from xpra.platform.printing import cleanup_printing
            printlog("cleanup_printing=%s", cleanup_printing)
            cleanup_printing()
        except Exception:
            log.warn("failed to cleanup printing subsystem", exc_info=True)

    def send_printers(self, *args):
        printlog("send_printers%s timer=%s", args, self.send_printers_timer)
        #dbus can fire dozens of times for a single printer change
        #so we wait a bit and fire via a timer to try to batch things together:
        if self.send_printers_timer:
            return
        self.send_printers_timer = self.timeout_add(500, self.do_send_printers)

    def cancel_send_printers_timer(self):
        spt = self.send_printers_timer
        printlog("cancel_send_printers_timer() send_printers_timer=%s", spt)
        if spt:
            self.send_printers_timer = None
            self.source_remove(spt)

    def do_send_printers(self):
        try:
            self.send_printers_timer = None
            from xpra.platform.printing import get_printers, get_mimetypes
            printers = get_printers()
            printlog("do_send_printers() found printers=%s", printers)
            #remove xpra-forwarded printers to avoid loops and multi-forwards,
            #also ignore stopped printers
            #and only keep the attributes that the server cares about (self.printer_attributes)
            exported_printers = {}
            def used_attrs(d):
                #filter attributes so that we only compare things that are actually used
                if not d:
                    return d
                return dict((k,v) for k,v in d.items() if k in self.printer_attributes)
            for k,v in printers.items():
                device_uri = v.get("device-uri", "")
                if device_uri:
                    #this is cups specific.. oh well
                    printlog("do_send_printers() device-uri(%s)=%s", k, device_uri)
                    if device_uri.startswith("xpraforwarder"):
                        printlog("do_send_printers() skipping xpra forwarded printer=%s", k)
                        continue
                state = v.get("printer-state")
                #"3" if the destination is idle,
                #"4" if the destination is printing a job,
                #"5" if the destination is stopped.
                if state==5 and SKIP_STOPPED_PRINTERS:
                    printlog("do_send_printers() skipping stopped printer=%s", k)
                    continue
                attrs = used_attrs(v)
                #add mimetypes:
                attrs["mimetypes"] = get_mimetypes()
                exported_printers[k.encode("utf8")] = attrs
            if self.exported_printers is None:
                #not been sent yet, ensure we can use the dict below:
                self.exported_printers = {}
            elif exported_printers==self.exported_printers:
                printlog("do_send_printers() exported printers unchanged: %s", self.exported_printers)
                return
            #show summary of what has changed:
            added = [k for k in exported_printers.keys() if k not in self.exported_printers]
            if added:
                printlog("do_send_printers() new printers: %s", added)
            removed = [k for k in self.exported_printers.keys() if k not in exported_printers]
            if removed:
                printlog("do_send_printers() printers removed: %s", removed)
            modified = [k for k,v in exported_printers.items() if self.exported_printers.get(k)!=v and k not in added]
            if modified:
                printlog("do_send_printers() printers modified: %s", modified)
            printlog("do_send_printers() printers=%s", exported_printers.keys())
            printlog("do_send_printers() exported printers=%s", ", ".join(str(x) for x in exported_printers.keys()))
            self.exported_printers = exported_printers
            self.send("printers", self.exported_printers)
        except:
            printlog.error("do_send_printers()", exc_info=True)


    def parse_version_capabilities(self):
        c = self.server_capabilities
        self._remote_machine_id = c.strget("machine_id")
        self._remote_uuid = c.strget("uuid")
        self._remote_version = c.strget("build.version", c.strget("version"))
        self._remote_revision = c.strget("build.revision", c.strget("revision"))
        self._remote_platform = c.strget("platform")
        self._remote_platform_release = c.strget("platform.release")
        self._remote_platform_platform = c.strget("platform.platform")
        #linux distribution is a tuple of different types, ie: ('Linux Fedora' , 20, 'Heisenbug')
        pld = c.listget("platform.linux_distribution")
        if pld and len(pld)==3:
            def san(v):
                if type(v)==int:
                    return v
                return bytestostr(v)
            self._remote_platform_linux_distribution = [san(x) for x in pld]
        verr = version_compat_check(self._remote_version)
        if verr is not None:
            self.warn_and_quit(EXIT_INCOMPATIBLE_VERSION, "incompatible remote version '%s': %s" % (self._remote_version, verr))
            return False
        return True

    def parse_server_capabilities(self):
        return True

    def parse_network_capabilities(self):
        c = self.server_capabilities
        p = self._protocol
        if not p or not p.enable_encoder_from_caps(c):
            return False
        p.enable_compressor_from_caps(c)
        return True

    def parse_encryption_capabilities(self):
        c = self.server_capabilities
        p = self._protocol
        if not p:
            return False
        p.send_aliases = c.dictget("aliases", {})
        if self.encryption:
            #server uses a new cipher after second hello:
            key = self.get_encryption_key()
            assert key, "encryption key is missing"
            if not self.set_server_encryption(c, key):
                return False
        return True

    def _process_set_deflate(self, packet):
        #legacy, should not be used for anything
        pass

    def _process_startup_complete(self, packet):
        #can be received if we connect with "xpra stop" or other command line client
        #as the server is starting up
        pass


    def _process_gibberish(self, packet):
        (_, message, data) = packet
        p = self._protocol
        show_as_text = p and p.input_packetcount==0 and all(c in string.printable for c in bytestostr(data))
        if show_as_text:
            #looks like the first packet back is just text, print it:
            data = bytestostr(data)
            if data.find("Traceback "):
                for x in data.split("\n"):
                    netlog.warn(x.strip("\r"))
            else:
                netlog.warn("Failed to connect, received: %s", repr_ellipsized(data.strip("\n").strip("\r")))
        else:
            netlog.warn("Received uninterpretable nonsense: %s", message)
            netlog.warn(" packet no %i data: %s", p.input_packetcount, repr_ellipsized(data))
        self.quit(EXIT_PACKET_FAILURE)

    def _process_invalid(self, packet):
        (_, message, data) = packet
        netlog.info("Received invalid packet: %s", message)
        netlog(" data: %s", repr_ellipsized(data))
        self.quit(EXIT_PACKET_FAILURE)


    def process_packet(self, proto, packet):
        try:
            handler = None
            packet_type = packet[0]
            if packet_type!=int:
                packet_type = bytestostr(packet_type)
            handler = self._packet_handlers.get(packet_type)
            if handler:
                handler(packet)
                return
            handler = self._ui_packet_handlers.get(packet_type)
            if not handler:
                netlog.error("unknown packet type: %s", packet_type)
                return
            self.idle_add(handler, packet)
        except KeyboardInterrupt:
            raise
        except:
            netlog.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
