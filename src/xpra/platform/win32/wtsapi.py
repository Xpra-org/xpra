#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import POINTER, WinDLL, c_void_p, Structure, c_int
from ctypes import byref, cast, sizeof
from ctypes.wintypes import WORD, DWORD, HANDLE, BOOL, LPSTR
from xpra.util import print_nested_dict

PDWORD = POINTER(DWORD)

wtsapi32 = WinDLL("WtsApi32")

NOTIFY_FOR_THIS_SESSION = 0

WTS_CURRENT_SERVER_HANDLE = 0

#no idea where we're supposed to get those from:
WM_WTSSESSION_CHANGE        = 0x02b1
WM_DWMNCRENDERINGCHANGED    = 0x031F
WM_DWMCOMPOSITIONCHANGED    = 0x031E

class WTS_SESSION_INFOA(Structure):
    _fields_ = [
        ("SessionId",       DWORD),
        ("pWinStationName", LPSTR),
        ("State",           c_int),
    ]
class WTS_CLIENT_DISPLAY(Structure):
    _fields_ = [
        ("HorizontalResolution",    DWORD),
        ("VerticalResolution",      DWORD),
        ("ColorDepth",              DWORD),
        ]
PWTS_SESSION_INFOA = POINTER(WTS_SESSION_INFOA)
PPWTS_SESSION_INFOA = POINTER(PWTS_SESSION_INFOA)
WTSActive       = 0
WTSConnected    = 1
WTSConnectQuery = 2
WTSShadow       = 3
WTSDisconnected = 4
WTSIdle         = 5
WTSListen       = 6
WTSReset        = 7
WTSDown         = 8
WTSInit         = 9
CONNECT_STATE = {
    WTSActive       : "Active",
    WTSConnected    : "Connected",
    WTSConnectQuery : "ConnectQuery",
    WTSShadow       : "Shadow",
    WTSDisconnected : "Disconnected",
    WTSIdle         : "Idle",
    WTSListen       : "Listen",
    WTSReset        : "Reset",
    WTSDown         : "Down",
    WTSInit         : "Init",
    }
WTSInitialProgram          = 0
WTSApplicationName         = 1
WTSWorkingDirectory        = 2
WTSOEMId                   = 3
WTSSessionId               = 4
WTSUserName                = 5
WTSWinStationName          = 6
WTSDomainName              = 7
WTSConnectState            = 8
WTSClientBuildNumber       = 9
WTSClientName              = 10
WTSClientDirectory         = 11
WTSClientProductId         = 12
WTSClientHardwareId        = 13
WTSClientAddress           = 14
WTSClientDisplay           = 15
WTSClientProtocolType      = 16
WTSIdleTime                = 17
WTSLogonTime               = 18
WTSIncomingBytes           = 19
WTSOutgoingBytes           = 20
WTSIncomingFrames          = 21
WTSOutgoingFrames          = 22
WTSClientInfo              = 23
WTSSessionInfo             = 24
WTSSessionInfoEx           = 25
WTSConfigInfo              = 26
WTSValidationInfo          = 27
WTSSessionAddressV4        = 28
WTSIsRemoteSession         = 29
WTS_INFO_CLASS = {
    WTSInitialProgram       : "InitialProgram",
    WTSApplicationName      : "ApplicationName",
    WTSWorkingDirectory     : "WorkingDirectory",
    WTSOEMId                : "OEMId",
    WTSSessionId            : "SessionId",
    WTSUserName             : "UserName",
    WTSWinStationName       : "WinStationName",
    WTSDomainName           : "DomainName",
    WTSConnectState         : "ConnectState",
    WTSClientBuildNumber    : "ClientBuildNumber",
    WTSClientName           : "ClientName",
    WTSClientDirectory      : "ClientDirectory",
    WTSClientProductId      : "ClientProductId",
    WTSClientHardwareId     : "ClientHardwareId",
    WTSClientAddress        : "ClientAddress",
    WTSClientDisplay        : "ClientDisplay",
    WTSClientProtocolType   : "ClientProtocolType",
    WTSIdleTime             : "IdleTime",
    WTSLogonTime            : "LogonTime",
    WTSIncomingBytes        : "IncomingBytes",
    WTSOutgoingBytes        : "OutgoingBytes",
    WTSIncomingFrames       : "IncomingFrames",
    WTSOutgoingFrames       : "OutgoingFrames",
    WTSClientInfo           : "ClientInfo",
    WTSSessionInfo          : "SessionInfo",
    WTSSessionInfoEx        : "SessionInfoEx",
    WTSConfigInfo           : "ConfigInfo",
    WTSValidationInfo       : "ValidationInfo",
    WTSSessionAddressV4     : "SessionAddressV4",
    WTSIsRemoteSession      : "IsRemoteSession",
    }
WTSRegisterSessionNotification = wtsapi32.WTSRegisterSessionNotification
WTSRegisterSessionNotification.restype = BOOL
WTSRegisterSessionNotification.argtypes = [HANDLE, DWORD]
WTSUnRegisterSessionNotification = wtsapi32.WTSUnRegisterSessionNotification
WTSUnRegisterSessionNotification.restype = BOOL
WTSUnRegisterSessionNotification.argtypes = [HANDLE]
WTSOpenServerA = wtsapi32.WTSOpenServerA
WTSOpenServerA.restype = HANDLE
WTSOpenServerA.argtypes = [LPSTR]
WTSCloseServer = wtsapi32.WTSCloseServer
WTSCloseServer.restype = BOOL
WTSCloseServer.argtypes = [HANDLE]
WTSQuerySessionInformationA = wtsapi32.WTSQuerySessionInformationA
WTSQuerySessionInformationA.restype = BOOL
WTSQuerySessionInformationA.argtypes = [HANDLE, DWORD, c_int, POINTER(LPSTR), POINTER(DWORD)]
WTSFreeMemory = wtsapi32.WTSFreeMemory
WTSFreeMemory.restype = BOOL
#WTSFreeMemory.argtypes = [PVOID]
WTSEnumerateSessionsA = wtsapi32.WTSEnumerateSessionsA
WTSEnumerateSessionsA.restype = BOOL
WTSEnumerateSessionsA.argtypes = [HANDLE, DWORD, DWORD, PPWTS_SESSION_INFOA, PDWORD]
WTS_CURRENT_SERVER_HANDLE = 0
WTSEnumerateProcessesExA = wtsapi32.WTSEnumerateProcessesExA
WTSEnumerateProcessesExA.restype = BOOL
WTSEnumerateProcessesExA.argtypes = [HANDLE, PDWORD, DWORD, POINTER(LPSTR), PDWORD]

WTSDisconnectSession = wtsapi32.WTSDisconnectSession
WTSDisconnectSession.restype = BOOL
WTSDisconnectSession.argtypes = [HANDLE, DWORD, BOOL]
WTSLogoffSession = wtsapi32.WTSLogoffSession
WTSLogoffSession.restype = BOOL
WTSLogoffSession.argtypes = [HANDLE, DWORD, BOOL]
WTSSendMessageA = wtsapi32.WTSSendMessageA
WTSSendMessageA.restype = BOOL
WTSSendMessageA.argtypes = [HANDLE, DWORD, LPSTR, DWORD, LPSTR, DWORD, DWORD, DWORD, POINTER(DWORD), BOOL]
WTSShutdownSystem = wtsapi32.WTSShutdownSystem
WTSShutdownSystem.restype = BOOL
WTSShutdownSystem.argtypes = [HANDLE, DWORD]
WTSTerminateProcess = wtsapi32.WTSTerminateProcess
WTSTerminateProcess.restype = BOOL
WTSTerminateProcess.argtypes = [HANDLE, DWORD, DWORD]

#WTSVirtualChannelOpen
#WTSWaitSystemEvent


def get_session_info(session):
    info = {
        "StationName"  : session.pWinStationName.decode("latin1"),
        "State"         : CONNECT_STATE.get(session.State, session.State),
        }
    csid = session.SessionId
    buf = LPSTR()
    size = DWORD()
    for q in (WTSInitialProgram, WTSApplicationName, WTSWorkingDirectory,
              WTSUserName, WTSDomainName,
              WTSClientName, WTSClientDirectory,
              ):
        if WTSQuerySessionInformationA(WTS_CURRENT_SERVER_HANDLE, csid, q, byref(buf), byref(size)):
            if buf.value:
                try:
                    info[WTS_INFO_CLASS.get(q, q)] = buf.value.decode("latin1")
                except:
                    pass
    if WTSQuerySessionInformationA(WTS_CURRENT_SERVER_HANDLE, csid, WTSClientDisplay, byref(buf), byref(size)):
        if size.value>=sizeof(WTS_CLIENT_DISPLAY):
            pdisplay = cast(buf, POINTER(WTS_CLIENT_DISPLAY))
            display = pdisplay[0]
            if display.HorizontalResolution>0 and display.VerticalResolution>0 and display.ColorDepth>0:
                info["Display"] = {
                    "Width"     : display.HorizontalResolution,
                    "Height"    : display.VerticalResolution,
                    "Depth"     : display.ColorDepth,
                    }
    #if WTSQuerySessionInformationA(WTS_CURRENT_SERVER_HANDLE, csid, WTSConnectState, byref(buf), byref(size)):
    #    if size.value==4:
    #        state = cast(buf, POINTER(DWORD)).contents.value
    #        info["ConnectState"] = CONNECT_STATE.get(state, state)
    if WTSQuerySessionInformationA(WTS_CURRENT_SERVER_HANDLE, csid, WTSClientProtocolType, byref(buf), byref(size)):
        if size.value==2:
            ptype = cast(buf, POINTER(WORD)).contents.value
            info["Type"] = {0:"console", 1:"legacy", 2:"RDP"}.get(ptype, ptype)
    return info

def get_sessions():
    cur = LPSTR(WTS_CURRENT_SERVER_HANDLE)
    h = WTSOpenServerA(cur)
    if not h:
        return {}
    session_info = PWTS_SESSION_INFOA()
    count = DWORD()
    sessions = {}
    if WTSEnumerateSessionsA(h, 0, 1, byref(session_info), byref(count)):
        for i in range(count.value):
            session = session_info[i]
            sessions[session.SessionId] = get_session_info(session)
        WTSFreeMemory(session_info)
    WTSCloseServer(h)
    return sessions

def find_session(username, with_display=True):
    if username:
        for sid, info in get_sessions().items():
            if with_display and not info.get("Display"):
                continue
            if info.get("UserName", "").lower()==username.lower():
                info["SessionID"] = sid
                return info
    return None



def main():
    import sys
    from xpra.platform.win32.common import WTSGetActiveConsoleSessionId
    csid = WTSGetActiveConsoleSessionId()
    print("WTSGetActiveConsoleSessionId()=%s" % csid)
    print_nested_dict(get_sessions())
    if len(sys.argv)>1:
        for x in sys.argv[1:]:
            print("find_session(%s)=%s" % (x, find_session(x)))

if __name__=='__main__':
    main()
