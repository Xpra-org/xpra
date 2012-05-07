#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import subprocess
import os.path
import time

from wimpiggy.log import Logger
log = Logger()
HOME = os.path.expanduser("~/")

#You will probably need to change those:
IP = "192.168.42.100"       #this is your IP
PORT = 10000                #the port to test on
DISPLAY_NO = 10             #the test DISPLAY no to use
XORG_CONFIG="%s/xorg.conf" % HOME
XORG_LOG = "%s/Xorg.%s.log" % (HOME, DISPLAY_NO)
START_SERVER = True         #if False, you are responsible for starting it
                            #and the data will not be available
TEST_XPRA = True
TEST_VNC = True

GLX_SPHERES = ["/opt/VirtualGL/bin/glxspheres"]
GLX_GEARS = ["/usr/bin/glxgears", "-geometry", "1240x900"]
X11_PERF = ["/usr/bin/x11perf", "-resize", "-all"]
XTERM_TEST = ["/usr/bin/xterm", "-geometry", "160x60", "-e", "while true; do dmesg; done"]
XSCREENSAVERS_PATH = "/usr/libexec/xscreensaver"
ALL_XSCREENSAVER_TESTS = ["%s/%s" % (XSCREENSAVERS_PATH, x) for x in
                        ["rss-glx-hufo_tunnel", "rss-glx-lattice", "rss-glx-plasma", "deluxe", "eruption", "memscroller", "moebiusgears", "polytopes", "rss-glx-drempels",
                         "xjack", "xmatrix"]
                          ]
SOME_XSCREENSAVER_TESTS = [["%s/%s" % (XSCREENSAVERS_PATH, x)] for x in
                        ["rss-glx-hufo_tunnel", "eruption", "memscroller", "xmatrix"]
                          ]
X11_TEST_COMMANDS = []
for x in [GLX_SPHERES, X11_PERF, GLX_GEARS, XTERM_TEST] + SOME_XSCREENSAVER_TESTS:
    if not os.path.exists(x[0]):
        print("WARNING: cannot find %s - removed from tests" % str(x))
    else:
        X11_TEST_COMMANDS.append(x)
        

#but these should be ok:
SETTLE_TIME = 5             #how long to wait before we start measuring
MEASURE_TIME = 20           #run for N seconds
SERVER_SETTLE_TIME = 5      #how long we wait for the server to start
TEST_COMMAND_SETTLE_TIME = 5    #how long we wait after starting the test command

XVNC_BIN = "/usr/bin/Xvnc"
XVNC_SERVER_START_COMMAND = [XVNC_BIN, "--rfbport=%s" % PORT,
                   "+extension", "GLX",
                   "--SecurityTypes=None",
                   "--SendCutText=0", "--AcceptCutText=0", "--AcceptPointerEvents=0", "--AcceptKeyEvents=0",
                   "-screen", "0", "1240x900x24",
                   ":%s" % DISPLAY_NO]
XVNC_SERVER_STOP_COMMAND = None     #stopped via kill
VNCVIEWER_BIN = "/usr/bin/vncviewer"
VNC_ENCODINGS = ["Tight", "ZRLE", "hextile", "raw", "auto"]
VNC_ZLIB_OPTIONS = [-1, 3, 6, 9]
VNC_ZLIB_OPTIONS = [-1, 9]
VNC_COMPRESSION_OPTIONS = [0, 3, 8, 9]
VNC_COMPRESSION_OPTIONS = [0, 3]
VNC_JPEG_OPTIONS = [-1, 0, 8]
VNC_JPEG_OPTIONS = [-1, 4]



XPRA_BIN = "/usr/bin/xpra"
XPRA_SERVER_START_COMMAND = [XPRA_BIN, "--no-daemon", "--bind-tcp=0.0.0.0:%s" % PORT,
                       "start", ":%s" % DISPLAY_NO,
                       "--xvfb=Xorg -nolisten tcp +extension GLX +extension RANDR +extension RENDER -logfile %s -config %s" % (XORG_LOG, XORG_CONFIG)]
XPRA_SERVER_STOP_COMMAND = [XPRA_BIN, "stop", ":%s" % DISPLAY_NO]
XPRA_TEST_ENCODINGS = ["png", "rgb24", "jpeg", "x264", "vpx", "mmap"]



def try_to_stop(process):
    if not process:
        return
    try:
        process.kill()
    except Exception, e:
        print("could not stop process %s: %s" % (process, e))

def getoutput(cmd):
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception, e:
        print("error running %s: %s" % (cmd, e))
        raise e
    (out,_) = process.communicate()
    code = process.poll()
    if code!=0:
        raise Exception("command '%s' returned error code %s" % (cmd, code))
    return out

def zero_iptables():
    cmds = [['iptables', '-Z', 'INPUT'], ['iptables', '-Z', 'OUTPUT']]
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
    user_pct = int(1000 * (new_utime - old_utime) / time_total_diff)/10.0
    sys_pct = int(1000 * (new_stime - old_stime) / time_total_diff)/10.0
    nthreads = int((int(old_pid_stat[19])+int(new_pid_stat[19]))/2)
    vsize = int(max(int(old_pid_stat[22]), int(new_pid_stat[22]))/1024/1024)
    rss = int(max(int(old_pid_stat[23]), int(new_pid_stat[23]))/1024)
    return [user_pct, sys_pct, nthreads, vsize, rss]

def getoutput_line(chain, pattern, setup_info):
    cmd = ["iptables", "-vnL", chain]
    out = getoutput(cmd)
    for line in out.splitlines():
        if line.find(pattern)>0:
            return  line
    raise Exception("no line found matching %s, make sure you have a rule like: %s" % (pattern, setup_info))

def parse_ipt(chain, pattern, setup_info):
    line = getoutput_line(chain, pattern, setup_info)
    parts = line.split()
    assert len(parts)>2
    def parse_num(part):
        U = 1024
        m = {"K":U, "M":U**2, "G":U**3}.get(part[-1], 1)
        num = "".join([x for x in part if x in "0123456789"])
        return int(num)*m
    return parse_num(parts[0]), parse_num(parts[1])

def get_input_count():
    setup = "iptables -I INPUT -p tcp --dport %s -j ACCEPT" % PORT
    return  parse_ipt("INPUT", "tcp dpt:%s" % PORT, setup)

def get_output_count():
    setup = "iptables -I OUTPUT -p tcp --sport %s -j ACCEPT" % PORT
    return  parse_ipt("OUTPUT", "tcp spt:%s" % PORT, setup)

def measure_client(server_pid, name, cmd):
    print("")
    print("starting %s: %s" % (name, cmd))
    client_process = subprocess.Popen(cmd)
    #give it time to settle down:
    time.sleep(SETTLE_TIME)
    code = client_process.poll()
    assert code is None, "client failed to start, return code is %s" % code
    #clear counters
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
    ni,isize = get_input_count()
    no,osize = get_output_count()
    #stop the process
    try_to_stop(client_process)
    time.sleep(1)
    code = client_process.poll()
    assert code is not None, "failed to stop client!"    
    #now collect the data
    client_process_data = compute_stat(new_time_total-old_time_total, old_pid_stat, new_pid_stat)
    if server_pid>0:
        server_process_data = compute_stat(new_time_total-old_time_total, old_server_pid_stat, new_server_pid_stat)
    else:
        server_process_data = []
    print("process_data (client/server): %s / %s" % (client_process_data, server_process_data))
    print("input/output on tcp port %s: %s / %s packets, %s / %s KBytes" % (PORT, ni, no, isize, osize))
    return [ni, isize, no, osize]+client_process_data+server_process_data

def with_server(start_server_command, stop_server_command, name_cmd):
    server_process = None
    test_command_process = None
    env = os.environ.copy()
    env["DISPLAY"] = ":%s" % DISPLAY_NO
    try:
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

        errors = 0
        results = {}
        for name, (compression, test_command, client_cmd) in name_cmd.items():
            test_command_process = None
            try:
                #start the test command:
                print("starting test command: %s" % str(test_command))
                test_command_process = subprocess.Popen(test_command, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                time.sleep(TEST_COMMAND_SETTLE_TIME)
                code = test_command_process.poll()
                assert code is None, "test command %s failed to start" % test_command
                results[name] = [compression]+measure_client(server_pid, name, client_cmd)
            except Exception, e:
                errors += 1
                print("error during client command run for %s: %s" % (name, e))
                import traceback
                traceback.print_stack()
                if errors>3:
                    print("too many errors, aborting tests")
                    break
            finally:
                print("stopping test command: %s" % test_command_process)
                try_to_stop(test_command_process)

    finally:
        print("")
        print("cleaning up")
        if START_SERVER:
            if stop_server_command:
                print("stopping server with: %s" % (stop_server_command))
                stop_process = subprocess.Popen(stop_server_command, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stop_process.wait()
            try_to_stop(server_process)
    return results
            

def test_xpra():
    print("")
    print("*********************************************************")
    print("                Xpra tests")
    print("")
    name_cmd = {}
    for x11_test_command in X11_TEST_COMMANDS:
        for encoding in XPRA_TEST_ENCODINGS:
            QUALITY = [-1]
            if encoding=="jpeg":
                QUALITY = [40, 80, 90]
            for jpeg_q in QUALITY:
                for compression in [0, 3, 9]:
                    cmd = [XPRA_BIN,
                           "attach", "tcp:%s:%s" % (IP, PORT),
                           "-z", str(compression), "--readonly"]
                    if encoding=="jpeg":
                        cmd.append("--jpeg-quality=%s" % jpeg_q)
                        name = "%s-%s" % (encoding, jpeg_q)
                    else:
                        name = encoding
                    if encoding!="mmap":
                        cmd.append("--no-mmap")
                        cmd.append("--encoding=%s" % encoding)
                    command_name = x11_test_command[0].split("/")[-1]
                    name_cmd["%s (%s - %s)" % (name, command_name, compression)] = (compression, x11_test_command, cmd)
    print("going to run %s tests: %s" % (len(name_cmd), name_cmd.keys()))
    return with_server(XPRA_SERVER_START_COMMAND, XPRA_SERVER_STOP_COMMAND, name_cmd)

def test_vnc():
    print("")
    print("*********************************************************")
    print("                VNC tests")
    print("")
    name_cmd = {}
    for x11_test_command in X11_TEST_COMMANDS:
        for encoding in VNC_ENCODINGS:
            for zlib in VNC_ZLIB_OPTIONS:
                for compression in VNC_COMPRESSION_OPTIONS:
                    jpeg_quality = [8]
                    if encoding=="Tight":
                        jpeg_quality = VNC_JPEG_OPTIONS
                    for jpegq in jpeg_quality:
                        cmd = [VNCVIEWER_BIN, "%s::%s" % (IP, PORT),
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
                        command_name = x11_test_command[0].split("/")[-1]
                        name = "vnc (%s - %s - %s - compression=%s - %s)" % (command_name, encoding, zlibtxt, compression, jpegtxt)
                        name_cmd[name] = (compression, x11_test_command, cmd)
    print("going to run %s tests: %s" % (len(name_cmd), name_cmd.keys()))
    return with_server(XVNC_SERVER_START_COMMAND, XVNC_SERVER_STOP_COMMAND, name_cmd)

def main():
    #before doing anything, check that the firewall is setup correctly:
    get_input_count()
    get_output_count()

    xpra_results = {}
    if TEST_XPRA:
        xpra_results = test_xpra()
    vnc_results = {}
    if TEST_VNC:
        vnc_results = test_vnc()
    print("")
    print("results:")
    headers = ["compression",
               "packets in", "packets in volume", "packets out", "packets out volume",
               "client user cpu_pct", "client system cpu pct", "client number of threads", "client vsize (MB)", "client rss (KB)",
               "server user cpu_pct", "server system cpu pct", "server number of threads", "server vsize (MB)", "server rss (KB)",
               ]
    print("encoding (compression): %s" % (", ".join(headers)))
    for name, data in xpra_results.items()+vnc_results.items():
        print "%s: %s" % (name, data)
    #self.client.send_ping()

if __name__ == "__main__":
    main()
