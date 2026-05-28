#!/bin/bash
# Memory-tunable sweep: start xpra on a sacrificial display, capture
# server+vfb RSS for each configuration, write a Markdown table.
#
# Usage: tests/perf/memory_sweep.sh [DISPLAY]
# Default DISPLAY is :250 to stay out of the way of an active session.

set -u
DISP="${1:-:250}"
SETTLE_SEC="${SETTLE_SEC:-15}"
OUT="${OUT:-/tmp/xpra-memory-sweep.md}"

XPRA="/usr/bin/xpra"
COMMON_OPTS=(--start=xterm --daemon=yes --systemd-run=no --exit-with-children=no)
COMMON_ENV=(XPRA_XDG=0 XPRA_IBUS=0)

stop_quiet() {
    "$XPRA" stop "$DISP" >/dev/null 2>&1 || true
    # wait up to 10s for socket to disappear
    for _ in $(seq 1 20); do
        [ -S "/run/user/$(id -u)/xpra/${DISP#:}/socket" ] || break
        sleep 0.5
    done
}

server_rss_kb() {
    # find xpra server pid via xpra info, read /proc rss
    local pid rss
    pid=$("$XPRA" info "$DISP" 2>/dev/null | awk -F= '/^pid=/{print $2; exit}')
    [ -z "$pid" ] && { echo ""; return; }
    rss=$(awk '/^VmRSS:/{print $2; exit}' "/proc/$pid/status" 2>/dev/null)
    echo "${rss:-}"
}

vfb_rss_kb() {
    local pid rss
    pid=$("$XPRA" info "$DISP" 2>/dev/null | awk -F= '/^display\.pid=/{print $2; exit}')
    [ -z "$pid" ] && { echo ""; return; }
    rss=$(awk '/^VmRSS:/{print $2; exit}' "/proc/$pid/status" 2>/dev/null)
    echo "${rss:-}"
}

measure() {
    local label="$1"; shift
    local extra_env="$1"; shift
    # remaining args are extra xpra flags
    stop_quiet
    # start with given env + flags
    if [ -n "$extra_env" ]; then
        env "${COMMON_ENV[@]}" $extra_env "$XPRA" start "$DISP" "${COMMON_OPTS[@]}" "$@" >/dev/null 2>&1 &
    else
        env "${COMMON_ENV[@]}" "$XPRA" start "$DISP" "${COMMON_OPTS[@]}" "$@" >/dev/null 2>&1 &
    fi
    # wait for socket
    for _ in $(seq 1 60); do
        "$XPRA" info "$DISP" >/dev/null 2>&1 && break
        sleep 0.5
    done
    sleep "$SETTLE_SEC"
    local srv vfb
    srv=$(server_rss_kb)
    vfb=$(vfb_rss_kb)
    printf '%-32s server=%6s KB  vfb=%6s KB  flags=%s\n' "$label" "$srv" "$vfb" "$*" >&2
    echo "$label|$srv|$vfb|$*"
}

stop_quiet
echo "# tunable | server RSS (KB) | vfb RSS (KB) | flags" > "$OUT"
echo "# Sweep on $DISP, settle ${SETTLE_SEC}s, with XPRA_XDG=0 XPRA_IBUS=0" >> "$OUT"

# baseline (no extra flags)
measure "baseline"           ""       >> "$OUT"

# subsystem disables
measure "audio=no"           ""  --audio=no                            >> "$OUT"
measure "gstreamer=no"       ""  --gstreamer=no                        >> "$OUT"
measure "clipboard=no"       ""  --clipboard=no                        >> "$OUT"
measure "notifications=no"   ""  --notifications=no                    >> "$OUT"
measure "bell=no"            ""  --bell=no                             >> "$OUT"
measure "cursors=no"         ""  --cursors=no                          >> "$OUT"
measure "dbus=no"            ""  --dbus-control=no  --dbus-launch=     >> "$OUT"
measure "mdns=no"            ""  --mdns=no                             >> "$OUT"
measure "http=no"            ""  --http=no                             >> "$OUT"
measure "webcam=no"          ""  --webcam=no                           >> "$OUT"
measure "printing=no"        ""  --printing=no                         >> "$OUT"
measure "file-transfer=no"   ""  --file-transfer=no                    >> "$OUT"
measure "readonly"           ""  --readonly                            >> "$OUT"

# encoding scope
measure "encoding=rgb"       ""  --encoding=rgb                        >> "$OUT"
measure "encodings=rgb,png"  ""  --encodings=rgb,png                   >> "$OUT"
measure "video=no"           ""  --video=no                            >> "$OUT"

# minimal: every memory-saving toggle on
measure "minimal-stack"      ""  --audio=no --clipboard=no --notifications=no \
                                  --bell=no --cursors=no --dbus-control=no \
                                  --mdns=no --http=no --webcam=no --printing=no \
                                  --file-transfer=no --video=no --encoding=rgb >> "$OUT"

stop_quiet
echo "Sweep complete. Output in $OUT"
