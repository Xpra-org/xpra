#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import subprocess
import os.path
import time

from wimpiggy.log import Logger
log = Logger()
HOME = os.path.expanduser("~/")

def getoutput(cmd, env=None):
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, close_fds=True)
    except Exception, e:
        print("error running %s: %s" % (cmd, e))
        raise e
    (out,err) = process.communicate()
    code = process.poll()
    if code!=0:
        raise Exception("command '%s' returned error code %s, out=%s, err=%s" % (cmd, code, out, err))
    return out


#You will probably need to change those:
IP = "127.0.0.1"            #this is your IP
PORT = 10000                #the port to test on
DISPLAY_NO = 10             #the test DISPLAY no to use
XORG_CONFIG="%s/xorg.conf" % HOME
XORG_LOG = "%s/Xorg.%s.log" % (HOME, DISPLAY_NO)
START_SERVER = True         #if False, you are responsible for starting it
                            #and the data will not be available

SETTLE_TIME = 3             #how long to wait before we start measuring
MEASURE_TIME = 120          #run for N seconds
SERVER_SETTLE_TIME = 3      #how long we wait for the server to start
DEFAULT_TEST_COMMAND_SETTLE_TIME = 1    #how long we wait after starting the test command
                            #this is the default value, some tests may override this below

TEST_XPRA = True
TEST_VNC = True
USE_IPTABLES = True         #this requires iptables to be setup so we can use it for accounting

LIMIT_TESTS = 2
LIMIT_TESTS = 99999         #to limit the total number of tests being run
MAX_ERRORS = 100            #allow this many tests to cause errors before aborting

#some commands (games especially) may need longer to startup:
TEST_COMMAND_SETTLE_TIME = {}

NO_SHAPING = (0, 0, 0)
TRICKLE_SHAPING_OPTIONS = [NO_SHAPING]
TRICKLE_SHAPING_OPTIONS = [NO_SHAPING, (1024, 1024, 20)]
TRICKLE_SHAPING_OPTIONS = [(1024, 1024, 20), (128, 32, 40), (0, 0, 0)]
TRICKLE_SHAPING_OPTIONS = [NO_SHAPING, (1024, 256, 20), (1024, 256, 300), (128, 32, 100), (32, 8, 200)]
TRICKLE_SHAPING_OPTIONS = [NO_SHAPING, (1024, 256, 20), (256, 64, 50), (128, 32, 100), (32, 8, 200)]

#tools we use:
IPTABLES_CMD = ["sudo", "/usr/sbin/iptables"]
TRICKLE_BIN = "/usr/bin/trickle"
TCBENCH = "/opt/VirtualGL/bin/tcbench"
TCBENCH_LOG = "./tcbench.log"
XORG_BIN = "/usr/local/bin/Xorg"

#the glx tests:
GLX_SPHERES = ["/opt/VirtualGL/bin/glxspheres64"]
GLX_GEARS = ["/usr/bin/glxgears", "-geometry", "1240x900"]
GLX_TESTS = [GLX_SPHERES, GLX_GEARS]

#the plain X11 tests:
X11_PERF = ["/usr/bin/x11perf", "-resize", "-all"]
XTERM_TEST = ["/usr/bin/xterm", "-geometry", "160x60", "-e", "while true; do dmesg; done"]
FAKE_CONSOLE_USER_TEST = ["/usr/bin/xterm", "-geometry", "160x60", "-e", "PYTHONPATH=`pwd` ./tests/xpra/simulate_console_user.py"]
GTKPERF_TEST = "while true; do gtkperf -a; done"
X11_TESTS = [X11_PERF, XTERM_TEST, FAKE_CONSOLE_USER_TEST, GTKPERF_TEST]

#the screensaver tests:
XSCREENSAVERS_PATH = "/usr/libexec/xscreensaver"
def screensaver(x):
    return  ["%s/%s" % (XSCREENSAVERS_PATH, x)]
ALL_SCREENSAVER_TESTS = [screensaver(x) for x in
                            ["rss-glx-lattice", "rss-glx-plasma", "deluxe", "eruption", "memscroller", "moebiusgears", "polytopes"]
                         ]
SOME_SCREENSAVER_TESTS = [screensaver(x) for x in
                            ["memscroller", "eruption", "xmatrix"]
                          ]
SOME_SCREENSAVER_TESTS = [screensaver(x) for x in
                            ["memscroller", "moebiusgears", "polytopes", "rss-glx-lattice"]
                          ]

#games tests:
#for more info, see here: http://dri.freedesktop.org/wiki/Benchmarking
NEXUIZ_TEST = ["/usr/bin/nexuiz-glx", "-benchmark", "demos/demo1", "-nosound"]
XONOTIC_TEST = ["/opt/Xonotic/xonotic-linux64-glx", "-basedir", "/opt/Xonotic", "-benchmark", "demos/the-big-keybench"]
TEST_COMMAND_SETTLE_TIME[NEXUIZ_TEST[0]] = 10
TEST_COMMAND_SETTLE_TIME[XONOTIC_TEST[0]] = 20
GAMES_TESTS = [NEXUIZ_TEST, XONOTIC_TEST]

#our selection:
TEST_CANDIDATES = [screensaver("deluxe")]
TEST_CANDIDATES = X11_TESTS + SOME_SCREENSAVER_TESTS + GAMES_TESTS
TEST_CANDIDATES = GLX_TESTS + X11_TESTS + ALL_SCREENSAVER_TESTS + GAMES_TESTS
TEST_CANDIDATES = GLX_TESTS + X11_TESTS + ALL_SCREENSAVER_TESTS


#now we filter all the test commands and only keep the valid ones:
print("Checking for test commands:")
X11_TEST_COMMANDS = []
for x in TEST_CANDIDATES:
    if x!=GTKPERF_TEST and not os.path.exists(x[0]):
        print("* WARNING: cannot find %s - removed from tests" % str(x))
    else:
        print("* adding test: %s" % str(x))
        X11_TEST_COMMANDS.append(x)
TEST_NAMES = {GTKPERF_TEST: "gtkperf"}


XVNC_BIN = "/usr/bin/Xvnc"
XVNC_SERVER_START_COMMAND = [XVNC_BIN, "--rfbport=%s" % PORT,
                   "+extension", "GLX",
                   "--SecurityTypes=None",
                   "--SendCutText=0", "--AcceptCutText=0", "--AcceptPointerEvents=0", "--AcceptKeyEvents=0",
                   "-screen", "0", "1240x900x24",
                   ":%s" % DISPLAY_NO]
XVNC_SERVER_STOP_COMMANDS = [["killall Xvnc"]]     #stopped via kill - beware, this will kill *all* Xvnc sessions!
VNCVIEWER_BIN = "/usr/bin/vncviewer"
VNC_ENCODINGS = ["Tight", "ZRLE", "hextile", "raw", "auto"]
VNC_ENCODINGS = ["auto"]
VNC_ZLIB_OPTIONS = [-1, 3, 6, 9]
VNC_ZLIB_OPTIONS = [-1, 9]
VNC_COMPRESSION_OPTIONS = [0, 3, 8, 9]
VNC_COMPRESSION_OPTIONS = [0, 3]
VNC_JPEG_OPTIONS = [-1, 0, 8]
VNC_JPEG_OPTIONS = [-1, 4]



XPRA_BIN = "/usr/bin/xpra"
XPRA_VERSION = getoutput([XPRA_BIN, "--version"]).replace("\n", "").replace("\r", "").split()[1].replace("v0.", "0.")
XPRA_VERSION_NO = [int(x) for x in XPRA_VERSION.split(".")]
XPRA_SERVER_STOP_COMMANDS = [
                             [XPRA_BIN, "stop", ":%s" % DISPLAY_NO],
                             "ps -ef | grep -i [X]org-for-Xpra-:%s | awk '{print $2}' | xargs kill" % DISPLAY_NO
                             ]
XPRA_INFO_COMMAND = [XPRA_BIN, "info", "tcp:%s:%s" % (IP, PORT)]
XPRA_USE_XDUMMY = True
XPRA_QUALITY_OPTIONS = [40, 90]
XPRA_QUALITY_OPTIONS = [80]
XPRA_QUALITY_OPTIONS = [10, 40, 80, 90]
XPRA_COMPRESSION_OPTIONS = [0, 3, 9]
XPRA_COMPRESSION_OPTIONS = [0, 3]
XPRA_COMPRESSION_OPTIONS = [None]
XPRA_CONNECT_OPTIONS = [("ssh", None), ("tcp", None), ("unix", None)]
XPRA_CONNECT_OPTIONS = [("tcp", None)]
if XPRA_VERSION_NO>=[0, 7]:
    XPRA_CONNECT_OPTIONS.append(("tcp", "AES"))
print ("XPRA_VERSION_NO=%s" % XPRA_VERSION_NO)
XPRA_TEST_ENCODINGS = ["png", "x264", "mmap"]
XPRA_TEST_ENCODINGS = ["png", "jpeg", "x264", "vpx", "mmap"]
XPRA_TEST_ENCODINGS = ["png", "rgb24", "jpeg", "x264", "vpx", "mmap"]
if XPRA_VERSION_NO>=[0, 7]:
    XPRA_TEST_ENCODINGS.append("webp")
XPRA_ENCODING_QUALITY_OPTIONS = {"jpeg" : XPRA_QUALITY_OPTIONS,
                                 "webp" : XPRA_QUALITY_OPTIONS,
                                 "x264" : XPRA_QUALITY_OPTIONS+[-1],
                                 }

password_filename = "./test-password.txt"
try:
    import uuid
    f = open(password_filename, 'wb')
    f.write(uuid.uuid4().hex)
finally:
    f.close()


check = [TRICKLE_BIN]
if TEST_XPRA:
    check.append(XPRA_BIN)
if TEST_VNC:
    check.append(XVNC_BIN)
    check.append(VNCVIEWER_BIN)
for x in check:
    if not os.path.exists(x):
        raise Exception("cannot run tests: %s is missing!" % x)

def is_process_alive(process, grace=0):
    i = 0
    while i<grace:
        if not process or process.poll() is not None:
            return  False
        time.sleep(1)
        i += 1
    return process and process.poll() is None

def try_to_stop(process, grace=0):
    if is_process_alive(process, grace):
        try:
            process.terminate()
        except Exception, e:
            print("could not stop process %s: %s" % (process, e))
def try_to_kill(process, grace=0):
    if is_process_alive(process, grace):
        try:
            process.kill()
        except Exception, e:
            print("could not stop process %s: %s" % (process, e))

def find_matching_lines(out, pattern):
    lines = []
    for line in out.splitlines():
        if line.find(pattern)>=0:
            lines.append(line)
    return  lines

def getoutput_lines(cmd, pattern, setup_info):
    out = getoutput(cmd)
    return  find_matching_lines(out, pattern)

def getoutput_line(cmd, pattern, setup_info):
    lines = getoutput_lines(cmd, pattern, setup_info)
    assert len(lines)==1, "expected 1 line matching '%s' from %s but found %s" % (pattern, cmd, len(lines))
    return  lines[0]

def get_cpu_info():
    lines = getoutput_lines(["cat", "/proc/cpuinfo"], "model name", "cannot find cpu info")
    assert len(lines)>0, "coult not find 'model name' in '/proc/cpuinfo'"
    cpu0 = lines[0]
    n = len(lines)
    for x in lines[1:]:
        if x!=cpu0:
            return " - ".join(lines), n
    cpu_name = cpu0.split(":")[1]
    for o,r in [("Processor", ""), ("(R)", ""), ("(TM)", ""), ("(tm)", ""), ("  ", " ")]:
        while cpu_name.find(o)>=0:
            cpu_name = cpu_name.replace(o, r)
    cpu_info = "%sx %s" % (len(lines), cpu_name.strip())
    print("CPU_INFO=%s" % cpu_info)
    return  cpu_info, n

XORG_VERSION = getoutput_line([XORG_BIN, "-version"], "X.Org X Server", "Cannot detect Xorg server version")
print("XORG_VERSION=%s" % XORG_VERSION)
CPU_INFO, N_CPUS = get_cpu_info()
KERNEL_VERSION = getoutput(["uname", "-r"]).replace("\n", "").replace("\r", "")
PAGE_SIZE = int(getoutput(["getconf", "PAGESIZE"]).replace("\n", "").replace("\r", ""))
PLATFORM = getoutput(["uname", "-p"]).replace("\n", "").replace("\r", "")
OPENGL_INFO = getoutput_line(["glxinfo"], "OpenGL renderer string", "Cannot detect OpenGL renderer string").split("OpenGL renderer string:")[1].strip()

import pygtk
pygtk.require("2.0")
import gtk                                      #@UnusedImport
from gtk import gdk                             #@UnusedImport
SCREEN_SIZE = gdk.get_default_root_window().get_size()
print("screen size=%s" % str(SCREEN_SIZE))

#detect Xvnc version:
XVNC_VERSION = ""
VNCVIEWER_VERSION = ""
DETECT_XVNC_VERSION_CMD = [XVNC_BIN, "--help"]
DETECT_VNCVIEWER_VERSION_CMD = [VNCVIEWER_BIN, "--help"]
def get_stderr(command):
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _,err = process.communicate()
        return err
    except Exception, e:
        print("error running %s: %s" % (DETECT_XVNC_VERSION_CMD, e))

err = get_stderr(DETECT_XVNC_VERSION_CMD)
if err:
    v_lines = find_matching_lines(err, "Xvnc TigerVNC")
    if len(v_lines)==1:
        XVNC_VERSION = " ".join(v_lines[0].split()[:3])
print ("XVNC_VERSION=%s" % XVNC_VERSION)
err = get_stderr(DETECT_VNCVIEWER_VERSION_CMD)
if err:
    v_lines = find_matching_lines(err, "TigerVNC Viewer for X version")
    if len(v_lines)==1:
        VNCVIEWER_VERSION = "TigerVNC Viewer %s" % (v_lines[0].split()[5])
print ("VNCVIEWER_VERSION=%s" % VNCVIEWER_VERSION)

SVN_VERSION = getoutput(["svnversion", "-n"])

WINDOW_MANAGER = os.environ.get("DESKTOP_SESSION", "unknown")

def clean_sys_state():
    #clear the caches
    cmd = ["echo", "3", ">", "/proc/sys/vm/drop_caches"]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.wait()==0, "failed to run %s" % str(cmd)

def zero_iptables():
    if not USE_IPTABLES:
        return
    cmds = [IPTABLES_CMD+['-Z', 'INPUT'], IPTABLES_CMD+['-Z', 'OUTPUT']]
    for cmd in cmds:
        getoutput(cmd)
        #out = getoutput(cmd)
        #print("output(%s)=%s" % (cmd, out))

def update_proc_stat():
    proc_stat = open("/proc/stat", "rU")
    time_total = 0
    for line in proc_stat:
        values = line.split()
        if values[0]=="cpu":
            time_total = sum([int(x) for x in values[1:]])
            #print("time_total=%s" % time_total)
            break
    proc_stat.close()
    return time_total

def update_pidstat(pid):
    stat_file = open("/proc/%s/stat" % pid, "rU")
    data = stat_file.read()
    stat_file.close()
    pid_stat = data.split()
    #print("update_pidstat(%s): %s" % (pid, pid_stat))
    return pid_stat

def compute_stat(time_total_diff, old_pid_stat, new_pid_stat):
    #found help here:
    #http://stackoverflow.com/questions/1420426/calculating-cpu-usage-of-a-process-in-linux
    old_utime = int(old_pid_stat[13])
    old_stime = int(old_pid_stat[14])
    new_utime = int(new_pid_stat[13])
    new_stime = int(new_pid_stat[14])
    #normalize to 100% (single process) by multiplying by number of CPUs:
    user_pct = int(N_CPUS * 1000 * (new_utime - old_utime) / time_total_diff)/10.0
    sys_pct = int(N_CPUS * 1000 * (new_stime - old_stime) / time_total_diff)/10.0
    nthreads = int((int(old_pid_stat[19])+int(new_pid_stat[19]))/2)
    vsize = int(max(int(old_pid_stat[22]), int(new_pid_stat[22]))/1024/1024)
    rss = int(max(int(old_pid_stat[23]), int(new_pid_stat[23]))*PAGE_SIZE/1024/1024)
    return [user_pct, sys_pct, nthreads, vsize, rss]

def getiptables_line(chain, pattern, setup_info):
    cmd = IPTABLES_CMD + ["-vnL", chain]
    line = getoutput_line(cmd, pattern, setup_info)
    if not line:
        raise Exception("no line found matching %s, make sure you have a rule like: %s" % (pattern, setup_info))
    return line

def parse_ipt(chain, pattern, setup_info):
    if not USE_IPTABLES:
        return  0, 0
    line = getiptables_line(chain, pattern, setup_info)
    parts = line.split()
    assert len(parts)>2
    def parse_num(part):
        U = 1024
        m = {"K":U, "M":U**2, "G":U**3}.get(part[-1], 1)
        num = "".join([x for x in part if x in "0123456789"])
        return int(num)*m/MEASURE_TIME
    return parse_num(parts[0]), parse_num(parts[1])

def get_iptables_INPUT_count():
    setup = "iptables -I INPUT -p tcp --dport %s -j ACCEPT" % PORT
    return  parse_ipt("INPUT", "tcp dpt:%s" % PORT, setup)

def get_iptables_OUTPUT_count():
    setup = "iptables -I OUTPUT -p tcp --sport %s -j ACCEPT" % PORT
    return  parse_ipt("OUTPUT", "tcp spt:%s" % PORT, setup)

def measure_client(server_pid, name, cmd, get_stats_cb):
    print("starting client: %s" % cmd)
    try:
        client_process = subprocess.Popen(cmd)
        #give it time to settle down:
        time.sleep(SETTLE_TIME)
        code = client_process.poll()
        assert code is None, "client failed to start, return code is %s" % code
        #clear counters
        initial_stats = get_stats_cb()
        zero_iptables()
        old_time_total = update_proc_stat()
        old_pid_stat = update_pidstat(client_process.pid)
        if server_pid>0:
            old_server_pid_stat = update_pidstat(server_pid)
        #we start measuring
        time.sleep(MEASURE_TIME)
        code = client_process.poll()
        assert code is None, "client crashed, return code is %s" % code
        #stop the counters
        new_time_total = update_proc_stat()
        new_pid_stat = update_pidstat(client_process.pid)
        if server_pid>0:
            new_server_pid_stat = update_pidstat(server_pid)
        ni,isize = get_iptables_INPUT_count()
        no,osize = get_iptables_OUTPUT_count()
        stats = get_stats_cb(initial_stats)
        #now collect the data
        client_process_data = compute_stat(new_time_total-old_time_total, old_pid_stat, new_pid_stat)
        if server_pid>0:
            server_process_data = compute_stat(new_time_total-old_time_total, old_server_pid_stat, new_server_pid_stat)
        else:
            server_process_data = []
        print("process_data (client/server): %s / %s" % (client_process_data, server_process_data))
        print("input/output on tcp port %s: %s / %s packets, %s / %s KBytes" % (PORT, ni, no, isize, osize))
        return [ni, isize, no, osize] + stats + client_process_data + server_process_data
    finally:
        #stop the process
        if client_process and client_process.poll() is None:
            try_to_stop(client_process)
            try_to_kill(client_process, 5)
            code = client_process.poll()
            assert code is not None, "failed to stop client!"

def with_server(start_server_command, stop_server_commands, in_tests, get_stats_cb):
    tests = in_tests[:LIMIT_TESTS]
    print("going to run %s tests: %s" % (len(tests), [x[0] for x in tests]))
    print("ETA: %s minutes" % int((SERVER_SETTLE_TIME+DEFAULT_TEST_COMMAND_SETTLE_TIME+SETTLE_TIME+MEASURE_TIME+1)*len(tests)/60))

    server_process = None
    test_command_process = None
    env = os.environ.copy()
    env["DISPLAY"] = ":%s" % DISPLAY_NO
    errors = 0
    results = []
    count = 0
    for name, tech_name, server_version, client_version, encoding, compression, encryption, ssh, (down,up,latency), test_command, client_cmd in tests:
        try:
            print("**************************************************************")
            count += 1
            test_command_settle_time = TEST_COMMAND_SETTLE_TIME.get(test_command[0], DEFAULT_TEST_COMMAND_SETTLE_TIME)
            eta = int((SERVER_SETTLE_TIME+test_command_settle_time+SETTLE_TIME+MEASURE_TIME+1)*(len(tests)-count)/60)
            print("%s/%s: %s            ETA=%s minutes" % (count, len(tests), name, eta))
            test_command_process = None
            try:
                clean_sys_state()
                #start the server:
                if START_SERVER:
                    print("starting server: %s" % str(start_server_command))
                    server_process = subprocess.Popen(start_server_command, stdin=None)
                    #give it time to settle down:
                    time.sleep(SERVER_SETTLE_TIME)
                    server_pid = server_process.pid
                    code = server_process.poll()
                    assert code is None, "server failed to start, return code is %s, please ensure that you can run the server command line above and that a server does not already exist on that port or DISPLAY" % code
                else:
                    server_pid = 0

                try:
                    #start the test command:
                    print("starting test command: %s, settle time=%s" % (str(test_command), test_command_settle_time))
                    test_command_process = subprocess.Popen(test_command, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, shell=type(test_command)==str)
                    time.sleep(test_command_settle_time)
                    code = test_command_process.poll()
                    assert code is None, "test command %s failed to start: exit code is %s" % (test_command, code)

                    #run the client test
                    result = [name, tech_name, server_version, client_version, " ".join(sys.argv[1:]), SVN_VERSION]
                    result += [encoding, get_command_name(test_command)]
                    result += [MEASURE_TIME, time.time(), CPU_INFO, PLATFORM, KERNEL_VERSION, XORG_VERSION, OPENGL_INFO, WINDOW_MANAGER]
                    result += ["%sx%s" % gdk.get_default_root_window().get_size()]
                    result += [compression, encryption, ssh, down, up, latency]
                    result += measure_client(server_pid, name, client_cmd, get_stats_cb)
                    results.append(result)
                except Exception, e:
                    import traceback
                    traceback.print_exc()
                    errors += 1
                    print("error during client command run for %s: %s" % (name, e))
                    if errors>MAX_ERRORS:
                        print("too many errors, aborting tests")
                        break
            finally:
                if test_command_process:
                    print("stopping '%s' with pid=%s" % (test_command, test_command_process.pid))
                    try_to_stop(test_command_process)
                    try_to_kill(test_command_process, 2)
                if START_SERVER:
                    try_to_stop(server_process)
                    time.sleep(2)
                    for s in stop_server_commands:
                        print("stopping server with: %s" % (s))
                        try:
                            stop_process = subprocess.Popen(s, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
                            stop_process.wait()
                        except Exception, e:
                            print("error: %s" % e)
                    try_to_kill(server_process, 5)
                time.sleep(1)
        except KeyboardInterrupt, e:
            print("caught %s: stopping this series of tests" % e)
            break
    return results


def trickle_command(down, up, latency):
    if down<=0 and up<=0 and latency<=0:
        return  []
    cmd = [TRICKLE_BIN, "-s"]
    if down>0:
        cmd += ["-d", str(down)]
    if up>0:
        cmd += ["-u", str(up)]
    if latency>0:
        cmd += ["-L", str(latency)]
    return cmd

def trickle_str(down, up, latency):
    if down<=0 and up<=0 and latency<=0:
        return  "unthrottled"
    s = "/".join(str(x) for x in [down,up,latency])
    return "throttled:%s" % s

def get_command_name(command_arg):
    try:
        name = TEST_NAMES.get(command_arg)
        if name:
            return  name
    except:
        pass
    if type(command_arg)==list:
        c = command_arg[0]              #["/usr/bin/xterm", "blah"] -> "/usr/bin/xterm"
    else:
        c = command_arg.split(" ")[0]   #"/usr/bin/xterm -e blah" -> "/usr/bin/xterm"
    assert type(c)==str
    return c.split("/")[-1]             #/usr/bin/xterm -> xterm

def get_stats_headers():
    #the stats that are returned by get_xpra_stats or get_vnc_stats
    return  ["Regions/s", "Pixels/s Sent", "Encoding Pixels/s", "Decoding Pixels/s",
             "Min Batch Delay (ms)", "Max Batch Delay (ms)", "Avg Batch Delay (ms)",
             "Application packets in/s", "Application bytes in/s", "Application packets out/s", "Application bytes out/s", "mmap bytes/s",
             "Min Client Latency (ms)", "Max Client Latency (ms)", "Avg Client Latency (ms)",
             "Min Client Ping Latency (ms)", "Max Client Ping Latency (ms)", "Avg Client Ping Latency (ms)",
             "Min Server Ping Latency (ms)", "Max Server Ping Latency (ms)", "Avg Server Ping Latency (ms)",
             "Min Damage Latency (ms)", "Max Damage Latency (ms)", "Avg Damage Latency (ms)",
             ]

def no_stats(last_record=None):
    return  ["" for _ in xrange(24)]

def xpra_get_stats(last_record=None):
    if XPRA_VERSION_NO<[0, 3]:
        return  no_stats(last_record)
    out = getoutput(XPRA_INFO_COMMAND)
    if not out:
        return  no_stats(last_record)
    d = {}
    for line in out.splitlines():
        parts = line.split("=")
        if len(parts)==2:
            d[parts[0]] = parts[1]
    last_input_packetcount = 0
    last_output_packetcount = 0
    last_mmap_bytes = 0
    last_input_bytecount = 0
    last_output_bytecount = 0
    if last_record:
        index = 7
        last_input_packetcount = last_record[index]
        last_input_bytecount = last_record[index+1]
        last_output_packetcount = last_record[index+2]
        last_output_bytecount = last_record[index+3]
        last_mmap_bytes = last_record[index+4]
    def get(names, default_value=""):
        """ some of the fields got renamed, try both old and new names """
        for n in names:
            v = d.get(n)
            if v is not None:
                return v
        return default_value
    return [
            get(["regions_per_second"]),
            get(["pixels_per_second"]),
            get(["pixels_encoded_per_second"]),
            get(["pixels_decoded_per_second"]),
            get(["batch_delay.min", "min_batch_delay"]),
            get(["batch_delay.max", "max_batch_delay"]),
            get(["batch_delay.avg", "avg_batch_delay"]),
            (int(get(["input_packetcount"], 0))-last_input_packetcount)/MEASURE_TIME,
            (int(get(["input_bytecount"], 0))-last_input_bytecount)/MEASURE_TIME,
            (int(get(["output_packetcount"], 0))-last_output_packetcount)/MEASURE_TIME,
            (int(get(["output_bytecount"], 0))-last_output_bytecount)/MEASURE_TIME,
            (int(get(["output_mmap_bytecount"], 0))-last_mmap_bytes)/MEASURE_TIME,
            get(["client_latency.min", "min_client_latency"]),
            get(["client_latency.max", "max_client_latency"]),
            get(["client_latency.avg", "avg_client_latency"]),
            get(["client_ping_latency.min"]),
            get(["client_ping_latency.max"]),
            get(["client_ping_latency.avg"]),
            get(["server_ping_latency.min", "server_latency.min", "min_server_latency"]),
            get(["server_ping_latency.max", "server_latency.max", "max_server_latency"]),
            get(["server_ping_latency.avg", "server_latency.avg", "avg_server_latency"]),
            get(["damage_in_latency.min"]),
            get(["damage_in_latency.max"]),
            get(["damage_in_latency.avg"]),
           ]

def get_xpra_start_server_command():
    cmd = [XPRA_BIN, "--no-daemon", "--bind-tcp=0.0.0.0:%s" % PORT]
    if XPRA_USE_XDUMMY:
        cmd.append("--xvfb=%s -nolisten tcp +extension GLX +extension RANDR +extension RENDER -logfile %s -config %s" % (XORG_BIN, XORG_LOG, XORG_CONFIG))
    if XPRA_VERSION_NO>=[0, 5]:
        cmd.append("--no-notifications")
    cmd.append("--password-file=%s" % password_filename)
    cmd += ["start", ":%s" % DISPLAY_NO]
    return cmd

def test_xpra():
    print("")
    print("*********************************************************")
    print("                Xpra tests")
    print("")
    tests = []
    for connect_option, encryption in XPRA_CONNECT_OPTIONS:
        shaping_options = TRICKLE_SHAPING_OPTIONS
        if connect_option=="unix":
            shaping_options = [NO_SHAPING]
        for down,up,latency in shaping_options:
            for x11_test_command in X11_TEST_COMMANDS:
                for encoding in XPRA_TEST_ENCODINGS:
                    quality_options = XPRA_ENCODING_QUALITY_OPTIONS.get(encoding, [-1])
                    for quality in quality_options:
                        comp_options = XPRA_COMPRESSION_OPTIONS
                        for compression in comp_options:
                            cmd = trickle_command(down, up, latency)
                            cmd += [XPRA_BIN, "attach"]
                            if connect_option=="ssh":
                                cmd.append("ssh:%s:%s" % (IP, DISPLAY_NO))
                            elif connect_option=="tcp":
                                cmd.append("tcp:%s:%s" % (IP, PORT))
                            else:
                                cmd.append(":%s" % (DISPLAY_NO))
                            cmd.append("--readonly")
                            cmd.append("--password-file=%s" % password_filename)
                            if compression is not None:
                                cmd += ["-z", str(compression)]
                            if XPRA_VERSION_NO>=[0, 3]:
                                cmd.append("--enable-pings")
                                cmd.append("--no-clipboard")
                            if XPRA_VERSION_NO>=[0, 5]:
                                cmd.append("--no-bell")
                                cmd.append("--no-cursors")
                                cmd.append("--no-notifications")
                            if XPRA_VERSION_NO>=[0, 8] and encryption:
                                cmd.append("--encryption=%s" % encryption)
                            if encoding in ("jpeg", "webp"):
                                if XPRA_VERSION_NO>=[0, 7]:
                                    cmd.append("--quality=%s" % quality)
                                else:
                                    cmd.append("--jpeg-quality=%s" % quality)
                                name = "%s-%s" % (encoding, quality)
                            else:
                                name = encoding
                            if encoding!="mmap":
                                cmd.append("--no-mmap")
                                cmd.append("--encoding=%s" % encoding)
                            command_name = get_command_name(x11_test_command)
                            test_name = "%s (%s - %s - %s - %s - via %s)" % (name, command_name, compression, encryption, trickle_str(down, up, latency), connect_option)
                            tests.append((test_name, "xpra", XPRA_VERSION, XPRA_VERSION, encoding, compression, encryption, connect_option, (down,up,latency), x11_test_command, cmd))
    return with_server(get_xpra_start_server_command(), XPRA_SERVER_STOP_COMMANDS, tests, xpra_get_stats)


def get_x11_client_window_info(display, *app_name_strings):
    env = os.environ.copy()
    if display:
        env["DISPLAY"] = display
    wininfo = getoutput(["xwininfo", "-root", "-tree"], env)
    for line in wininfo.splitlines():
        if not line:
            continue
        found = True
        for x in app_name_strings:
            if not line.find(x)>=0:
                found = False
                break
        if not found:
            continue
        parts = line.split()
        if not parts[0].startswith("0x"):
            continue
        #found a window which matches the name we are looking for!
        wid = parts[0]
        x, y, w, h = 0, 0, 0, 0
        dims = parts[-2]        #ie: 400x300+20+10
        dp = dims.split("+")    #["400x300", "20", "10"]
        if len(dp)==3:
            d = dp[0]           #"400x300"
            x = int(dp[1])      #20
            y = int(dp[2])      #10
            wh = d.split("x")   #["400", "300"]
            if len(wh)==2:
                w = int(wh[0])  #400
                h = int(wh[1])  #300
        print("Found window for '%s': %s - %sx%s" % (app_name_strings, wid, w, h))
        return  wid, x, y, w, h
    return  None

def get_vnc_stats(last_record=None):
    #print("get_vnc_stats(%s)" % last_record)
    if last_record==None:
        #this is the initial call,
        #start the thread to watch the output of tcbench
        #we first need to figure out the dimensions of the client window
        #within the Xvnc server, the use those dimensions to tell tcbench
        #where to look in the vncviewer client window
        test_window_info = get_x11_client_window_info(":%s" % DISPLAY_NO)
        print("info for client test window: %s" % str(test_window_info))
        info = get_x11_client_window_info(None, "TigerVNC: x11", "Vncviewer")
        if not info:
            return  no_stats(last_record)
        print("info for TigerVNC: %s" % str(info))
        wid, _, _, w, h = info
        if not wid:
            return  no_stats(last_record)
        if test_window_info:
            _, _, _, w, h = test_window_info
        command = [TCBENCH, "-wh%s" % wid, "-t%s" % (MEASURE_TIME-5)]
        if w>0 and h>0:
            command.append("-x%s" % int(w/2))
            command.append("-y%s" % int(h/2))
        if os.path.exists(TCBENCH_LOG):
            os.unlink(TCBENCH_LOG)
        tcbench_log  = open(TCBENCH_LOG, 'w')
        try:
            print("tcbench starting: %s, logging to %s" % (command, TCBENCH_LOG))
            return  subprocess.Popen(command, stdin=None, stdout=tcbench_log, stderr=tcbench_log)
        except Exception, e:
            import traceback
            traceback.print_exc()
            print("error running %s: %s" % (command, e))
        return  no_stats(last_record)           #we failed...
    regions_s = ""
    if last_record!="":
        #found the process watcher,
        #parse the tcbench output and look for frames/sec:
        assert type(last_record)==subprocess.Popen
        process = last_record
        #print("get_vnc_stats(%s) process.poll()=%s" % (last_record, process.poll()))
        if process.poll() is None:
            try_to_stop(process)
            try_to_kill(process, 2)
        else:
            f = open(TCBENCH_LOG, mode='rb')
            out = f.read()
            f.close()
            #print("get_vnc_stats(%s) tcbench output=%s" % (last_record, out))
            for line in out.splitlines():
                if not line.find("Frames/sec:")>=0:
                    continue
                parts = line.split()
                regions_s = parts[-1]
                print("Frames/sec=%s" % regions_s)
    return  [regions_s] + ["" for _ in xrange(20)]

def test_vnc():
    print("")
    print("*********************************************************")
    print("                VNC tests")
    print("")
    tests = []
    for down,up,latency in TRICKLE_SHAPING_OPTIONS:
        for x11_test_command in X11_TEST_COMMANDS:
            for encoding in VNC_ENCODINGS:
                for zlib in VNC_ZLIB_OPTIONS:
                    for compression in VNC_COMPRESSION_OPTIONS:
                        jpeg_quality = [8]
                        if encoding=="Tight":
                            jpeg_quality = VNC_JPEG_OPTIONS
                        for jpegq in jpeg_quality:
                            cmd = trickle_command(down, up, latency)
                            cmd += [VNCVIEWER_BIN, "%s::%s" % (IP, PORT),
                                   "--ViewOnly",
                                   "--ZlibLevel=%s" % str(zlib),
                                   "--CompressLevel=%s" % str(compression),
                                   ]
                            if encoding=="auto":
                                cmd.append("--AutoSelect=1")
                            else:
                                cmd.append("--AutoSelect=0")
                                cmd.append("--PreferredEncoding=%s" % encoding)
                            if jpegq<0:
                                cmd.append("--NoJPEG=1")
                                jpegtxt = "nojpeg"
                            else:
                                cmd.append("--NoJPEG=0")
                                cmd.append("--QualityLevel=%s" % jpegq)
                                jpegtxt = "jpeg=%s" % jpegq
                            #make a descriptive title:
                            if zlib==-1:
                                zlibtxt = "nozlib"
                            else:
                                zlibtxt = "zlib=%s" % zlib
                            command_name = get_command_name(x11_test_command)
                            test_name = "vnc (%s - %s - %s - compression=%s - %s - %s)" % (command_name, encoding, zlibtxt, compression, jpegtxt, trickle_str(down, up, latency))
                            tests.append((test_name, "vnc", XVNC_VERSION, VNCVIEWER_VERSION, encoding, compression, None, False, (down,up,latency), x11_test_command, cmd))
    return with_server(XVNC_SERVER_START_COMMAND, XVNC_SERVER_STOP_COMMANDS, tests, get_vnc_stats)


def main():
    #before doing anything, check that the firewall is setup correctly:
    get_iptables_INPUT_count()
    get_iptables_OUTPUT_count()

    xpra_results = []
    if TEST_XPRA:
        xpra_results = test_xpra()
    vnc_results = []
    if TEST_VNC:
        vnc_results = test_vnc()
    print("*"*80)
    print("RESULTS:")
    print("")
    headers = ["Test Name", "Remoting Tech", "Server Version", "Client Version", "Custom Params", "SVN Version",
               "Encoding", "Test Command", "Sample Duration (s)", "Sample Time (epoch)",
               "CPU info", "Platform", "Kernel Version", "Xorg version", "OpenGL", "Client Window Manager", "Screen Size",
               "Compression", "Encryption", "Connect via", "download limit (KB)", "upload limit (KB)", "latency (ms)",
               "packets in/s", "packets in: bytes/s", "packets out/s", "packets out: bytes/s"]
    headers += get_stats_headers()
    headers += ["client user cpu_pct", "client system cpu pct", "client number of threads", "client vsize (MB)", "client rss (MB)",
               "server user cpu_pct", "server system cpu pct", "server number of threads", "server vsize (MB)", "server rss (MB)",
               ]
    print(", ".join(headers))
    for result in xpra_results+vnc_results:
        print ", ".join([str(x) for x in result])

if __name__ == "__main__":
    main()
