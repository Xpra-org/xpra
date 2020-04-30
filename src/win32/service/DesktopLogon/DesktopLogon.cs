using System;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using AxMSTSCLib;
//using System.Runtime.InteropServices;

namespace DesktopLogon
{
    public class DesktopLogon
    {
        private static int ErrorCode = -1;

        [DllExport]
        public static int getErrorCode()
        {
            return ErrorCode;
        }

        [DllExport]
        public static void Logon(string user, string password)
        {
            Console.WriteLine("Logon({0}, {1})", user, password);
            var domain = System.Environment.UserDomainName;
            var server = "localhost"; //System.Net.Dns.GetHostName();
            LogonEx(server, domain, user, password);
        }

        [DllExport]
        public static void LogonEx(string server, string domain, string user, string password)
        {
            Console.WriteLine("LogonEx({0}, {1}, {2}, {3})", server, domain, user, password);
            void ProcessTaskThread()
            {
                var form = new Form();
                form.Load += (sender, args) =>
                {
                    Console.WriteLine("Form.Load(..)");
                    var conn = new AxMSTSCLib.AxMsRdpClient9NotSafeForScripting();
                    form.Controls.Add(conn);
                    conn.Server = server;
                    conn.Domain = domain;
                    conn.UserName = user;
                    conn.AdvancedSettings9.ClearTextPassword = password;
                    conn.AdvancedSettings9.EnableCredSspSupport = true;
                    conn.OnDisconnected += OnDisconnected;
                    conn.OnLoginComplete += OnLoginComplete;
                    conn.OnLogonError += OnLogonError;
                    Console.WriteLine("RDP.Connect()");
                    conn.Connect();
                    conn.Enabled = false;
                    conn.Dock = DockStyle.Fill;
                    Console.WriteLine("Application.Run()");
                    Application.Run(form);
                };
                form.Show();
            }

            var rdpClientThread = new Thread(ProcessTaskThread) { IsBackground = true };
            rdpClientThread.SetApartmentState(ApartmentState.STA);
            rdpClientThread.Start();
            while (rdpClientThread.IsAlive && ErrorCode==-1)
            {
                Task.Delay(500).GetAwaiter().GetResult();
            }
            Console.WriteLine("RDP client thread ended");
        }

        private static void OnLogonError(object sender, IMsTscAxEvents_OnLogonErrorEvent e)
        {
            Console.WriteLine("OnLogonError: {0:D}", e.lError);
            ErrorCode = e.lError;
        }
        private static void OnLoginComplete(object sender, EventArgs e)
        {
            Console.WriteLine("OnLoginComplete");
            if (ErrorCode == -2)
            {
                Debug.WriteLine($"    ## New Session Detected ##");
                Task.Delay(10000).GetAwaiter().GetResult();
            }
            var rdpSession = (AxMsRdpClient9NotSafeForScripting)sender;
            rdpSession.Disconnect();
        }
        private static void OnDisconnected(object sender, IMsTscAxEvents_OnDisconnectedEvent e)
        {
            Console.WriteLine("OnDisconnected: {0:D}", e.discReason);
            if (ErrorCode == -1)
            {
                ErrorCode = e.discReason;
            }
            //Environment.Exit(ErrorCode);
        }
    }
}