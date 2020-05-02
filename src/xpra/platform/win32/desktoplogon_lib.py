#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import ctypes

# This definition of the error codes was found here:
# https://social.technet.microsoft.com/wiki/contents/articles/37870.remote-desktop-client-troubleshooting-disconnect-codes-and-reasons.aspx
ERROR_CODES = {
    0   : "No error",
    1   : "User-initiated client disconnect.",
    2   : "User-initiated client logoff.",
    3	: "Your Remote Desktop Services session has ended, possibly for one of the following reasons:  The administrator has ended the session. An error occurred while the connection was being established. A network problem occurred.  For help solving the problem, see \"Remote Desktop\" in Help and Support.",
    260	: "Remote Desktop can't find the computer "". This might mean that "" does not belong to the specified network.  Verify the computer name and domain that you are trying to connect to.",
    262	: "This computer can't connect to the remote computer.  Your computer does not have enough virtual memory available. Close your other programs, and then try connecting again. If the problem continues, contact your network administrator or technical support.",
    264	: "This computer can't connect to the remote computer.  The two computers couldn't connect in the amount of time allotted. Try connecting again. If the problem continues, contact your network administrator or technical support.",
    266	: "The smart card service is not running. Please start the smart card service and try again.",
    516	: "Remote Desktop can't connect to the remote computer for one of these reasons:  1) Remote access to the server is not enabled 2) The remote computer is turned off 3) The remote computer is not available on the network  Make sure the remote computer is turned on and connected to the network, and that remote access is enabled.",
    522	: "A smart card reader was not detected. Please attach a smart card reader and try again.",
    772	: "This computer can't connect to the remote computer.  The connection was lost due to a network error. Try connecting again. If the problem continues, contact your network administrator or technical support.",
    778	: "There is no card inserted in the smart card reader. Please insert your smart card and try again.",
    1030	: "Because of a security error, the client could not connect to the remote computer. Verify that you are logged on to the network, and then try connecting again.",
    1032	: "The specified computer name contains invalid characters. Please verify the name and try again.",
    1034	: "An error has occurred in the smart card subsystem. Please contact your helpdesk about this error.",
    1796	: "This computer can't connect to the remote computer.  Try connecting again. If the problem continues, contact the owner of the remote computer or your network administrator.",
    1800	: "Your computer could not connect to another console session on the remote computer because you already have a console session in progress.",
    2056	: "The remote computer disconnected the session because of an error in the licensing protocol. Please try connecting to the remote computer again or contact your server administrator.",
    2308	: "Your Remote Desktop Services session has ended.  The connection to the remote computer was lost, possibly due to network connectivity problems. Try connecting to the remote computer again. If the problem continues, contact your network administrator or technical support.",
    2311	: "The connection has been terminated because an unexpected server authentication certificate was received from the remote computer. Try connecting again. If the problem continues, contact the owner of the remote computer or your network administrator.",
    2312	: "A licensing error occurred while the client was attempting to connect (Licensing timed out). Please try connecting to the remote computer again.",
    2567	: "The specified username does not exist. Verify the username and try logging in again. If the problem continues, contact your system administrator or technical support.",
    2820	: "This computer can't connect to the remote computer.  An error occurred that prevented the connection. Try connecting again. If the problem continues, contact the owner of the remote computer or your network administrator.",
    2822	: "Because of an error in data encryption, this session will end. Please try connecting to the remote computer again.",
    2823	: "The user account is currently disabled and cannot be used. For assistance, contact your system administrator or technical support.",
    2825	: "The remote computer requires Network Level Authentication, which your computer does not support. For assistance, contact your system administrator or technical support.",
    3079	: "A user account restriction (for example, a time-of-day restriction) is preventing you from logging on. For assistance, contact your system administrator or technical support.",
    3080	: "The remote session was disconnected because of a decompression failure at the client side. Please try connecting to the remote computer again.",
    3335	: "As a security precaution, the user account has been locked because there were too many logon attempts or password change attempts. Wait a while before trying again, or contact your system administrator or technical support.",
    3337	: "The security policy of your computer requires you to type a password on the Windows Security dialog box. However, the remote computer you want to connect to cannot recognize credentials supplied using the Windows Security dialog box. For assistance, contact your system administrator or technical support.",
    3590	: "The client can't connect because it doesn't support FIPS encryption level.  Please lower the server side required security level Policy, or contact your network administrator for assistance",
    3591	: "This user account has expired. For assistance, contact your system administrator or technical support.",
    3592	: "Failed to reconnect to your remote session. Please try to connect again.",
    3593	: "The remote PC doesn't support Restricted Administration mode.",
    3847	: "This user account's password has expired. The password must change in order to logon. Please update the password or contact your system administrator or technical support.",
    3848	: "A connection will not be made because credentials may not be sent to the remote computer. For assistance, contact your system administrator.",
    4103	: "The system administrator has restricted the times during which you may log in. Try logging in later. If the problem continues, contact your system administrator or technical support.",
    4104	: "The remote session was disconnected because your computer is running low on video resources.  Close your other programs, and then try connecting again. If the problem continues, contact your network administrator or technical support.",
    4359	: "The system administrator has limited the computers you can log on with. Try logging on at a different computer. If the problem continues, contact your system administrator or technical support.",
    4615	: "You must change your password before logging on the first time. Please update your password or contact your system administrator or technical support.",
    4871	: "The system administrator has restricted the types of logon (network or interactive) that you may use. For assistance, contact your system administrator or technical support.",
    5127	: "The Kerberos sub-protocol User2User is required. For assistance, contact your system administrator or technical support.",
    6919	: "Remote Desktop cannot connect to the remote computer because the authentication certificate received from the remote computer is expired or invalid.  In some cases, this error might also be caused by a large time discrepancy between the client and server computers.",
    7431	: "Remote Desktop cannot verify the identity of the remote computer because there is a time or date difference between your computer and the remote computer. Make sure your computer's clock is set to the correct time, and then try connecting again. If the problem occurs again, contact your network administrator or the owner of the remote computer.",
    8711	: "Your computer can't connect to the remote computer because your smart card is locked out. Contact your network administrator about unlocking your smart card or resetting your PIN.",
    9479	: "Could not auto-reconnect to your applications,please re-launch your applications",
    9732	: "Client and server versions do not match. Please upgrade your client software and then try connecting again.",
    33554433	: "Failed to reconnect to the remote program. Please restart the remote program.",
    33554434	: "The remote computer does not support RemoteApp. For assistance, contact your system administrator.",
    50331649	: "Your computer can't connect to the remote computer because the username or password is not valid. Type a valid user name and password.",
    50331650	: "Your computer can't connect to the remote computer because it can't verify the certificate revocation list. Contact your network administrator for assistance.",
    50331651	: "Your computer can't connect to the remote computer due to one of the following reasons:  1) The requested Remote Desktop Gateway server address and the server SSL certificate subject name do not match. 2) The certificate is expired or revoked. 3) The certificate root authority does not trust the certificate.  Contact your network administrator for assistance.",
    50331652	: "Your computer can't connect to the remote computer because the SSL certificate was revoked by the certification authority. Contact your network administrator for assistance.",
    50331653	: "This computer can't verify the identity of the RD Gateway "". It's not safe to connect to servers that can't be identified. Contact your network administrator for assistance.",
    50331654	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server address requested and the certificate subject name do not match. Contact your network administrator for assistance.",
    50331655	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server's certificate has expired or has been revoked. Contact your network administrator for assistance.",
    50331656	: "Your computer can't connect to the remote computer because an error occurred on the remote computer that you want to connect to. Contact your network administrator for assistance.",
    50331657	: "An error occurred while sending data to the Remote Desktop Gateway server. The server is temporarily unavailable or a network connection is down. Try again later, or contact your network administrator for assistance.",
    50331658	: "An error occurred while receiving data from the Remote Desktop Gateway server. Either the server is temporarily unavailable or a network connection is down. Try again later, or contact your network administrator for assistance.",
    50331659	: "Your computer can't connect to the remote computer because an alternate logon method is required. Contact your network administrator for assistance.",
    50331660	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server address is unreachable or incorrect. Type a valid Remote Desktop Gateway server address.",
    50331661	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server is temporarily unavailable. Try reconnecting later or contact your network administrator for assistance.",
    50331662	: "Your computer can't connect to the remote computer because the Remote Desktop Services client component is missing or is an incorrect version. Verify that setup was completed successfully, and then try reconnecting later.",
    50331663	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server is running low on server resources and is temporarily unavailable. Try reconnecting later or contact your network administrator for assistance.",
    50331664	: "Your computer can't connect to the remote computer because an incorrect version of rpcrt4.dll has been detected. Verify that all components for Remote Desktop Gateway client were installed correctly.",
    50331665	: "Your computer can't connect to the remote computer because no smart card service is installed. Install a smart card service and then try again, or contact your network administrator for assistance.",
    50331666	: "Your computer can't stay connected to the remote computer because the smart card has been removed. Try again using a valid smart card, or contact your network administrator for assistance.",
    50331667	: "Your computer can't connect to the remote computer because no smart card is available. Try again using a smart card.",
    50331668	: "Your computer can't stay connected to the remote computer because the smart card has been removed. Reinsert the smart card and then try again.",
    50331669	: "Your computer can't connect to the remote computer because the user name or password is not valid. Please type a valid user name and password.",
    50331671	: "Your computer can't connect to the remote computer because a security package error occurred in the transport layer. Retry the connection or contact your network administrator for assistance.",
    50331672	: "The Remote Desktop Gateway server has ended the connection. Try reconnecting later or contact your network administrator for assistance.",
    50331673	: "The Remote Desktop Gateway server administrator has ended the connection. Try reconnecting later or contact your network administrator for assistance.",
    50331674	: "Your computer can't connect to the remote computer due to one of the following reasons:   1) Your credentials (the combination of user name, domain, and password) were incorrect. 2) Your smart card was not recognized.",
    50331675	: "Remote Desktop can't connect to the remote computer "" for one of these reasons:  1) Your user account is not listed in the RD Gateway's permission list 2) You might have specified the remote computer in NetBIOS format (for example, computer1), but the RD Gateway is expecting an FQDN or IP address format (for example, computer1.fabrikam.com or 157.60.0.1).  Contact your network administrator for assistance.",
    50331676	: "Remote Desktop can't connect to the remote computer "" for one of these reasons:  1) Your user account is not authorized to access the RD Gateway "" 2) Your computer is not authorized to access the RD Gateway "" 3) You are using an incompatible authentication method (for example, the RD Gateway might be expecting a smart card but you provided a password)  Contact your network administrator for assistance.",
    50331679	: "Your computer can't connect to the remote computer because your network administrator has restricted access to this RD Gateway server. Contact your network administrator for assistance.",
    50331680	: "Your computer can't connect to the remote computer because the web proxy server requires authentication. To allow unauthenticated traffic to an RD Gateway server through your web proxy server, contact your network administrator.",
    50331681	: "Your computer can't connect to the remote computer because your password has expired or you must change the password. Please change the password or contact your network administrator or technical support for assistance.",
    50331682	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server reached its maximum allowed connections. Try reconnecting later or contact your network administrator for assistance.",
    50331683	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server does not support the request. Contact your network administrator for assistance.",
    50331684	: "Your computer can't connect to the remote computer because the client does not support one of the Remote Desktop Gateway's capabilities. Contact your network administrator for assistance.",
    50331685	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server and this computer are incompatible. Contact your network administrator for assistance.",
    50331686	: "Your computer can't connect to the remote computer because the credentials used are not valid. Insert a valid smart card and type a PIN or password, and then try connecting again.",
    50331687	: "Your computer can't connect to the remote computer because your computer or device did not pass the Network Access Protection requirements set by your network administrator. Contact your network administrator for assistance.",
    50331688	: "Your computer can't connect to the remote computer because no certificate was configured to use at the Remote Desktop Gateway server. Contact your network administrator for assistance.",
    50331689	: "Your computer can't connect to the remote computer because the RD Gateway server that you are trying to connect to is not allowed by your computer administrator. If you are the administrator, add this Remote Desktop Gateway server name to the trusted Remote Desktop Gateway server list on your computer and then try connecting again.",
    50331690	: "Your computer can't connect to the remote computer because your computer or device did not meet the Network Access Protection requirements set by your network administrator, for one of the following reasons:  1) The Remote Desktop Gateway server name and the server's public key certificate subject name do not match. 2) The certificate has expired or has been revoked. 3) The certificate root authority does not trust the certificate. 4) The certificate key extension does not support encryption. 5) Your computer cannot verify the certificate revocation list.  Contact your network administrator for assistance.",
    50331691	: "Your computer can't connect to the remote computer because a user name and password are required to authenticate to the Remote Desktop Gateway server instead of smart card credentials.",
    50331692	: "Your computer can't connect to the remote computer because smart card credentials are required to authenticate to the Remote Desktop Gateway server instead of a user name and password.",
    50331693	: "Your computer can't connect to the remote computer because no smart card reader is detected. Connect a smart card reader and then try again, or contact your network administrator for assistance.",
    50331695	: "Your computer can't connect to the remote computer because authentication to the firewall failed due to missing firewall credentials. To resolve the issue, go to the firewall website that your network administrator recommends, and then try the connection again, or contact your network administrator for assistance.",
    50331696	: "Your computer can't connect to the remote computer because authentication to the firewall failed due to invalid firewall credentials. To resolve the issue, go to the firewall website that your network administrator recommends, and then try the connection again, or contact your network administrator for assistance.",
    50331698	: "Your Remote Desktop Services session ended because the remote computer didn't receive any input from you.",
    50331699	: "The connection has been disconnected because the session timeout limit was reached.",
    50331700	: "Your computer can't connect to the remote computer because an invalid cookie was sent to the Remote Desktop Gateway server. Contact your network administrator for assistance.",
    50331701	: "Your computer can't connect to the remote computer because the cookie was rejected by the Remote Desktop Gateway server. Contact your network administrator for assistance.",
    50331703	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway server is expecting an authentication method different from the one attempted. Contact your network administrator for assistance.",
    50331704	: "The RD Gateway connection ended because periodic user authentication failed. Try reconnecting with a correct user name and password. If the reconnection fails, contact your network administrator for further assistance.",
    50331705	: "The RD Gateway connection ended because periodic user authorization failed. Try reconnecting with a correct user name and password. If the reconnection fails, contact your network administrator for further assistance.",
    50331707	: "Your computer can't connect to the remote computer because the Remote Desktop Gateway and the remote computer are unable to exchange policies. This could happen due to one of the following reasons:     1. The remote computer is not capable of exchanging policies with the Remote Desktop Gateway.     2. The remote computer's configuration does not permit a new connection.     3. The connection between the Remote Desktop Gateway and the remote computer ended.    Contact your network administrator for assistance.",
    50331708	: "Your computer can't connect to the remote computer, possibly because the smart card is not valid, the smart card certificate was not found in the certificate store, or the Certificate Propagation service is not running. Contact your network administrator for assistance.",
    50331709	: "To use this program or computer, first log on to the following website: <a href=""></a>.",
    50331710	: "To use this program or computer, you must first log on to an authentication website. Contact your network administrator for assistance.",
    50331711	: "Your session has ended. To continue using the program or computer, first log on to the following website: <a href=""></a>.",
    50331712	: "Your session has ended. To continue using the program or computer, you must first log on to an authentication website. Contact your network administrator for assistance.",
    50331713	: "The RD Gateway connection ended because periodic user authorization failed. Your computer or device didn't pass the Network Access Protection (NAP) requirements set by your network administrator. Contact your network administrator for assistance.",
    50331714	: "Your computer can't connect to the remote computer because the size of the cookie exceeded the supported size. Contact your network administrator for assistance.",
    50331716	: "Your computer can't connect to the remote computer using the specified forward proxy configuration. Contact your network administrator for assistance.",
    50331717	: "This computer cannot connect to the remote resource because you do not have permission to this resource. Contact your network administrator for assistance.",
    50331718	: "There are currently no resources available to connect to. Retry the connection or contact your network administrator.",
    50331719	: "An error occurred while Remote Desktop Connection was accessing this resource. Retry the connection or contact your system administrator.",
    50331721	: "Your Remote Desktop Client needs to be updated to the newest version. Contact your system administrator for help installing the update, and then try again.",
    50331722	: "Your network configuration doesn't allow the necessary HTTPS ports. Contact your network administrator for help allowing those ports or disabling the web proxy, and then try connecting again.",
    50331723	: "We're setting up more resources, and it might take a few minutes. Please try again later.",
    50331724	: "The user name you entered does not match the user name used to subscribe to your applications. If you wish to sign in as a different user please choose Sign Out from the Home menu.",
    50331725	: "Looks like there are too many users trying out the Azure RemoteApp service at the moment. Please wait a few minutes and then try again.",
    50331726	: "Maximum user limit has been reached. Please contact your administrator for further assistance.",
    50331727	: "Your trial period for Azure RemoteApp has expired. Ask your admin or tech support for help.",
    50331728	: "You no longer have access to Azure RemoteApp. Ask your admin or tech support for help.}",
    }

def Logon(username, password):
    #sys.path.insert(0, "E:\\DesktopLogon\\")
    #desktop_logon = ctypes.cdll.LoadLibrary("E:\\DesktopLogon\\DesktopLogon.dll")
    desktop_logon = ctypes.cdll.LoadLibrary("DesktopLogon.dll")
    desktop_logon.Logon(username, password)
    r = desktop_logon.getErrorCode()
    if r:
        from xpra.log import Logger
        log = Logger("win32")
        log.warn("Logon(..) error %i : '%s'", r, ERROR_CODES.get(r, "unknown error"))

def main():
    Logon(b"Windows 10 Test", b"win10test")

if __name__ == "__main__":
    sys.exit(main())
