/*
 * This is based on the snippet current_utc_time.c from:
 * https://gist.github.com/jbenet/1087739
 *
 * On OS X, compile with: gcc get_monotonic_time.c
 *  Linux, compile with: gcc get_monotonic_time.c -lrt
 */

#ifdef _WIN32
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif
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

#ifdef _WIN32
LARGE_INTEGER freq;
#endif

// Use clock_gettime in linux, clock_get_time in OS X.
double get_monotonic_time(void){
#ifdef _WIN32
	LARGE_INTEGER t;
	if (freq.QuadPart==0) {
		if (!QueryPerformanceFrequency(&freq)) {
			freq.QuadPart = 0;
		}
	}
	if (freq.QuadPart>0) {
		if (QueryPerformanceCounter(&t)) {
			return (((double) t.QuadPart) / freq.QuadPart);
		}
	}
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
