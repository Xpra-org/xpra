#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <libproc.h>

/**
 * Compile and place the resulting binary somewhere in the bundle under /Contents/
 * this program will try to execute the file with the same name in /Contents/Resources/scripts/
 * using the shell /bin/sh
 */
#define MAX_ARGV 100

int main (int argc, char* argv[])
{
	int ret;
	pid_t pid;
	char pathbuf[PROC_PIDPATHINFO_MAXSIZE+64];
	char filename[PROC_PIDPATHINFO_MAXSIZE];
	char *p;

	pid = getpid();
	ret = proc_pidpath(pid, pathbuf, PROC_PIDPATHINFO_MAXSIZE);
	if (ret <= 0) {
		fprintf(stderr, "PID %d: proc_pidpath ();\n", pid);
		fprintf(stderr, "	%s\n", strerror(errno));
		return 1;
	}
#ifdef DEBUG
	printf("proc %d: %s\n", pid, pathbuf);
#endif
	//stop on last directory separator to copy the filename:
	p = pathbuf;
	while (strchr(p, '/')) {
		p = strchr(p, '/')+1;
	}
	strcpy(filename, p);
	//stop on last "/Contents" directory:
	p = pathbuf;
	while (strstr(p, "/Contents/")) {
		p = strstr(p, "/Contents/")+1;
	}
	if (p==pathbuf) {
		fprintf(stderr, "invalid command path: '/Contents/' directory not found in path '%s'\n", pathbuf);
		return 1;
	}
	strcpy(p, "/Contents/Resources/scripts/");
	strcpy(pathbuf+strlen(pathbuf), filename);
	char *new_argv[MAX_ARGV];
	new_argv[0] = "/bin/sh";
	new_argv[1] = pathbuf;
	//copy remaining args:
	int i = 1;
	while (argv[i]!=NULL && i<(MAX_ARGV-1)) {
		new_argv[i+1] = argv[i];
		i += 1;
	}
	new_argv[i+1] = NULL;
#ifdef DEBUG
	printf("execv(/bin/sh, %s, ..)\n", pathbuf);
#endif
	int v = execv("/bin/sh", new_argv);
	fprintf(stderr, "execv(\"/bin/sh\", %s, ..) returned %i\n", pathbuf, v);
	return v;
}
