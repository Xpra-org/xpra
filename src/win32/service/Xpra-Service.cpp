/**
 * This file is part of Xpra.
 * Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
 *
 * This service code is based on "The Complete Service Sample":
 * https://msdn.microsoft.com/en-us/library/bb540476(v=VS.85).aspx
 */

#include <windows.h>
#include <tchar.h>
#undef __CRT__NO_INLINE
#include <strsafe.h>
#include "event_log.h"

#pragma comment(lib, "advapi32.lib")

#define SVCNAME TEXT("Xpra")

const char* LOG_NAME = "Xpra";

SERVICE_STATUS          gSvcStatus;
SERVICE_STATUS_HANDLE   gSvcStatusHandle;
HANDLE                  ghSvcStopEvent = NULL;

VOID SvcInstall(void);
VOID WINAPI SvcCtrlHandler(DWORD);
VOID WINAPI SvcMain(DWORD, LPTSTR *);

VOID ReportSvcStatus(DWORD, DWORD, DWORD);
VOID SvcInit(DWORD, LPTSTR *);
VOID SvcReportEvent(LPTSTR);


int __cdecl main(int argc, TCHAR *argv[])
{
    if (lstrcmpi(argv[1], TEXT("install")) == 0)
    {
        SvcInstall();
        return 0;
    }

    // TO_DO: Add any additional services for the process to this table.
    SERVICE_TABLE_ENTRY DispatchTable[] =
    {
        { SVCNAME, (LPSERVICE_MAIN_FUNCTION) SvcMain },
        { NULL, NULL }
    };

    // This call returns when the service has stopped.
    // The process should simply terminate when the call returns.
    if (!StartServiceCtrlDispatcher(DispatchTable))
    {
        SvcReportEvent(TEXT("StartServiceCtrlDispatcher"));
    }
    return 0;
}

VOID SvcInstall() {
    SC_HANDLE schSCManager;
    SC_HANDLE schService;
    TCHAR szPath[MAX_PATH];

    if (!GetModuleFileName(NULL, szPath, MAX_PATH))
    {
        printf("Cannot install service (%d)\n", GetLastError());
        return;
    }

    // Get a handle to the SCM database.
    schSCManager = OpenSCManager(NULL, NULL, SC_MANAGER_ALL_ACCESS);
    if (schSCManager==NULL)
    {
        printf("OpenSCManager failed (%d)\n", GetLastError());
        return;
    }

    schService = CreateService(
        schSCManager,              // SCM database
        SVCNAME,                   // name of service
        SVCNAME,                   // service name to display
        SERVICE_ALL_ACCESS,        // desired access
        SERVICE_WIN32_OWN_PROCESS, // service type
        SERVICE_DEMAND_START,      // start type
        SERVICE_ERROR_NORMAL,      // error control type
        szPath,                    // path to service's binary
        NULL,                      // no load ordering group
        NULL,                      // no tag identifier
        NULL,                      // no dependencies
        NULL,                      // LocalSystem account
        NULL);                     // no password

    if (schService==NULL)
    {
        printf("CreateService failed (%d)\n", GetLastError());
        CloseServiceHandle(schSCManager);
        return;
    }
    else
    {
    	printf("Service installed successfully\n");
    }
    CloseServiceHandle(schService);
    CloseServiceHandle(schSCManager);
}

//
// Purpose:
//   Entry point for the service
//
// Parameters:
//   dwArgc - Number of arguments in the lpszArgv array
//   lpszArgv - Array of strings. The first string is the name of
//     the service and subsequent strings are passed by the process
//     that called the StartService function to start the service.
//
// Return value:
//   None.
//
VOID WINAPI SvcMain(DWORD dwArgc, LPTSTR *lpszArgv)
{
    gSvcStatusHandle = RegisterServiceCtrlHandler(SVCNAME, SvcCtrlHandler);
    if (!gSvcStatusHandle)
    {
        SvcReportEvent(TEXT("RegisterServiceCtrlHandler"));
        return;
    }
    // These SERVICE_STATUS members remain as set here
    gSvcStatus.dwServiceType = SERVICE_WIN32_OWN_PROCESS;
    gSvcStatus.dwServiceSpecificExitCode = 0;   

    // Report initial status to the SCM
    ReportSvcStatus(SERVICE_START_PENDING, NO_ERROR, 3000);

    // Perform service-specific initialization and work.
    SvcInit(dwArgc, lpszArgv);
}

//
// Purpose:
//   The service code
//
// Parameters:
//   dwArgc - Number of arguments in the lpszArgv array
//   lpszArgv - Array of strings. The first string is the name of
//     the service and subsequent strings are passed by the process
//     that called the StartService function to start the service.
//
// Return value:
//   None
//
VOID SvcInit(DWORD dwArgc, LPTSTR *lpszArgv)
{
	HANDLE event_log = RegisterEventSource(NULL, LOG_NAME);

	// Create an event. The control handler function, SvcCtrlHandler,
    // signals this event when it receives the stop control code.
    ghSvcStopEvent = CreateEvent(NULL, TRUE, FALSE, NULL);
    if (ghSvcStopEvent==NULL)
    {
        ReportSvcStatus(SERVICE_STOPPED, NO_ERROR, 0);
        return;
    }

    STARTUPINFO si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));   

	char buf[64];
	const char* message = "Going to start Xpra shadow";
	ReportEvent(event_log, EVENTLOG_SUCCESS, 0, 0, NULL, 1, 0, &message, NULL);

    //LPTSTR command = "\"E:\\Xpra\\trunk\\src\\dist\\Xpra_cmd.exe\" proxy --bind-tcp=0.0.0.0:14500";
    //LPCTSTR cwd = "E:\\Xpra\\trunk\\src\\dist\\";
    //TODO add SSL: --tcp-auth=sys --ssl-cert=""{commonappdata}\Xpra\ssl-cert.pem"";
    LPTSTR command = "\"C:\\Program Files\\Xpra\\Xpra-Proxy.exe\" proxy --bind-tcp=0.0.0.0:14500 --tcp-auth=sys";
    LPCTSTR cwd = "C:\\Program Files\\Xpra\\";
    if (!CreateProcess(NULL, command, NULL, NULL, FALSE, 0, NULL, cwd, &si, &pi))
    {
    	snprintf(buf, 64, "CreateProcess failed (%d).\n", GetLastError());
    	message = (const char*) &buf;
    	ReportEvent(event_log, EVENTLOG_ERROR_TYPE, 0, 0, NULL, 1, 0, &message, NULL);
        DeregisterEventSource(event_log);

        ReportSvcStatus(SERVICE_STOPPED, 1, 0);
        return;
    }

	snprintf(buf, 64, "Xpra shadow started with pid=%d.\n", pi.dwProcessId);
	message = (const char*) &buf;
	ReportEvent(event_log, EVENTLOG_SUCCESS, 0, 0, NULL, 1, 0, &message, NULL);
    ReportSvcStatus( SERVICE_RUNNING, NO_ERROR, 0 );

    while (1)
    {
        WaitForSingleObject(ghSvcStopEvent, INFINITE);

    	message = "Xpra shadow asked to close";
    	ReportEvent(event_log, EVENTLOG_SUCCESS, 0, 0, NULL, 1, 0, &message, NULL);
        PostMessage((HWND) pi.hProcess, WM_CLOSE, 0, 0);
        Sleep(1*1000);
        PostMessage((HWND) pi.hProcess, WM_QUIT, 0, 0);
        Sleep(1*1000);
        PostMessage((HWND) pi.hProcess, WM_DESTROY, 0, 0);

        Sleep(2*1000);

    	message = "Xpra shadow forced to terminate";
    	ReportEvent(event_log, EVENTLOG_SUCCESS, 0, 0, NULL, 1, 0, &message, NULL);
        DeregisterEventSource(event_log);
        TerminateProcess(pi.hProcess, 0);

        ReportSvcStatus( SERVICE_STOPPED, NO_ERROR, 0 );
        return;
    }
}

//
// Purpose:
//   Sets the current service status and reports it to the SCM.
//
// Parameters:
//   dwCurrentState - The current state (see SERVICE_STATUS)
//   dwWin32ExitCode - The system error code
//   dwWaitHint - Estimated time for pending operation,
//     in milliseconds
//
// Return value:
//   None
//
VOID ReportSvcStatus( DWORD dwCurrentState,
                      DWORD dwWin32ExitCode,
                      DWORD dwWaitHint)
{
    static DWORD dwCheckPoint = 1;

    // Fill in the SERVICE_STATUS structure.

    gSvcStatus.dwCurrentState = dwCurrentState;
    gSvcStatus.dwWin32ExitCode = dwWin32ExitCode;
    gSvcStatus.dwWaitHint = dwWaitHint;

    if (dwCurrentState == SERVICE_START_PENDING)
    {
        gSvcStatus.dwControlsAccepted = 0;
    }
    else {
    	gSvcStatus.dwControlsAccepted = SERVICE_ACCEPT_STOP;
    }

    if ((dwCurrentState==SERVICE_RUNNING) || (dwCurrentState == SERVICE_STOPPED))
    {
        gSvcStatus.dwCheckPoint = 0;
    }
    else 
	{
    	gSvcStatus.dwCheckPoint = dwCheckPoint++;
	}
    // Report the status of the service to the SCM.
    SetServiceStatus( gSvcStatusHandle, &gSvcStatus );
}

//
// Purpose:
//   Called by SCM whenever a control code is sent to the service
//   using the ControlService function.
//
// Parameters:
//   dwCtrl - control code
//
// Return value:
//   None
//
VOID WINAPI SvcCtrlHandler( DWORD dwCtrl )
{
   switch(dwCtrl)
   { 
      case SERVICE_CONTROL_STOP:
         ReportSvcStatus(SERVICE_STOP_PENDING, NO_ERROR, 0);
         SetEvent(ghSvcStopEvent);
         ReportSvcStatus(gSvcStatus.dwCurrentState, NO_ERROR, 0);
         return;

      case SERVICE_CONTROL_INTERROGATE:
         break;

      default:
         break;
   }
}

//
// Purpose:
//   Logs messages to the event log
//
// Parameters:
//   szFunction - name of function that failed
//
// Return value:
//   None
//
// Remarks:
//   The service must have an entry in the Application event log.
//
VOID SvcReportEvent(LPTSTR szFunction)
{
    HANDLE hEventSource;
    LPCTSTR lpszStrings[2];
    TCHAR Buffer[80];

    hEventSource = RegisterEventSource(NULL, SVCNAME);

    if( NULL != hEventSource )
    {
        StringCchPrintf(Buffer, 80, TEXT("%s failed with %d"), szFunction, GetLastError());

        lpszStrings[0] = SVCNAME;
        lpszStrings[1] = Buffer;

        ReportEvent(hEventSource,        // event log handle
                    EVENTLOG_ERROR_TYPE, // event type
                    0,                   // event category
                    SVC_ERROR,           // event identifier
                    NULL,                // no security identifier
                    2,                   // size of lpszStrings array
                    0,                   // no binary data
                    lpszStrings,         // array of strings
                    NULL);               // no binary data

        DeregisterEventSource(hEventSource);
    }
}
