#!/bin/sh
# Page row: page number, name, date and running clock.  usage: tui-clock.sh PAGE [dev]
# Reads FZF_COLUMNS (set by fzf) and TV_TUI_MOTION. Dutch names without relying on the locale.
set -- "$1" "$2" $(date '+%w %e %m %H:%M:%S')
page=$1 dev=$2 wd=$3 day=$4 mon=$5 clock=$6
[ "$TV_TUI_MOTION" = 0 ] && clock='        '   # no running clock: eight spaces keep the date in place
set -- zo ma di wo do vr za; shift "$wd"; wd=$1
set -- jan feb mrt apr mei jun jul aug sep okt nov dec; shift $(( ${mon#0} - 1 )); mon=$1
date="$wd $day $mon"
width=$(( ${FZF_COLUMNS:-80} - 2 ))
used=$(( ${#page} + 3 + 10 ))
e=$(printf '\033')
w="$e[38;5;231m" b="$e[1m" d="$e[1;38;5;16;48;5;201m" c="$e[38;5;51m" y="$e[38;5;226m" r="$e[0m"
[ -n "$NO_COLOR" ] && w= b= d= c= y= r=   # https://no-color.org
left="${w}P$page  ${b}SofaStream$r"
if [ -n "$dev" ]; then left="$left $d DEV $r"; used=$(( used + 6 )); fi
if [ $(( width - used )) -ge $(( ${#date} + 12 )) ]; then
  pad=$(( width - used - ${#date} - 10 ))
  printf '%s%*s%s%s  %s%s%s' "$left" "$pad" '' "$c" "$date" "$y" "$clock" "$r"
else
  pad=$(( width - used - 8 )); [ "$pad" -lt 1 ] && pad=1
  printf '%s%*s%s%s%s' "$left" "$pad" '' "$y" "$clock" "$r"
fi
