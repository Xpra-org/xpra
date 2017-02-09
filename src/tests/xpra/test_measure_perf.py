#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#
# To create multiple output files which can be used to generate charts (using test_measure_perf_charts.py)
# build a config class (copy from perf_config_default.py -- make changes as necessary).
#
# Then determine the values of the following variables:
#   prefix: a string to identify the data set
#   id: a string to identify the variable that the data set is testing (for example '14' because we're testing xpra v14 in this data set)
#   repetitions: decide how many times you want to run the tests
#
# The data file names you will produce will then be in the format:
#   prefix_id_rep#.csv
#
# With this information in hand you can now create a script that will run the tests, containing commands like:
#   ./test_measure_perf.py as an example:

# For example:
#
# ./test_measure_perf.py all_tests_40 ./data/all_tests_40_14_1.csv 1 14 > ./data//all_tests_40_14_1.log
# ./test_measure_perf.py all_tests_40 ./data/all_tests_40_14_2.csv 2 14 > ./data//all_tests_40_14_2.log
#
# In this example script, I'm running test_measure_perf 2 times, using a config class named "all_tests_40.py",
# and outputting the results to data files using the prefix "all_tests_40", for version 14.
#
# The additional arguments "1 14", "2 14" are custom paramaters which will be written to the "Custom Params" column
# in the corresponding data files.
#
# Where you see "1", "2" in the file names or params, that's referring to the corresponding repetition of the tests.
#
# Once this script has run, you can open up test_measure_perf_charts.py and take a look at the
# instructions there for generating the charts.
#

import re
import sys
import subprocess
import os.path
import time

from xpra.log import Logger
log = Logger()

def getoutput(cmd, env=None):
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, close_fds=True)
    except Exception as e:
        print("error running %s: %s" % (cmd, e))
        raise e
    (out,err) = process.communicate()
    code = process.poll()
    if code!=0:
        raise Exception("command '%s' returned error code %s, out=%s, err=%s" % (cmd, code, out, err))
    return out

def get_config(config_name):
    try:
        mod = __import__(config_name)
    except (ImportError, SyntaxError) as e:
        sys.stderr.write("Error loading module %s (%s)\n" % (config_name, e))
        return None
    return mod.Config()

if (len(sys.argv) > 1):
    config_name = sys.argv[1]
else:
    config_name = 'perf_config_default'
config = get_config(config_name)
if (config==None):
    raise Exception("Could not load config file")

XPRA_BIN = "/usr/bin/xpra"
XPRA_VERSION_OUTPUT = getoutput([XPRA_BIN, "--version"])
XPRA_VERSION = ""
for x in XPRA_VERSION_OUTPUT.splitlines():
    if x.startswith("xpra v"):
        XPRA_VERSION = x[len("xpra v"):].replace("\n", "").replace("\r", "")
XPRA_VERSION = XPRA_VERSION.split("-")[0]
XPRA_VERSION_NO = [int(x) for x in XPRA_VERSION.split(".")]
XPRA_SERVER_STOP_COMMANDS = [
                             [XPRA_BIN, "stop", ":%s" % config.DISPLAY_NO],
                             "ps -ef | grep -i [X]org-for-Xpra-:%s | awk '{print $2}' | xargs kill" % config.DISPLAY_NO
                             ]
XPRA_INFO_COMMAND = [XPRA_BIN, "info", "tcp:%s:%s" % (config.IP, config.PORT)]
print ("XPRA_VERSION_NO=%s" % XPRA_VERSION_NO)

STRICT_ENCODINGS = False
if STRICT_ENCODINGS:
    #beware: only enable this flag if the version being tested
    # also supports the same environment overrides,
    # or the comparison will not be fair.
    os.environ["XPRA_ENCODING_STRICT_MODE"] = "1"
    os.environ["XPRA_MAX_PIXELS_PREFER_RGB"] = "0"
    os.environ["XPRA_MAX_NONVIDEO_PIXELS"] = "0"

XPRA_SPEAKER_OPTIONS = [None]
XPRA_MICROPHONE_OPTIONS = [None]
if config.TEST_SOUND:
    from xpra.sound.gstreamer_util import CODEC_ORDER, has_codec
    if XPRA_VERSION_NO>=[0, 9]:
        #0.9 onwards supports all codecs defined:
        XPRA_SPEAKER_OPTIONS = [x for x in CODEC_ORDER if has_codec(x)]
    elif XPRA_VERSION_NO==[0, 8]:
        #only mp3 works in 0.8:
        XPRA_SPEAKER_OPTIONS = ["mp3"]
    else:
        #none before that
        XPRA_SPEAKER_OPTIONS = [None]

if (config.XPRA_USE_PASSWORD):
    password_filename = "./test-password.txt"
    import uuid
    with open(password_filename, 'wb') as f:
        f.write(uuid.uuid4().hex)

check = [config.TRICKLE_BIN]
if config.TEST_XPRA:
    check.append(XPRA_BIN)
if config.TEST_VNC:
    check.append(config.XVNC_BIN)
    check.append(config.VNCVIEWER_BIN)
for x in check:
    if not os.path.exists(x):
        raise Exception("cannot run tests: %s is missing!" % x)

HEADERS = ["Test Name", "Remoting Tech", "Server Version", "Client Version", "Custom Params", "SVN Version",
           "Encoding", "Quality", "Speed","OpenGL", "Test Command", "Sample Duration (s)", "Sample Time (epoch)",
           "CPU info", "Platform", "Kernel Version", "Xorg version", "OpenGL", "Client Window Manager", "Screen Size",
           "Compression", "Encryption", "Connect via", "download limit (KB)", "upload limit (KB)", "latency (ms)",
           "packets in/s", "packets in: bytes/s", "packets out/s", "packets out: bytes/s",
           "Regions/s", "Pixels/s Sent", "Encoding Pixels/s", "Decoding Pixels/s",
           "Application packets in/s", "Application bytes in/s",
           "Application packets out/s", "Application bytes out/s", "mmap bytes/s",
           "Video Encoder", "CSC", "CSC Mode", "Scaling",
           ]
for x in ("client", "server"):
    HEADERS += [x+" user cpu_pct", x+" system cpu pct", x+" number of threads", x+" vsize (MB)", x+" rss (MB)"]
#all these headers have min/max/avg:
for h in ("Batch Delay (ms)", "Actual Batch Delay (ms)",
          "Client Latency (ms)", "Client Ping Latency (ms)", "Server Ping Latency (ms)",
          "Damage Latency (ms)",
          "Quality", "Speed"):
    for x in ("Min", "Avg", "Max"):
        HEADERS.append(x+" "+h)

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
        except Exception as e:
            print("could not stop process %s: %s" % (process, e))
def try_to_kill(process, grace=0):
    if is_process_alive(process, grace):
        try:
            process.kill()
        except Exception as e:
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
    if len(lines)!=1:
        print("WARNING: expected 1 line matching '%s' from %s but found %s" % (pattern, cmd, len(lines)))
        return "not found"
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

XORG_VERSION = getoutput_line([config.XORG_BIN, "-version"], "X.Org X Server", "Cannot detect Xorg server version")
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
DETECT_XVNC_VERSION_CMD = [config.XVNC_BIN, "--help"]
DETECT_VNCVIEWER_VERSION_CMD = [config.VNCVIEWER_BIN, "--help"]
def get_stderr(command):
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _,err = process.communicate()
        return err
    except Exception as e:
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

#get svnversion, prefer directly from svn:
try:
    SVN_VERSION = getoutput(["svnversion", "-n"]).split(":")[-1].strip()
except:
    SVN_VERSION = ""
if not SVN_VERSION:
    #fallback to getting it from xpra's src_info:
    try:
        from xpra.src_info import REVISION, LOCAL_MODIFICATIONS
        SVN_VERSION = 'r%s' % REVISION
        if LOCAL_MODIFICATIONS:
            SVN_VERSION += "M"
    except:
        pass
if not SVN_VERSION:
    #fallback to running python:
    SVN_VERSION = getoutput(["python", "-c", "from xpra.src_info import REVISION,LOCAL_MODIFICATIONS;print(('r%s%s' % (REVISION, ' M'[int(bool(LOCAL_MODIFICATIONS))])).strip())"])
print("Found xpra revision: '%s'" % str(SVN_VERSION))

WINDOW_MANAGER = os.environ.get("DESKTOP_SESSION", "unknown")

def clean_sys_state():
    #clear the caches
    cmd = ["echo", "3", ">", "/proc/sys/vm/drop_caches"]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.wait()==0, "failed to run %s" % str(cmd)

def zero_iptables():
    if not config.USE_IPTABLES:
        return
    cmds = [config.IPTABLES_CMD+['-Z', 'INPUT'], config.IPTABLES_CMD+['-Z', 'OUTPUT']]
    for cmd in cmds:
        getoutput(cmd)
        #out = getoutput(cmd)
        #print("output(%s)=%s" % (cmd, out))

def update_proc_stat():
    with open("/proc/stat", "rU") as proc_stat:
        time_total = 0
        for line in proc_stat:
            values = line.split()
            if values[0]=="cpu":
                time_total = sum([int(x) for x in values[1:]])
                #print("time_total=%s" % time_total)
                break
    return time_total

def update_pidstat(pid):
    with open("/proc/%s/stat" % pid, "rU") as stat_file:
        data = stat_file.read()
    pid_stat = data.split()
    #print("update_pidstat(%s): %s" % (pid, pid_stat))
    return pid_stat

def compute_stat(prefix, time_total_diff, old_pid_stat, new_pid_stat):
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
    return {prefix+" user cpu_pct"       : user_pct,
            prefix+" system cpu pct"     : sys_pct,
            prefix+" number of threads"  : nthreads,
            prefix+" vsize (MB)"         : vsize,
            prefix+" rss (MB)"           : rss,
            }

def getiptables_line(chain, pattern, setup_info):
    cmd = config.IPTABLES_CMD + ["-vnL", chain]
    line = getoutput_line(cmd, pattern, setup_info)
    if not line:
        raise Exception("no line found matching %s, make sure you have a rule like: %s" % (pattern, setup_info))
    return line

def parse_ipt(chain, pattern, setup_info):
    if not config.USE_IPTABLES:
        return  0, 0
    line = getiptables_line(chain, pattern, setup_info)
    parts = line.split()
    assert len(parts)>2
    def parse_num(part):
        U = 1024
        m = {"K":U, "M":U**2, "G":U**3}.get(part[-1], 1)
        num = "".join([x for x in part if x in "0123456789"])
        return int(num)*m/config.MEASURE_TIME
    return parse_num(parts[0]), parse_num(parts[1])

def get_iptables_INPUT_count():
    setup = "iptables -I INPUT -p tcp --dport %s -j ACCEPT" % config.PORT
    return  parse_ipt("INPUT", "tcp dpt:%s" % config.PORT, setup)

def get_iptables_OUTPUT_count():
    setup = "iptables -I OUTPUT -p tcp --sport %s -j ACCEPT" % config.PORT
    return  parse_ipt("OUTPUT", "tcp spt:%s" % config.PORT, setup)

def measure_client(server_pid, name, cmd, get_stats_cb):
    print("starting client: %s" % cmd)
    try:
        client_process = subprocess.Popen(cmd)
        #give it time to settle down:
        time.sleep(config.SETTLE_TIME)
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
        t = 0
        all_stats = [initial_stats]
        while t<config.MEASURE_TIME:
            time.sleep(config.COLLECT_STATS_TIME)
            t += config.COLLECT_STATS_TIME

            code = client_process.poll()
            assert code is None, "client crashed, return code is %s" % code

            stats = get_stats_cb(initial_stats, all_stats)

        #stop the counters
        new_time_total = update_proc_stat()
        new_pid_stat = update_pidstat(client_process.pid)
        if server_pid>0:
            new_server_pid_stat = update_pidstat(server_pid)
        ni,isize = get_iptables_INPUT_count()
        no,osize = get_iptables_OUTPUT_count()
        #[ni, isize, no, osize]
        iptables_stat = {"packets in/s"         : ni,
                         "packets in: bytes/s"  : isize,
                         "packets out/s"        : no,
                         "packets out: bytes/s" : osize}
        #now collect the data
        client_process_data = compute_stat("client", new_time_total-old_time_total, old_pid_stat, new_pid_stat)
        if server_pid>0:
            server_process_data = compute_stat("server", new_time_total-old_time_total, old_server_pid_stat, new_server_pid_stat)
        else:
            server_process_data = []
        print("process_data (client/server): %s / %s" % (client_process_data, server_process_data))
        print("input/output on tcp PORT %s: %s / %s packets, %s / %s KBytes" % (config.PORT, ni, no, isize, osize))
        data = {}
        data.update(iptables_stat)
        data.update(stats)
        data.update(client_process_data)
        data.update(server_process_data)
        return data
    finally:
        #stop the process
        if client_process and client_process.poll() is None:
            try_to_stop(client_process)
            try_to_kill(client_process, 5)
            code = client_process.poll()
            assert code is not None, "failed to stop client!"

def with_server(start_server_command, stop_server_commands, in_tests, get_stats_cb):
    tests = in_tests[config.STARTING_TEST:config.LIMIT_TESTS]
    print("going to run %s tests: %s" % (len(tests), [x[0] for x in tests]))
    print("*******************************************")
    print("ETA: %s minutes" % int((config.SERVER_SETTLE_TIME+config.DEFAULT_TEST_COMMAND_SETTLE_TIME+config.SETTLE_TIME+config.MEASURE_TIME+1)*len(tests)/60))
    print("*******************************************")

    server_process = None
    test_command_process = None
    env = {}
    for k,v in os.environ.items():
    #whitelist what we want to keep:
        if k.startswith("XPRA") or k in ("LOGNAME", "XDG_RUNTIME_DIR", "USER", "HOME", "PATH", "LD_LIBRARY_PATH", "XAUTHORITY", "SHELL", "TERM", "USERNAME", "HOSTNAME", "PWD"):
            env[k] = v
    env["DISPLAY"] = ":%s" % config.DISPLAY_NO
    errors = 0
    results = []
    count = 0
    for name, tech_name, server_version, client_version, encoding, quality, speed, \
        opengl, compression, encryption, ssh, (down,up,latency), test_command, client_cmd in tests:
        try:
            print("**************************************************************")
            count += 1
            test_command_settle_time = config.TEST_COMMAND_SETTLE_TIME.get(test_command[0], config.DEFAULT_TEST_COMMAND_SETTLE_TIME)
            eta = int((config.SERVER_SETTLE_TIME+test_command_settle_time+config.SETTLE_TIME+config.MEASURE_TIME+1)*(len(tests)-count)/60)
            print("%s/%s: %s            ETA=%s minutes" % (count, len(tests), name, eta))
            test_command_process = None
            try:
                clean_sys_state()
                #start the server:
                if config.START_SERVER:
                    print("starting server: %s" % str(start_server_command))
                    server_process = subprocess.Popen(start_server_command, stdin=None)
                    #give it time to settle down:
                    t = config.SERVER_SETTLE_TIME
                    if count==1:
                        #first run, give it enough time to cleanup the socket
                        t += 5
                    time.sleep(t)
                    server_pid = server_process.pid
                    code = server_process.poll()
                    assert code is None, "server failed to start, return code is %s, please ensure that you can run the server command line above and that a server does not already exist on that port or DISPLAY" % code
                else:
                    server_pid = 0

                try:
                    #start the test command:
                    if config.USE_VIRTUALGL:
                        if type(test_command)==str:
                            cmd = config.VGLRUN_BIN + " -- "+ test_command
                        elif type(test_command) in (list, tuple):
                            cmd = [config.VGLRUN_BIN, "--"] + list(test_command)
                        else:
                            raise Exception("invalid test command type: %s for %s" % (type(test_command), test_command))
                    else:
                        cmd = test_command

                    print("starting test command: %s with env=%s, settle time=%s" % (cmd, env, test_command_settle_time))
                    shell = type(cmd)==str
                    test_command_process = subprocess.Popen(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, shell=shell)

                    if config.PREVENT_SLEEP:
                        subprocess.Popen(config.PREVENT_SLEEP_COMMAND)

                    time.sleep(test_command_settle_time)
                    code = test_command_process.poll()
                    assert code is None, "test command %s failed to start: exit code is %s" % (cmd, code)
                    print("test command %s is running with pid=%s" % (cmd, test_command_process.pid))

                    #run the client test
                    data = {"Test Name"      : name,
                            "Remoting Tech"  : tech_name,
                            "Server Version" : server_version,
                            "Client Version" : client_version,
                            "Custom Params"  : config.CUSTOM_PARAMS,
                            "SVN Version"    : SVN_VERSION,
                            "Encoding"       : encoding,
                            "Quality"        : quality,
                            "Speed"          : speed,
                            "OpenGL"         : opengl,
                            "Test Command"   : get_command_name(test_command),
                            "Sample Duration (s)"    : config.MEASURE_TIME,
                            "Sample Time (epoch)"    : time.time(),
                            "CPU info"       : CPU_INFO,
                            "Platform"       : PLATFORM,
                            "Kernel Version" : KERNEL_VERSION,
                            "Xorg version"   : XORG_VERSION,
                            "OpenGL"         : OPENGL_INFO,
                            "Client Window Manager"  : WINDOW_MANAGER,
                            "Screen Size"    : "%sx%s" % gdk.get_default_root_window().get_size(),
                            "Compression"    : compression,
                            "Encryption"     : encryption,
                            "Connect via"    : ssh,
                            "download limit (KB)"    : down,
                            "upload limit (KB)"      : up,
                            "latency (ms)"           : latency,
                            }
                    data.update(measure_client(server_pid, name, client_cmd, get_stats_cb))
                    results.append([data.get(x, "") for x in HEADERS])
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    errors += 1
                    print("error during client command run for %s: %s" % (name, e))
                    if errors>config.MAX_ERRORS:
                        print("too many errors, aborting tests")
                        break
            finally:
                if test_command_process:
                    print("stopping '%s' with pid=%s" % (test_command, test_command_process.pid))
                    try_to_stop(test_command_process)
                    try_to_kill(test_command_process, 2)
                if config.START_SERVER:
                    try_to_stop(server_process)
                    time.sleep(2)
                    for s in stop_server_commands:
                        print("stopping server with: %s" % (s))
                        try:
                            stop_process = subprocess.Popen(s, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
                            stop_process.wait()
                        except Exception as e:
                            print("error: %s" % e)
                    try_to_kill(server_process, 5)
                time.sleep(1)
        except KeyboardInterrupt as e:
            print("caught %s: stopping this series of tests" % e)
            break
    return results

def trickle_command(down, up, latency):
    if down<=0 and up<=0 and latency<=0:
        return  []
    cmd = [config.TRICKLE_BIN, "-s"]
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
        name = config.TEST_NAMES.get(command_arg)
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

def get_auth_args():
    cmd = []
    if config.XPRA_USE_PASSWORD:
        cmd.append("--password-file=%s" % password_filename)
        if XPRA_VERSION_NO>=[0, 14]:
            cmd.append("--auth=file")
        if XPRA_VERSION_NO>=[0, 15]:
            cmd.append("--auth=none")
            cmd.append("--tcp-auth=file")
    return cmd

def xpra_get_stats(initial_stats=None, all_stats=[]):
    if XPRA_VERSION_NO<[0, 3]:
        return  {}
    info_cmd = XPRA_INFO_COMMAND[:] + get_auth_args()
    out = getoutput(info_cmd)
    if not out:
        return  {}
    #parse output:
    d = {}
    for line in out.splitlines():
        parts = line.split("=")
        if len(parts)==2:
            d[parts[0]] = parts[1]
    #functions for accessing the data:
    def iget(names, default_value=""):
        """ some of the fields got renamed, try both old and new names """
        for n in names:
            v = d.get(n)
            if v is not None:
                return int(v)
        return default_value
    #values always based on initial data only:
    #(difference from initial value)
    lookup = initial_stats or {}
    initial_input_packetcount  = lookup.get("Application packets in/s", 0)
    initial_input_bytecount    = lookup.get("Application bytes in/s", 0)
    initial_output_packetcount = lookup.get("Application packets out/s", 0)
    initial_output_bytecount   = lookup.get("Application bytes out/s", 0)
    initial_mmap_bytes         = lookup.get("mmap bytes/s", 0)
    data = {
            "Application packets in/s"      : (iget(["client.connection.input.packetcount", "input_packetcount"], 0)-initial_input_packetcount)/config.MEASURE_TIME,
            "Application bytes in/s"        : (iget(["client.connection.input.bytecount", "input_bytecount"], 0)-initial_input_bytecount)/config.MEASURE_TIME,
            "Application packets out/s"     : (iget(["client.connection.output.packetcount", "output_packetcount"], 0)-initial_output_packetcount)/config.MEASURE_TIME,
            "Application bytes out/s"       : (iget(["client.connection.output.bytecount", "output_bytecount"], 0)-initial_output_bytecount)/config.MEASURE_TIME,
            "mmap bytes/s"                  : (iget(["client.connection.output.mmap_bytecount", "output_mmap_bytecount"], 0)-initial_mmap_bytes)/config.MEASURE_TIME,
            }

    #values that are averages or min/max:
    def add(prefix, op, name, prop_names):
        values = []
        #cook the property names using the lowercase prefix if needed
        #(all xpra info properties are lowercase):
        actual_prop_names = []
        full_search = []
        for prop_name in prop_names:
            if prop_name.find("%s")>=0:
                prop_name = prop_name % prefix.lower()
            actual_prop_names.append(prop_name)
            if prop_name.find("*")>=0 or prop_name.find("+")>=0:        #ie: "window\[\d+\].encoding.quality.avg"
                #make it a proper python regex:
                full_search.append(prop_name)
        if len(full_search)>0:
            for s in full_search:
                regex = re.compile(s)
                matches = [d.get(x) for x in d.keys() if regex.match(x)]
                for v in matches:
                    values.append(int(v))
            #print("add(%s, %s, %s, %s) values from full_search=%s: %s" % (prefix, op, name, prop_names, full_search, values))
        else:
            #match just one record:
            values.append(iget(actual_prop_names))
            #print("add(%s, %s, %s, %s) values from iget: %s" % (prefix, op, name, prop_names, values))
        #this is the stat property name:
        full_name = name                            #ie: "Application packets in/s"
        if prefix:
            full_name = prefix+" "+name             #ie: "Min" + " " + "Batch Delay"
        for s in all_stats:                         #add all previously found values to list
            values.append(s.get(full_name))
        #strip missing values:
        values = [x for x in values if x is not None and x!=""]
        if len(values)>0:
            v = op(values)                          #ie: avg([4,5,4]) or max([4,5,4])
            #print("%s: %s(%s)=%s" % (full_name, op, values, v))
            data[full_name] = v

    def avg(l):
        return sum(l)/len(l)

    add("", avg, "Regions/s",                       ["encoding.regions_per_second", "regions_per_second"])
    add("", avg, "Pixels/s Sent",                   ["encoding.pixels_per_second", "pixels_per_second"])
    add("", avg, "Encoding Pixels/s",               ["encoding.pixels_encoded_per_second", "pixels_encoded_per_second"])
    add("", avg, "Decoding Pixels/s",               ["encoding.pixels_decoded_per_second", "pixels_decoded_per_second"])

    for prefix, op in (("Min", min), ("Max", max), ("Avg", avg)):
        add(prefix, op, "Batch Delay (ms)",         ["batch.delay.%s", "batch_delay.%s", "%s_batch_delay"])
        add(prefix, op, "Actual Batch Delay (ms)",  ["batch.actual_delay.%s"])
        add(prefix, op, "Client Latency (ms)",      ["client.latency.%s", "client_latency.%s", "%s_client_latency"])
        add(prefix, op, "Client Ping Latency (ms)", ["client.ping_latency.%s", "client_ping_latency.%s"])
        add(prefix, op, "Server Ping Latency (ms)", ["server.ping_latency.%s", "server_ping_latency.%s", "server_latency.%s", "%s_server_latency"])
        add(prefix, op, "Damage Latency (ms)",      ["damage.in_latency.%s", "damage_in_latency.%s"])

        add(prefix, op, "Quality",                  ["^window\[\d+\].encoding.quality.%s$"])
        add(prefix, op, "Speed",                    ["^window\[\d+\].encoding.speed.%s$"])

    def addset(name, prop_name):
        regex = re.compile(prop_name)
        def getdictvalues(from_dict):
            return [from_dict.get(x) for x in from_dict.keys() if regex.match(x)]
        values = getdictvalues(d)
        for s in all_stats:                         #add all previously found values to list
            values += getdictvalues(s)
        data[name] = list(set(values))

    #video encoder
    addset("Video Encoder", "^window\[\d+\].encoder$")
    #record CSC:
    addset("CSC", "^window\[\d+\].csc$")
    addset("CSC Mode", "^window\[\d+\].csc.dst_format$")
    addset("Scaling", "^window\[\d+\].scaling$")
    #packet layer:
    addset("Compressors", "connection.compression$")
    addset("Packet Encoders", "connection.encoder$")
    #add this record to the list:
    all_stats.append(data)
    return data

def get_xpra_start_server_command():
    cmd = [XPRA_BIN, "--no-daemon", "--bind-tcp=0.0.0.0:%s" % config.PORT]
    if config.XPRA_FORCE_XDUMMY:
        cmd.append("--xvfb=%s -nolisten tcp +extension GLX +extension RANDR +extension RENDER -logfile %s -config %s" % (config.XORG_BIN, config.XORG_LOG, config.XORG_CONFIG))
    if XPRA_VERSION_NO>=[0, 5]:
        cmd.append("--no-notifications")
    cmd += get_auth_args()
    cmd.append("--no-pulseaudio")
    cmd += ["start", ":%s" % config.DISPLAY_NO]
    return cmd

def test_xpra():
    print("")
    print("*********************************************************")
    print("                Xpra tests")
    print("")
    tests = []
    for connect_option, encryption in config.XPRA_CONNECT_OPTIONS:
        shaping_options = config.TRICKLE_SHAPING_OPTIONS
        if connect_option=="unix-domain":
            shaping_options = [config.NO_SHAPING]
        for down,up,latency in shaping_options:
            for x11_test_command in config.X11_TEST_COMMANDS:
                for encoding in config.XPRA_TEST_ENCODINGS:
                    if XPRA_VERSION_NO>=[0, 10]:
                        opengl_options = config.XPRA_OPENGL_OPTIONS.get(encoding, [True])
                    elif XPRA_VERSION_NO>=[0, 9]:
                        opengl_options = config.XPRA_OPENGL_OPTIONS.get(encoding, [False])
                    else:
                        opengl_options = [False]
                    for opengl in opengl_options:
                        quality_options = config.XPRA_ENCODING_QUALITY_OPTIONS.get(encoding, [-1])
                        for quality in quality_options:
                            speed_options = config.XPRA_ENCODING_SPEED_OPTIONS.get(encoding, [-1])
                            for speed in speed_options:
                                for speaker in XPRA_SPEAKER_OPTIONS:
                                    for mic in XPRA_MICROPHONE_OPTIONS:
                                        comp_options = [None]
                                        if XPRA_VERSION_NO>=[0, 13]:
                                            comp_options = config.XPRA_COMPRESSORS_OPTIONS
                                        for comp in comp_options:
                                            comp_level_options = config.XPRA_COMPRESSION_LEVEL_OPTIONS
                                            for compression in comp_level_options:
                                                packet_encoders_options = [None]
                                                if XPRA_VERSION_NO>=[0, 14]:
                                                    packet_encoders_options = config.XPRA_PACKET_ENCODERS_OPTIONS
                                                for packet_encoders in packet_encoders_options:
                                                    cmd = trickle_command(down, up, latency)
                                                    cmd += [XPRA_BIN, "attach"]
                                                    if connect_option=="ssh":
                                                        cmd.append("ssh:%s:%s" % (config.IP, config.DISPLAY_NO))
                                                    elif connect_option=="tcp":
                                                        cmd.append("tcp:%s:%s" % (config.IP, config.PORT))
                                                    else:
                                                        cmd.append(":%s" % (config.DISPLAY_NO))
                                                    if XPRA_VERSION_NO>=[0, 15]:
                                                        cmd.append("--readonly=yes")
                                                    else:
                                                        cmd.append("--readonly")
                                                    cmd += get_auth_args()
                                                    if packet_encoders:
                                                        cmd += ["--packet-encoders=%s" % packet_encoders]
                                                    if comp:
                                                        cmd += ["--compressors=%s" % comp]
                                                    if compression is not None:
                                                        cmd += ["-z", str(compression)]
                                                    if XPRA_VERSION_NO>=[0, 3]:
                                                        cmd.append("--enable-pings")
                                                        cmd.append("--no-clipboard")
                                                    if XPRA_VERSION_NO>=[0, 5]:
                                                        cmd.append("--no-bell")
                                                        cmd.append("--no-cursors")
                                                        cmd.append("--no-notifications")
                                                    if XPRA_VERSION_NO>=[0, 12]:
                                                        if config.XPRA_MDNS:
                                                            cmd.append("--mdns")
                                                        else:
                                                            cmd.append("--no-mdns")
                                                    if XPRA_VERSION_NO>=[0, 8] and encryption:
                                                        cmd.append("--encryption=%s" % encryption)
                                                    if speed>=0:
                                                        cmd.append("--speed=%s" % speed)
                                                    if quality>=0:
                                                        if XPRA_VERSION_NO>=[0, 7]:
                                                            cmd.append("--quality=%s" % quality)
                                                        else:
                                                            cmd.append("--jpeg-quality=%s" % quality)
                                                        name = "%s-%s" % (encoding, quality)
                                                    else:
                                                        name = encoding
                                                    if speaker is None:
                                                        if XPRA_VERSION_NO>=[0, 8]:
                                                            cmd.append("--no-speaker")
                                                    else:
                                                        cmd.append("--speaker-codec=%s" % speaker)
                                                    if mic is None:
                                                        if XPRA_VERSION_NO>=[0, 8]:
                                                            cmd.append("--no-microphone")
                                                    else:
                                                        cmd.append("--microphone-codec=%s" % mic)
                                                    if encoding!="mmap":
                                                        cmd.append("--no-mmap")
                                                        cmd.append("--encoding=%s" % encoding)
                                                    if XPRA_VERSION_NO>=[0, 9]:
                                                        cmd.append("--opengl=%s" % opengl)
                                                    command_name = get_command_name(x11_test_command)
                                                    test_name = "%s (%s - %s - %s - %s - via %s)" % \
                                                        (name, command_name, compression, encryption, trickle_str(down, up, latency), connect_option)
                                                    tests.append((test_name, "xpra", XPRA_VERSION, XPRA_VERSION, \
                                                                  encoding, quality, speed,
                                                                  opengl, compression, encryption, connect_option, \
                                                                  (down,up,latency), x11_test_command, cmd))
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

def get_vnc_stats(initial_stats=None, all_stats=[]):
    #print("get_vnc_stats(%s)" % last_record)
    if initial_stats==None:
        #this is the initial call,
        #start the thread to watch the output of tcbench
        #we first need to figure out the dimensions of the client window
        #within the Xvnc server, the use those dimensions to tell tcbench
        #where to look in the vncviewer client window
        test_window_info = get_x11_client_window_info(":%s" % config.DISPLAY_NO)
        print("info for client test window: %s" % str(test_window_info))
        info = get_x11_client_window_info(None, "TigerVNC: x11", "Vncviewer")
        if not info:
            return  {}
        print("info for TigerVNC: %s" % str(info))
        wid, _, _, w, h = info
        if not wid:
            return  {}
        if test_window_info:
            _, _, _, w, h = test_window_info
        command = [config.TCBENCH, "-wh%s" % wid, "-t%s" % (config.MEASURE_TIME-5)]
        if w>0 and h>0:
            command.append("-x%s" % int(w/2))
            command.append("-y%s" % int(h/2))
        if os.path.exists(config.TCBENCH_LOG):
            os.unlink(config.TCBENCH_LOG)
        tcbench_log  = open(config.TCBENCH_LOG, 'w')
        try:
            print("tcbench starting: %s, logging to %s" % (command, config.TCBENCH_LOG))
            proc = subprocess.Popen(command, stdin=None, stdout=tcbench_log, stderr=tcbench_log)
            return {"tcbench" : proc}
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("error running %s: %s" % (command, e))
        return  {}           #we failed...
    regions_s = ""
    if "tcbench" in initial_stats:
        #found the process watcher,
        #parse the tcbench output and look for frames/sec:
        process = initial_stats.get("tcbench")
        assert type(process)==subprocess.Popen
        #print("get_vnc_stats(%s) process.poll()=%s" % (last_record, process.poll()))
        if process.poll() is None:
            try_to_stop(process)
            try_to_kill(process, 2)
        else:
            with open(config.TCBENCH_LOG, mode='rb') as f:
                out = f.read()
            #print("get_vnc_stats(%s) tcbench output=%s" % (last_record, out))
            for line in out.splitlines():
                if not line.find("Frames/sec:")>=0:
                    continue
                parts = line.split()
                regions_s = parts[-1]
                print("Frames/sec=%s" % regions_s)
    return {
            "Regions/s"                     : regions_s,
           }

def test_vnc():
    print("")
    print("*********************************************************")
    print("                VNC tests")
    print("")
    tests = []
    for down,up,latency in config.TRICKLE_SHAPING_OPTIONS:
        for x11_test_command in config.X11_TEST_COMMANDS:
            for encoding in config.VNC_ENCODINGS:
                for zlib in config.VNC_ZLIB_OPTIONS:
                    for compression in config.VNC_COMPRESSION_OPTIONS:
                        jpeg_quality = [8]
                        if encoding=="Tight":
                            jpeg_quality = config.VNC_JPEG_OPTIONS
                        for jpegq in jpeg_quality:
                            cmd = trickle_command(down, up, latency)
                            cmd += [config.VNCVIEWER_BIN, "%s::%s" % (config.IP, config.PORT),
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
                            test_name = "vnc (%s - %s - %s - compression=%s - %s - %s)" % \
                                        (command_name, encoding, zlibtxt, compression, jpegtxt, trickle_str(down, up, latency))
                            tests.append((test_name, "vnc", XVNC_VERSION, VNCVIEWER_VERSION, \
                                          encoding, False, compression, None, False, \
                                          (down,up,latency), x11_test_command, cmd))
    return with_server(config.XVNC_SERVER_START_COMMAND, config.XVNC_SERVER_STOP_COMMANDS, tests, get_vnc_stats)

def main():
    #before doing anything, check that the firewall is setup correctly:
    get_iptables_INPUT_count()
    get_iptables_OUTPUT_count()

    #If CUSTOM_PARAMS are supplied on the command line, they override what's in config
    if (len(sys.argv) > 3):
        config.CUSTOM_PARAMS = " ".join(sys.argv[3:])
    config.print_options()

    xpra_results = []
    if config.TEST_XPRA:
        xpra_results = test_xpra()
    vnc_results = []
    if config.TEST_VNC:
        vnc_results = test_vnc()

    if (len(sys.argv) > 2):
        csv_name = sys.argv[2]
    else:
        csv_name = None

    print("*"*80)
    print("RESULTS:")
    print("")

    out_lines = []
    out_line = ", ".join(HEADERS)
    print out_line
    out_lines.append(out_line)

    def s(x):
        if x is None:
            return ""
        elif type(x) in (list, tuple, set):
            return '"' + (", ".join(list(x))) + '"'
        elif type(x) in (unicode, str):
            if len(x)==0:
                return ""
            return '"%s"' % x
        elif type(x) in (float, long, int):
            return str(x)
        else:
            return "unhandled-type: %s" % type(x)

    for result in xpra_results+vnc_results:
        out_line = ", ".join([s(x) for x in result])
        print(out_line)
        out_lines.append(out_line)

    if (csv_name != None):
        with open(csv_name, "w") as csv:
            for line in out_lines:
                csv.write(line+"\n")

if __name__ == "__main__":
    main()
