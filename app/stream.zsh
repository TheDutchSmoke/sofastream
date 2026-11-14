#!/bin/zsh -f
# Starts Streamlink for one SofaStream session. launchd runs this script, so the
# optional Twitch login is read here from the macOS Keychain. It never ends up in
# the launchd job definition, process arguments, settings files or the stream log:
# Streamlink reads it from a private (0600) temporary config file that is removed
# right after startup.
#
# Usage: stream.zsh <streamlink> <2k:0|1> <keychain-service> <streamlink args...>
streamlink="$1" hq="$2" service="$3"
shift 3

extra=()
if [[ "$hq" == 1 ]]; then
    # 1440p is only offered in H.265 and normally only to a logged-in viewer.
    extra+=(--twitch-supported-codecs h264,h265,av1)
    token=$("${TV_SECURITY_BIN:-/usr/bin/security}" find-generic-password \
        -a twitch -s "$service" -w 2>/dev/null)
    if [[ ! "$token" =~ '^[a-z0-9]{20,40}$' ]]; then
        print -r -- "[sofastream][warning] 2K staat aan, maar er is geen Twitch-login in de sleutelhanger (dienst '$service'); maximaal 1080p."
    elif [[ "$(print -r -- "Authorization: OAuth $token" | "${TV_CURL_BIN:-/usr/bin/curl}" -s -o /dev/null \
            -w '%{http_code}' -m 4 -H @- "${TV_TWITCH_VALIDATE_URL:-https://id.twitch.tv/oauth2/validate}")" == 401 ]]; then
        # An expired login would make Streamlink fail; play without it (max 1080p) instead.
        print -r -- "[sofastream][warning] Twitch-login in de sleutelhanger is verlopen; opnieuw ophalen voor 2K. Nu maximaal 1080p."
    else
        umask 077
        tmpdir="${TV_PRIVATE_TMP:-$(/usr/bin/getconf DARWIN_USER_TEMP_DIR 2>/dev/null)}"
        # A stopped job can kill the remover below; sweep leftovers older than a minute.
        /bin/rm -f -- "${tmpdir:-/tmp}"/sofastream-login.*(N.mm+0)
        cfg=$(/usr/bin/mktemp "${tmpdir:-/tmp}/sofastream-login.XXXXXX") || exit 1
        print -r -- "twitch-api-header=Authorization=OAuth $token" > "$cfg"
        # --config skips Streamlink's default config files, so pass existing ones first.
        for default in "$HOME/Library/Application Support/streamlink/config" \
                       "$HOME/Library/Application Support/streamlink/config.twitch" \
                       "$HOME/.config/streamlink/config" "$HOME/.config/streamlink/config.twitch"; do
            [[ -f "$default" ]] && extra+=(--config "$default")
        done
        extra+=(--config "$cfg")
        # Streamlink reads its config at startup; remove the file shortly after.
        ( /bin/sleep "${TV_LOGIN_CONFIG_TTL:-15}"; /bin/rm -f -- "$cfg" ) &!
    fi
    unset token
fi

exec "$streamlink" "${extra[@]}" "$@"
