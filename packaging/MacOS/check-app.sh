#!/bin/bash
# Verify that an app bundle is self-contained:
# - no Mach-O file loads a library (or has an rpath) outside the bundle or the OS
# - no file references a Homebrew prefix, not even as a plain string
#   (ie: a hardcoded dlopen() search path, a loaders.cache, a sysconfig module)
# Usage: check-app.sh [path/to/Xpra.app]

MACOS_SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
APP_DIR="${1:-${MACOS_SCRIPT_DIR}/image/Xpra.app}"
if [ ! -d "${APP_DIR}" ]; then
	echo "app bundle not found: ${APP_DIR}"
	exit 1
fi

# `/usr/local/Cellar` and `/usr/local/opt` are the Intel Homebrew prefixes:
FORBIDDEN_RE='/opt/homebrew|/usr/local/Cellar|/usr/local/opt/|/opt/local/'
# the only absolute locations a load command or rpath may point to:
ALLOWED_RE='^(@rpath/|@loader_path/|@executable_path/|/usr/lib/|/System/Library/)'

ERRORS=0
WARNINGS=0

echo "*******************************************************************************"
echo "Checking ${APP_DIR}"

echo "- Mach-O load commands and rpaths"
while IFS= read -r -d $'\0' f; do
	# only look at Mach-O files (magic bytes: thin 32/64-bit or fat, either endianness):
	magic=$(xxd -p -l 4 "$f" 2>/dev/null)
	case "$magic" in
		feedface|feedfacf|cefaedfe|cffaedfe|cafebabe|bebafeca) ;;
		*) continue ;;
	esac
	# `cafebabe` is also the Java class file magic, `otool` will just fail on those
	deps=$(otool -L "$f" 2>/dev/null | tail -n +2 | awk '{print $1}')
	rpaths=$(otool -l "$f" 2>/dev/null | awk '/cmd LC_RPATH/{getline; getline; print $2}')
	for p in $deps; do
		if ! [[ "$p" =~ $ALLOWED_RE ]]; then
			echo "  error: ${f#"${APP_DIR}/"} links against $p"
			ERRORS=$((ERRORS+1))
		fi
	done
	# a stale rpath is only searched after the bundled ones,
	# (forbidden prefixes are caught by the string check below)
	for p in $rpaths; do
		if ! [[ "$p" =~ $ALLOWED_RE ]]; then
			echo "  warning: ${f#"${APP_DIR}/"} has rpath $p"
			WARNINGS=$((WARNINGS+1))
		fi
	done
done < <(find "${APP_DIR}" -type f -print0)

echo "- forbidden path strings"
# `-a` so binaries are searched too, not just text files:
MATCHES=$(grep -rlaE "${FORBIDDEN_RE}" "${APP_DIR}")
if [ -n "${MATCHES}" ]; then
	while IFS= read -r f; do
		echo "  error: ${f#"${APP_DIR}/"}: $(grep -aoE "(${FORBIDDEN_RE})[^[:space:][:cntrl:]\"']*" "$f" | sort -u | head -n 3 | xargs)"
		ERRORS=$((ERRORS+1))
	done <<< "${MATCHES}"
fi

if [ "${WARNINGS}" != "0" ]; then
	echo "found ${WARNINGS} warning(s)"
fi
if [ "${ERRORS}" != "0" ]; then
	echo "found ${ERRORS} problem(s) in ${APP_DIR}"
	exit 1
fi
echo "OK"
