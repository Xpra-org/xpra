# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#!python
#cython: boundscheck=False, wraparound=False, cdivision=True

import os
import time

from xpra.log import Logger
log = Logger("util")


from posix.types cimport gid_t, pid_t, off_t, uid_t

cdef extern from "errno.h" nogil:
    int errno

cdef extern from "pwd.h":
    struct passwd:
        char   *pw_name         #username
        char   *pw_passwd       #user password
        uid_t   pw_uid          #user ID
        gid_t   pw_gid          #group ID
        char   *pw_gecos        #user information
        char   *pw_dir          #home directory
        char   *pw_shell        #shell program
    passwd *getpwuid(uid_t uid)

cdef extern from "pam_misc.h":
    ctypedef struct pam_handle_t:
        pass
    void misc_conv(int num_msg, const pam_message **msgm, pam_response **response, void *appdata_ptr)


cdef extern from "pam_appl.h":
    int PAM_SUCCESS
    struct pam_conv:
        void *conv
        #int (*conv)(int num_msg, const pam_message **msg, pam_response **resp, void *appdata_ptr)
        void *appdata_ptr
    struct pam_message:
        pass
    struct pam_response:
        pass
    const char *pam_strerror(pam_handle_t *pamh, int errnum)
    int pam_start(const char *service_name, const char *user, const pam_conv *pam_conversation, pam_handle_t **pamh)
    int pam_open_session(pam_handle_t *pamh, int flags)
    int pam_close_session(pam_handle_t *pamh, int flags)
    int pam_end(pam_handle_t *pamh, int pam_status)

PAM_ERR_STR = {PAM_SUCCESS : "success"}

cdef pam_handle_t*   pam_handle = NULL

def pam_open(service_name="xpra"):
    global pam_handle
    cdef passwd *passwd_struct
    cdef pam_conv conv
    cdef int r

    if pam_handle!=NULL:
        log.error("Error: cannot open the pam session more than once!")
        return False

    passwd_struct = getpwuid(os.geteuid())
    if passwd_struct==NULL:
        try:
            estr = os.strerror(errno)
        except ValueError:
            estr = str(errno)
        log.error("Error: cannot find pwd entry for euid %i", os.geteuid())
        log.error(" %s", estr)
        return False

    conv.conv = <void*> misc_conv
    conv.appdata_ptr = NULL;
    r = pam_start(service_name, passwd_struct.pw_name, &conv, &pam_handle)
    log("pam_start: %s", PAM_ERR_STR.get(r, r))
    if r!=PAM_SUCCESS:
        pam_handle = NULL
        log.error("Error: pam_start failed:")
        log.error(" %s", pam_strerror(pam_handle, r))
        return False

    r = pam_open_session(pam_handle, 0)
    log("pam_open_session: %s", PAM_ERR_STR.get(r, r))
    if r!=PAM_SUCCESS:
        pam_handle = NULL
        log.error("Error: pam_open_session failed:")
        log.error(" %s", pam_strerror(pam_handle, r))
        return False
    return True

def pam_close():
    global pam_handle
    if pam_handle==NULL:
        log.error("Error: no pam session to close!")
        return False

    cdef int r = pam_close_session(pam_handle, 0)
    log("pam_close_session: %s", PAM_ERR_STR.get(r, r))
    if r!=PAM_SUCCESS:
        pam_handle = NULL
        log.error("Error: failed to close the pam session:")
        log.error(" %s", pam_strerror(pam_handle, r))
        return False

    r = pam_end(pam_handle, r)
    log("pam_end: %s", PAM_ERR_STR.get(r, r))
    if r!=PAM_SUCCESS:
        log.error("Error: pam_end '%s'", pam_strerror(pam_handle, r))
        return False
    return True
