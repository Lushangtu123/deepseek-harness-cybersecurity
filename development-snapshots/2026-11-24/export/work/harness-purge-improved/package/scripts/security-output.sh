#!/bin/sh
# Fixed scanner adapter. Inputs and this script are read-only; output lives in tmpfs.
set -u
out=$1
shift
case "$out" in /out|/zap/wrk) ;; *) exit 74 ;; esac
if [ "${1:-}" = --deadline-seconds ]; then
 [ "$out" = /out ] && [ "$#" -ge 3 ] || exit 74
 seconds=$2
 shift 2
 case "$seconds" in ''|*[!0-9]*|????*) exit 74 ;; esac
 [ "$seconds" -ge 1 ] && [ "$seconds" -le 240 ] || exit 74
 # This shell is PID 1 in the scanner container. On expiry its exit
 # terminates every process in the container PID namespace.
 owner=$$
 trap 'exit 124' USR1
 (sleep "$seconds"; kill -USR1 "$owner") </dev/null >/dev/null 2>&1 &
 watchdog=$!
 trap 'kill "$watchdog" 2>/dev/null || :' EXIT
 "$@" > /tmp/harness-scanner.log 2>&1 &
 wait "$!"
 code=$?
else
 "$@" > /tmp/harness-scanner.log 2>&1
 code=$?
fi
result="$out/result.json"
auth="$out/auth-check.json"
# Stream only two fixed regular files. Raw logs never leave the bounded tmpfs.
if [ ! -f "$result" ] || [ -L "$result" ]; then
 printf '{"result":null,"authentication":null}\n'
 exit "$code"
fi
if [ "$(wc -c < "$result")" -gt 8388608 ]; then exit 73; fi
printf '{"result":'
head -c 8388609 "$result" || exit 74
printf ',"authentication":'
if [ -f "$auth" ] && [ ! -L "$auth" ]; then
 if [ "$(wc -c < "$auth")" -gt 1024 ]; then exit 73; fi
 head -c 1025 "$auth" || exit 74
else printf 'null'; fi
printf '}\n'
exit "$code"
