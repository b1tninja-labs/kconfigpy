#!/bin/bash
# Read-only. Prints one line per device and per loaded module, tab-separated:
#   dev <sysfs path> <modalias> <driver> <module>
#   mod <name>
export LC_ALL=C
find /sys/devices -name modalias -type f 2>/dev/null | sort | while read -r file; do
  dir=${file%/modalias}
  alias=$(cat "$file" 2>/dev/null)
  [ -n "$alias" ] || continue
  driver=""
  module=""
  if [ -e "$dir/driver" ]; then
    driver=$(basename "$(readlink -f "$dir/driver")")
    [ -e "$dir/driver/module" ] && module=$(basename "$(readlink -f "$dir/driver/module")")
  fi
  printf 'dev\t%s\t%s\t%s\t%s\n' "${dir#/sys/devices/}" "$alias" "$driver" "$module"
done
awk '{print "mod\t" $1}' /proc/modules | sort
