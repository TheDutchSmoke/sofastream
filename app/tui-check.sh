#!/bin/sh
# Pages 201 and 202: the header with a live check of what the typed text becomes.
# It runs on every keystroke, so it is plain sh without Python's start-up time; the rules
# mirror normalize_channel in tui.py (test_tui.py compares both). Reads FZF_QUERY (fzf)
# and TV_TUI_DIALOG_HEAD (band and instruction, rendered once by tui.py --dialog).
printf '%s\n' "$TV_TUI_DIALOG_HEAD"
value=$(printf '%s' "$FZF_QUERY" | tr 'A-Z' 'a-z' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
[ -n "$value" ] || exit 0
rest=$value
case $rest in http://*) rest=${rest#http://} ;; https://*) rest=${rest#https://} ;; esac
case $rest in
  www.twitch.tv/*) rest=${rest#www.twitch.tv/} ;;
  m.twitch.tv/*) rest=${rest#m.twitch.tv/} ;;
  twitch.tv/*) rest=${rest#twitch.tv/} ;;
  *) rest=$value ;;
esac
[ "$rest" = "$value" ] || rest=${rest%%[/?#]*}
login=${rest#@}
valid=1
case $login in '' | *[!a-z0-9_]*) valid=0 ;; esac
[ ${#login} -le 25 ] || valid=0
if [ "$valid" = 1 ]; then
  if [ -n "$NO_COLOR" ]; then printf '→ twitch.tv/%s' "$login"
  else printf '\033[38;5;30m→ twitch.tv/\033[1;38;5;46m%s\033[0m' "$login"; fi
else
  if [ -n "$NO_COLOR" ]; then printf '✕ Geen geldige kanaalnaam of Twitch-link.'
  else printf '\033[38;5;196m✕ Geen geldige kanaalnaam of Twitch-link.\033[0m'; fi
fi
