/*
 * This is based on the snippet current_utc_time.c from:
 * https://gist.github.com/jbenet/1087739
 *
 * On OS X, compile with: gcc get_monotonic_time.c
 *  Linux, compile with: gcc get_monotonic_time.c -lrt
 */

#ifdef _WIN32
#define _WIN32_WINNT 0x0600
#include <Windows.h>
#else
#include <time.h>
#include <sys/time.h>
#include <stdio.h>

#ifdef __MACH__
#include <mach/clock.h>
#include <mach/mach.h>
#endif
#endif

// Use clock_gettime in linux, clock_get_time in OS X.
double get_monotonic_time(){
#ifdef _WIN32
	ULONGLONG ticks = GetTickCount64();
	return ((double) ticks) / 1000;
#else
#ifdef __MACH__
	clock_serv_t cclock;
	mach_timespec_t mts;
	host_get_clock_service(mach_host_self(), SYSTEM_CLOCK, &cclock);
	clock_get_time(cclock, &mts);
	mach_port_deallocate(mach_task_self(), cclock);
	return mts.tv_sec + mts.tv_nsec/1000000000.0;
#else
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec/1000000000.0;
#endif
#endif
}
