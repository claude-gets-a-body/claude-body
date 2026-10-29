#!/bin/bash
# guard.sh LIMIT_MB cmd...  — run cmd, kill its whole process group if total RSS passes LIMIT_MB
lim=$1; shift
setsid "$@" &
pid=$!
peak=0
while kill -0 $pid 2>/dev/null; do
  rss=$(ps -o rss= -g $pid 2>/dev/null | awk '{s+=$1} END {print int(s/1024)}')
  [ -n "$rss" ] && [ "$rss" -gt "$peak" ] && peak=$rss
  if [ -n "$rss" ] && [ "$rss" -gt "$lim" ]; then
    kill -9 -- -$pid 2>/dev/null; echo "GUARD: killed at ${rss} MB (limit ${lim})"; wait $pid 2>/dev/null; exit 99
  fi
  sleep 0.3
done
wait $pid; rc=$?
echo "GUARD: peak ${peak} MB, exit $rc"
exit $rc
