# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
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

from xpra.net.protocol import Protocol, get_network_caps, sanity_checks
from xpra.scripts.config import ENCRYPTION_CIPHERS
from xpra.version_util import version_compat_check, get_version_info, get_platform_info, local_version
from xpra.platform.features import GOT_PASSWORD_PROMPT_SUGGESTION
from xpra.platform.info import get_name
from xpra.os_util import get_hex_uuid, get_machine_id, get_user_uuid, load_binary_file, SIGNAMES, strtobytes, bytestostr
from xpra.util import typedict, updict, xor, repr_ellipsized, nonl, disconnect_is_an_error

try:
    import xpra.platform.printing
    assert xpra.platform.printing
    HAS_PRINTING = True
except:
    HAS_PRINTING = False

EXIT_OK = 0
EXIT_CONNECTION_LOST = 1
EXIT_TIMEOUT = 2
EXIT_PASSWORD_REQUIRED = 3
EXIT_PASSWORD_FILE_ERROR = 4
EXIT_INCOMPATIBLE_VERSION = 5
EXIT_ENCRYPTION = 6
EXIT_FAILURE = 7
EXIT_SSH_FAILURE = 8
EXIT_PACKET_FAILURE = 9
EXIT_MMAP_TOKEN_FAILURE = 10
EXIT_NO_AUTHENTICATION = 11
EXIT_UNSUPPORTED = 12
EXIT_REMOTE_ERROR = 13
EXIT_INTERNAL_ERROR = 14


EXTRA_TIMEOUT = 10
ALLOW_UNENCRYPTED_PASSWORDS = os.environ.get("XPRA_ALLOW_UNENCRYPTED_PASSWORDS", "0")=="1"
DETECT_LEAKS = os.environ.get("XPRA_DETECT_LEAKS", "0")=="1"
DELETE_PRINTER_FILE = os.environ.get("XPRA_DELETE_PRINTER_FILE", "1")=="1"


class XpraClientBase(object):
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
        #this may be called more than once,
        #skip doing internal init again:
        if not hasattr(self, "exit_code"):
            self.defaults_init()

    def defaults_init(self):
        #client state:
        self.exit_code = None
        self.exit_on_signal = False
        #connection attributes:
        self.compression_level = 0
        self.display = None
        self.username = None
        self.password_file = None
        self.password_sent = False
        self.encryption = None
        self.encryption_keyfile = None
        self.quality = -1
        self.min_quality = 0
        self.speed = 0
        self.min_speed = -1
        self.file_transfer = False
        self.printing = False
        self.printer_attributes = []
        self.send_printers_pending = False
        self.exported_printers = None
        self.open_command = None
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
        self.password_file = opts.password_file
        self.encryption = opts.encryption
        self.encryption_keyfile = opts.encryption_keyfile
        self.quality = opts.quality
        self.min_quality = opts.min_quality
        self.speed = opts.speed
        self.min_speed = opts.min_speed
        self.file_transfer = opts.file_transfer
        self.printing = opts.printing and self.file_transfer
        self.open_command = opts.open_command

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
            self.timeout_add(0, self.disconnect_and_quit, 128 + signum, "exit on signal %s" % SIGNAMES.get(signum, signum))
        signal.signal(signal.SIGINT, app_signal)
        signal.signal(signal.SIGTERM, app_signal)

    def signal_disconnect_and_quit(self, exit_code, reason):
        log("signal_disconnect_and_quit(%s, %s) exit_on_signal=%s", exit_code, reason, self.exit_on_signal)
        if not self.exit_on_signal:
            #if we get another signal, we'll try to exit without idle_add...
            self.exit_on_signal = True
            self.idle_add(self.disconnect_and_quit, exit_code, reason)
            return
        #warning: this will run cleanup code from the signal handler
        self.disconnect_and_quit(exit_code, reason)
        self.quit(exit_code)

    def disconnect_and_quit(self, exit_code, reason):
        #try to tell the server we're going, then quit
        log("disconnect_and_quit(%s, %s)", exit_code, reason)
        p = self._protocol
        if p is None or p._closed:
            self.quit(exit_code)
            return
        def do_quit():
            log("disconnect_and_quit: do_quit()")
            self.quit(exit_code)
        if p:
            p.flush_then_close(["disconnect", reason], done_callback=do_quit)
        self.timeout_add(1000, do_quit)


    def client_type(self):
        #overriden in subclasses!
        return "Python"

    def get_scheduler(self):
        raise NotImplementedError()

    def setup_connection(self, conn):
        log("setup_connection(%s)", conn)
        self._protocol = Protocol(self.get_scheduler(), conn, self.process_packet, self.next_packet)
        self._protocol.large_packets.append("keymap-changed")
        self._protocol.large_packets.append("server-settings")
        self._protocol.set_compression_level(self.compression_level)
        self._protocol.receive_aliases.update(self._aliases)
        self._protocol.enable_default_encoder()
        self._protocol.enable_default_compressor()
        self.have_more = self._protocol.source_has_more
        if conn.timeout>0:
            self.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)

    def init_packet_handlers(self):
        self._packet_handlers = {
            "hello"             : self._process_hello,
            "send-file"         : self._process_send_file,
            }
        self._ui_packet_handlers = {
            "challenge":                self._process_challenge,
            "disconnect":               self._process_disconnect,
            "set_deflate":              self._process_set_deflate,
            Protocol.CONNECTION_LOST:   self._process_connection_lost,
            Protocol.GIBBERISH:         self._process_gibberish,
            Protocol.INVALID:           self._process_invalid,
            }

    def init_authenticated_packet_handlers(self):
        #for subclasses to override
        pass


    def init_aliases(self):
        packet_types = list(self._packet_handlers.keys())
        packet_types += list(self._ui_packet_handlers.keys())
        i = 1
        for key in packet_types:
            self._aliases[i] = key
            self._reverse_aliases[key] = i
            i += 1

    def send_hello(self, challenge_response=None, client_salt=None):
        try:
            hello = self.make_hello_base()
            if (self.password_file or os.environ.get('XPRA_PASSWORD')) and not challenge_response:
                #avoid sending the full hello: tell the server we want
                #a packet challenge first
                hello["challenge"] = True
            else:
                hello.update(self.make_hello())
        except Exception as e:
            log.error("error preparing connection: %s", e, exc_info=True)
            self.quit(EXIT_INTERNAL_ERROR)
            return
        if challenge_response:
            assert self.password_file or os.environ.get('XPRA_PASSWORD')
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
        capabilities = get_network_caps()
        capabilities.update({
                "version"               : local_version,
                "encoding.generic"      : True,
                "namespace"             : True,
                "file-transfer"         : self.file_transfer,
                "printing"              : self.printing,
                "hostname"              : socket.gethostname(),
                "uuid"                  : self.uuid,
                "username"              : self.username,
                "name"                  : get_name(),
                "client_type"           : self.client_type(),
                "python.version"        : sys.version_info[:3],
                "compression_level"     : self.compression_level,
                })
        if self.display:
            capabilities["display"] = self.display
        def up(prefix, d):
            updict(capabilities, prefix, d)
        up("platform",  get_platform_info())
        up("build",     get_version_info())
        mid = get_machine_id()
        if mid:
            capabilities["machine_id"] = mid

        if self.encryption:
            assert self.encryption in ENCRYPTION_CIPHERS
            iv = get_hex_uuid()[:16]
            key_salt = get_hex_uuid()+get_hex_uuid()
            iterations = 1000
            capabilities.update({
                        "cipher"                       : self.encryption,
                        "cipher.iv"                    : iv,
                        "cipher.key_salt"              : key_salt,
                        "cipher.key_stretch_iterations": iterations,
                        })
            key = self.get_encryption_key()
            if key is None:
                self.warn_and_quit(EXIT_ENCRYPTION, "encryption key is missing")
                return
            self._protocol.set_cipher_in(self.encryption, iv, key, key_salt, iterations)
            log("encryption capabilities: %s", [(k,v) for k,v in capabilities.items() if k.startswith("cipher")])
        return capabilities

    def make_hello(self):
        capabilities = {
                        "randr_notify"        : False,        #only client.py cares about this
                        "windows"            : False,        #only client.py cares about this
                       }
        if self._reverse_aliases:
            capabilities["aliases"] = self._reverse_aliases
        return capabilities

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
        log("XpraClientBase.cleanup() protocol=%s", self._protocol)
        if self._protocol:
            self._protocol.close()
            self._protocol = None
        self.cleanup_printing()

    def glib_init(self):
        try:
            glib = import_glib()
            try:
                glib.threads_init()
            except AttributeError:
                #old versions of glib may not have this method
                pass
        except ImportError:
            pass

    def run(self):
        self._protocol.start()

    def quit(self, exit_code=0):
        raise Exception("override me!")

    def warn_and_quit(self, exit_code, warning):
        log.warn(warning)
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
            e = EXIT_OK
        self.warn_and_quit(e, "server requested disconnect: %s" % s)

    def _process_connection_lost(self, packet):
        p = self._protocol
        if p and p.input_raw_packetcount==0:
            props = p.get_info()
            c = props.get("compression", "unknown")
            e = props.get("encoder", "unknown")
            log.warn("failed to receive anything, not an xpra server?")
            log.warn("  could also be the wrong username, password or port")
            if c!="unknown" or e!="unknown":
                log.warn("  or maybe this server does not support '%s' compression or '%s' packet encoding?", c, e)
        self.warn_and_quit(EXIT_CONNECTION_LOST, "Connection lost")

    def _process_challenge(self, packet):
        log("processing challenge: %s", packet[1:])
        if not self.password_file and not os.environ.get('XPRA_PASSWORD'):
            self.warn_and_quit(EXIT_PASSWORD_REQUIRED, "server requires authentication, please provide a password")
            return
        password = self.load_password()
        if not password:
            self.warn_and_quit(EXIT_PASSWORD_FILE_ERROR, "failed to load password from file %s" % self.password_file)
            return
        salt = packet[1]
        if self.encryption:
            assert len(packet)>=3, "challenge does not contain encryption details to use for the response"
            server_cipher = packet[2]
            key = self.get_encryption_key()
            if key is None:
                self.warn_and_quit(EXIT_ENCRYPTION, "encryption key is missing")
                return
            if not self.set_server_encryption(server_cipher, key):
                return
        digest = "hmac"
        client_can_salt = len(packet)>=4
        client_salt = None
        if client_can_salt:
            #server supports client salt, and tells us which digest to use:
            digest = packet[3]
            client_salt = get_hex_uuid()+get_hex_uuid()
            #TODO: use some key stretching algorigthm? (meh)
            salt = xor(salt, client_salt)
        if digest=="hmac":
            import hmac
            challenge_response = hmac.HMAC(password, salt).hexdigest()
        elif digest=="xor":
            #don't send XORed password unencrypted:
            if not self._protocol.cipher_out and not ALLOW_UNENCRYPTED_PASSWORDS:
                self.warn_and_quit(EXIT_ENCRYPTION, "server requested digest %s, cowardly refusing to use it without encryption" % digest)
                return
            challenge_response = xor(password, salt)
        else:
            self.warn_and_quit(EXIT_PASSWORD_REQUIRED, "server requested an unsupported digest: %s" % digest)
            return
        if digest:
            log("%s(%s, %s)=%s", digest, password, salt, challenge_response)
        self.password_sent = True
        self.send_hello(challenge_response, client_salt)

    def set_server_encryption(self, capabilities, key):
        def get(key, default=None):
            return capabilities.get(strtobytes(key), default)
        cipher = get("cipher")
        cipher_iv = get("cipher.iv")
        key_salt = get("cipher.key_salt")
        iterations = get("cipher.key_stretch_iterations")
        if not cipher or not cipher_iv:
            self.warn_and_quit(EXIT_ENCRYPTION, "the server does not use or support encryption/password, cannot continue with %s cipher" % self.encryption)
            return False
        if cipher not in ENCRYPTION_CIPHERS:
            self.warn_and_quit(EXIT_ENCRYPTION, "unsupported server cipher: %s, allowed ciphers: %s" % (cipher, ", ".join(ENCRYPTION_CIPHERS)))
            return False
        self._protocol.set_cipher_out(cipher, cipher_iv, key, key_salt, iterations)
        return True


    def get_encryption_key(self):
        key = load_binary_file(self.encryption_keyfile)
        if not key:
            key = os.environ.get('XPRA_ENCRYPTION_KEY')
        if not key and self.password_file:
            key = load_binary_file(self.password_file)
            if key:
                log("used password file as encryption key")
        if not key:
            key = os.environ.get('XPRA_PASSWORD')
            if key:
                log("used XPRA_PASSWORD as encryption key")
        if key is None:
            raise Exception("no encryption key")
        return key.strip("\n\r")

    def load_password(self):
        if not self.password_file:
            return os.environ.get('XPRA_PASSWORD')
        filename = os.path.expanduser(self.password_file)
        password = load_binary_file(filename)
        if password is None:
            return None
        password = password.strip("\n\r")
        log("password read from file %s is %s", self.password_file, "".join(["*" for _ in password]))
        return password

    def _process_hello(self, packet):
        if not self.password_sent and (self.password_file or os.environ.get('XPRA_PASSWORD')):
            self.warn_and_quit(EXIT_NO_AUTHENTICATION, "the server did not request our password")
            return
        try:
            self.server_capabilities = typedict(packet[1])
            log("processing hello from server: %s", self.server_capabilities)
            self.server_connection_established()
        except Exception as e:
            log.info("error in hello packet", exc_info=True)
            self.warn_and_quit(EXIT_FAILURE, "error processing hello packet from server: %s" % e)

    def capsget(self, capabilities, key, default):
        v = capabilities.get(strtobytes(key), default)
        if sys.version >= '3' and type(v)==bytes:
            v = bytestostr(v)
        return v


    def server_connection_established(self):
        log("server_connection_established()")
        if not self.parse_version_capabilities():
            log("server_connection_established() failed version capabilities")
            return False
        if not self.parse_server_capabilities():
            log("server_connection_established() failed server capabilities")
            return False
        if not self.parse_network_capabilities():
            log("server_connection_established() failed network capabilities")
            return False
        if not self.parse_encryption_capabilities():
            log("server_connection_established() failed encryption capabilities")
            return False
        self.parse_printing_capabilities()
        log("server_connection_established() adding authenticated packet handlers")
        self.init_authenticated_packet_handlers()
        return True


    def parse_printing_capabilities(self):
        if self.printing:
            if self.server_capabilities.boolget("printing"):
                self.printer_attributes = self.server_capabilities.strlistget("printer.attributes", ["printer-info", "device-uri"])
                self.timeout_add(1000, self.init_printing)

    def init_printing(self):
        if not HAS_PRINTING:
            return
        try:
            from xpra.platform.printing import init_printing
            printlog("init_printing=%s", init_printing)
            init_printing(self.send_printers)
            self.do_send_printers()
        except Exception:
            log.warn("failed to send printers", exc_info=True)

    def cleanup_printing(self):
        if not HAS_PRINTING:
            return
        try:
            from xpra.platform.printing import cleanup_printing
            printlog("cleanup_printing=%s", cleanup_printing)
            cleanup_printing()
        except Exception:
            log.warn("failed to cleanup printing subsystem", exc_info=True)

    def send_printers(self, *args):
        #dbus can fire dozens of times for a single printer change
        #so we wait a bit and fire via a timer to try to batch things together:
        if self.send_printers_pending:
            return
        self.send_printers_pending = True
        self.timeout_add(500, self.do_send_printers)

    def do_send_printers(self):
        try:
            self.send_printers_pending = False
            from xpra.platform.printing import get_printers
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
                if state==5:
                    printlog("do_send_printers() skipping stopped printer=%s", k)
                    continue
                exported_printers[k.encode("utf8")] = used_attrs(v)
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
            log.error("do_send_printers()", exc_info=True)


    def parse_version_capabilities(self):
        c = self.server_capabilities
        self._remote_machine_id = c.strget("machine_id")
        self._remote_uuid = c.strget("uuid")
        self._remote_version = c.strget("version")
        self._remote_version = c.strget("build.version", self._remote_version)
        self._remote_revision = c.strget("revision")
        self._remote_revision = c.strget("build.revision", self._remote_revision)
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
        if not self._protocol.enable_encoder_from_caps(c):
            return False
        self._protocol.enable_compressor_from_caps(c)
        return True

    def parse_encryption_capabilities(self):
        c = self.server_capabilities
        if self.encryption:
            #server uses a new cipher after second hello:
            key = self.get_encryption_key()
            assert key, "encryption key is missing"
            if not self.set_server_encryption(c, key):
                return False
        self._protocol.send_aliases = c.dictget("aliases", {})
        return True

    def _process_set_deflate(self, packet):
        #legacy, should not be used for anything
        pass


    def _process_send_file(self, packet):
        #send-file basefilename, printit, openit, filesize, 0, data)
        from xpra.platform.features import DOWNLOAD_PATH
        basefilename, mimetype, printit, openit, filesize, file_data, options = packet[1:11]
        filelog("received file: %s", [basefilename, mimetype, printit, openit, filesize, "%s bytes" % len(file_data), options])
        options = typedict(options)
        if printit:
            assert self.printing
        else:
            assert self.file_transfer
        assert filesize>0 and file_data
        #check digest if present:
        digest = options.get("sha1")
        if digest:
            import hashlib
            u = hashlib.sha1()
            u.update(file_data)
            filelog("sha1 digest: %s - expected: %s", u.hexdigest(), digest)
            assert digest==u.hexdigest(), "invalid file digest %s (expected %s)" % (u.hexdigest(), digest)

        #make sure we use a filename that does not exist already:
        wanted_filename = os.path.abspath(os.path.join(os.path.expanduser(DOWNLOAD_PATH), os.path.basename(basefilename)))
        EXTS = {"application/postscript"    : "ps",
                "application/pdf"           : "pdf",
                }
        ext = EXTS.get(mimetype)
        if ext:
            #on some platforms (win32),
            #we want to force an extension
            #so that the file manager can display them properly when you double-click on them
            if not wanted_filename.endswith("."+ext):
                wanted_filename += "."+ext
        filename = wanted_filename
        base = 0
        while os.path.exists(filename):
            filelog("cannot save file as %s: file already exists", filename)
            root, ext = os.path.splitext(wanted_filename)
            base += 1
            filename = root+("-%s" % base)+ext
        flags = os.O_CREAT | os.O_RDWR | os.O_EXCL
        try:
            flags |= os.O_BINARY                #@UndefinedVariable (win32 only)
        except:
            pass
        fd = os.open(filename, flags)
        try:
            os.write(fd, file_data)
        finally:
            os.close(fd)
        filelog.info("downloaded %s bytes to %s file %s", filesize, mimetype, filename)
        if printit:
            printer = options.strget("printer")
            title   = options.strget("title")
            print_options = options.dictget("options")
            #TODO: how do we print multiple copies?
            #copies = options.intget("copies")
            #whitelist of options we can forward:
            safe_print_options = dict((k,v) for k,v in print_options.items() if k in ("PageSize", "Resolution"))
            printlog("safe print options(%s) = %s", options, safe_print_options)
            self._print_file(filename, printer, title, safe_print_options)
            return
        elif openit:
            #run the command in a new thread
            #so we can block waiting for the subprocess to exit
            #(ensures that we do reap the process)
            import thread
            thread.start_new_thread(self._open_file, (filename, ))

    def _print_file(self, filename, printer, title, options):
        import time
        from xpra.platform.printing import print_files, printing_finished
        job = print_files(printer, [filename], title, options)
        printlog("printing %s, job=%s", filename, job)
        if not job:
            return
        start = time.time()
        def delfile():
            if not DELETE_PRINTER_FILE:
                return
            try:
                os.unlink(filename)
            except:
                printlog("failed to delete print job file '%s'", filename)
            return False
        def check_printing_finished():
            done = printing_finished(job)
            printlog("printing_finished(%s)=%s", job, done)
            if done:
                delfile()
                return False
            if time.time()-start>10*60:
                printlog.warn("print job %s timed out", job)
                delfile()
                return False
            return True #try again..
        if check_printing_finished():
            self.timeout_add(10000, check_printing_finished)

    def _open_file(self, filename):
        import subprocess
        PIPE = subprocess.PIPE
        process = subprocess.Popen([self.open_command, filename], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        out, err = process.communicate()
        r = process.wait()
        filelog.info("opened file %s with %s, exit code: %s", filename, self.open_command, r)
        if r!=0:
            l = filelog.warn
        else:
            l = filelog
        if out:
            l("stdout=%s", nonl(out)[:512])
        if err:
            l("stderr=%s", nonl(err)[:512])


    def _process_gibberish(self, packet):
        (_, message, data) = packet
        p = self._protocol
        show_as_text = p and p.input_packetcount==0 and all(c in string.printable for c in bytestostr(data))
        if show_as_text:
            #looks like the first packet back is just text, print it:
            data = bytestostr(data)
            if data.find("Traceback "):
                for x in data.split("\n"):
                    log.warn(x.strip("\r"))
            else:
                log.warn("Failed to connect, received: %s", repr_ellipsized(data.strip("\n").strip("\r")))
        else:
            log.warn("Received uninterpretable nonsense: %s", message)
            log.warn(" packet no %i data: %s", p.input_packetcount, repr_ellipsized(data))
        if str(data).find("assword")>0:
            self.warn_and_quit(EXIT_SSH_FAILURE,
                              "Your ssh program appears to be asking for a password."
                             + GOT_PASSWORD_PROMPT_SUGGESTION)
        elif str(data).find("login")>=0:
            self.warn_and_quit(EXIT_SSH_FAILURE,
                             "Your ssh program appears to be asking for a username.\n"
                             "Perhaps try using something like 'ssh:USER@host:display'?")
        else:
            self.quit(EXIT_PACKET_FAILURE)

    def _process_invalid(self, packet):
        (_, message, data) = packet
        log.info("Received invalid packet: %s", message)
        log(" data: %s", repr_ellipsized(data))
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
                log.error("unknown packet type: %s", packet_type)
                return
            self.idle_add(handler, packet)
        except KeyboardInterrupt:
            raise
        except:
            log.error("Unhandled error while processing a '%s' packet from peer using %s", packet_type, handler, exc_info=True)
