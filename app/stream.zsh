#!/bin/zsh -f
# Starts Streamlink for one SofaStream session. launchd runs this script, so the
# optional Twitch login is read here from the macOS Keychain. It never ends up in
# the launchd job definition, process arguments, settings files or the stream log:
# Streamlink reads it from a private (0600) temporary config file that is removed
# right after startup, and also when the job is stopped before that.
#
# Usage: stream.zsh <streamlink> <2k:0|1> <keychain-service> <streamlink args...>
streamlink="$1" hq="$2" service="$3"
shift 3

tmpdir="${TV_PRIVATE_TMP:-$(/usr/bin/getconf DARWIN_USER_TEMP_DIR 2>/dev/null)}"
# A login file survives only a hard kill. Sweep those on every start, also with 2K
# off; files under a minute old may belong to a stable/dev session starting now.
/bin/rm -f -- "${tmpdir:-/tmp}"/sofastream-login.*(N.mm+0)

# Always on the command line: it overrides 'loglevel=debug' in the user's own
# Streamlink config, which would print the login header into the stream log.
extra=(--loglevel info)
cfg=
# Streamlink's own config files; without --config it reads these by itself.
defaults=("$HOME/Library/Application Support/streamlink/config"
          "$HOME/Library/Application Support/streamlink/config.twitch"
          "$HOME/.config/streamlink/config" "$HOME/.config/streamlink/config.twitch")
if [[ "$hq" == 1 ]]; then
    # 1440p is only offered in H.265 and normally only to a logged-in viewer.
    extra+=(--twitch-supported-codecs h264,h265,av1)
    # A login in the user's Streamlink config also counts; only the option name is matched.
    config_login=0
    for default in "${defaults[@]}"; do
        [[ -f "$default" ]] && /usr/bin/grep -qE '^[[:space:]]*(--)?twitch-api-header[[:space:]]*=[[:space:]]*Authorization' "$default" && config_login=1
    done
    token=$("${TV_SECURITY_BIN:-/usr/bin/security}" find-generic-password \
        -a twitch -s "$service" -w 2>/dev/null)
    if [[ ! "$token" =~ '^[a-z0-9]{20,40}$' ]]; then
        if (( config_login )); then
            print -r -- "[sofastream][info] 2K met de Twitch-login uit je Streamlink-config." >&2
        else
            print -r -- "[sofastream][warning] 2K staat aan, maar er is geen Twitch-login (sleutelhanger, dienst '$service', of Streamlink-config); maximaal 1080p." >&2
        fi
    elif [[ "$(print -r -- "Authorization: OAuth $token" | "${TV_CURL_BIN:-/usr/bin/curl}" -s -o /dev/null \
            -w '%{http_code}' -m 4 -H @- "${TV_TWITCH_VALIDATE_URL:-https://id.twitch.tv/oauth2/validate}")" == 401 ]]; then
        # An expired login would make Streamlink fail; play without it instead.
        if (( config_login )); then
            print -r -- "[sofastream][warning] Twitch-login in de sleutelhanger is verlopen; 2K gebruikt nu de login uit je Streamlink-config." >&2
        else
            print -r -- "[sofastream][warning] Twitch-login in de sleutelhanger is verlopen; opnieuw ophalen voor 2K. Nu maximaal 1080p." >&2
        fi
    else
        umask 077
        cfg=$(/usr/bin/mktemp "${tmpdir:-/tmp}/sofastream-login.XXXXXX") || exit 1
        print -r -- "twitch-api-header=Authorization=OAuth $token" > "$cfg"
        # --config skips Streamlink's default config files, so pass existing ones first.
        for default in "${defaults[@]}"; do
            [[ -f "$default" ]] && extra+=(--config "$default")
        done
        extra+=(--config "$cfg")
    fi
    unset token
else
    # The user's own Streamlink config may enable H.265/AV1 for other tools; with
    # 2K off the setting must hold. Command-line options override config files.
    extra+=(--twitch-supported-codecs h264)
fi

[[ -z "$cfg" ]] && exec "$streamlink" "${extra[@]}" "$@"

# With a login file, Streamlink runs as a child so this shell can remove the file.
# launchd stops the job's whole process group, so a background remover would die
# with it; the trap covers 'tv stop' and a channel switch within the TTL.
pid=
trap '/bin/rm -f -- "$cfg"; [[ -n "$pid" ]] && { kill -TERM $pid 2>/dev/null; wait $pid 2>/dev/null; }; exit 143' TERM INT HUP
"$streamlink" "${extra[@]}" "$@" &
pid=$!
# Streamlink reads its config at startup; remove the login after that, or at once
# when Streamlink has already ended.
end=$(( SECONDS + ${TV_LOGIN_CONFIG_TTL:-15} ))
while (( SECONDS < end )) && kill -0 $pid 2>/dev/null; do /bin/sleep 0.2; done
/bin/rm -f -- "$cfg"
wait $pid
