# A wake can show tvOS' profile choice; choosing a profile closes VLC. Within a
# short window after a wake-start, reopen VLC and restart the stream once.
# Cancelling only removes the marker (no kill, so no risk of hitting a reused PID).
_tv_cancel_profile_retry() {
    rm -f "${TV_CACHE_DIR:-$HOME/.cache/tv}/profile-retry"
}

# Each start owns the session until a newer start or 'tv stop' replaces it. A start
# that lost it (a long prepare, a running profile retry, another terminal) must not
# touch VLC or the job any more. /dev/urandom: a subshell repeats $RANDOM.
_tv_session_file() {
    print -r -- "${TV_CACHE_DIR:-$HOME/.cache/tv}/session"
}

_tv_end_session() {
    rm -f "$(_tv_session_file)"
}

_tv_owns_session() {
    local file="$(_tv_session_file)"
    [[ -r "$file" && "$(<"$file")" == "$1" ]]
}

# Ctrl-C or a closed window while starting: unload a job nobody watches yet.
_tv_abort_start() {
    local session="$1" job="$2"
    if _tv_owns_session "$session" && ! grep -qs 'Got HTTP request' "$TV_STREAM_LOG"; then
        launchctl bootout "$job" 2>/dev/null
        echo "Afgebroken; Streamlink is gestopt."
    fi
}

# The relay's control socket lives in the profile's cache folder (stable and dev apart).
_tv_relay_socket() {
    print -r -- "${TV_CACHE_DIR:-$HOME/.cache/tv}/relay.sock"
}

_tv_relay() {
    local command="$1"
    shift
    python3 "$TV_APP_DIR/relay.py" "$command" "$(_tv_relay_socket)" "$@"
}

_tv_profile_retry() {
    local channel="$1" session="$2" cache="${TV_CACHE_DIR:-$HOME/.cache/tv}"
    local marker="$cache/profile-retry" log="$cache/profile-retry.log"
    local token="$$.$RANDOM.$SECONDS"
    print -r -- "$token" > "$marker"
    : > "$log"
    # Fully detached: the TUI captures _tv_start's output and must not wait on this.
    (
        local end=$(( SECONDS + ${TV_PROFILE_RETRY_WINDOW:-30} ))
        while (( SECONDS < end )); do
            [[ "$(<"$marker")" == "$token" ]] || exit 0
            if grep -qs 'HTTP connection closed' "$TV_STREAM_LOG"; then
                [[ "$(<"$marker")" == "$token" ]] || exit 0
                rm -f "$marker"
                print -r -- "$(date +%T) VLC sloot kort na wekken (profielkeuze?); eenmalig opnieuw starten." >> "$log"
                # Same session: a 'tv stop' or newer choice meanwhile still ends this restart.
                _tv_start "$channel" noretry "$session" >> "$log" 2>&1
                exit 0
            fi
            sleep "${TV_PROFILE_RETRY_POLL:-0.5}"
        done
        [[ "$(<"$marker")" == "$token" ]] && rm -f "$marker"
    ) </dev/null >/dev/null 2>&1 &!
}

_tv_start() {
    setopt localoptions localtraps
    local channel="$1" retry=1
    [[ "$2" == noretry ]] && retry=0
    # A new choice replaces any pending retry for the previous one.
    _tv_cancel_profile_retry
    local label="$TV_LAUNCH_LABEL"
    local domain="gui/$(id -u)"
    local streamlink="$(command -v streamlink)" ffmpeg="$(command -v ffmpeg)" python="$(command -v python3)"
    local cache="${TV_CACHE_DIR:-$HOME/.cache/tv}"
    local superseded="Vervangen door een nieuwere kanaalkeuze of stop."

    [[ -z "$streamlink" ]] && {
        echo "❌ Streamlink niet gevonden."
        return 1
    }
    [[ -z "$ffmpeg" ]] && {
        echo "❌ ffmpeg niet gevonden. Installeer met: brew install ffmpeg"
        return 1
    }

    channel=$(python3 "$TV_APP_DIR/tui.py" --normalize-channel "$channel") || return 1

    mkdir -p "$cache"
    local session="$3"
    if [[ -n "$session" ]]; then
        # The profile retry continues the session of the start that scheduled it.
        _tv_owns_session "$session" || { echo "$superseded"; return 1; }
    else
        session=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
        print -r -- "$session" > "$(_tv_session_file)"
    fi

    # Validate the channel before waking the TV or switching apps.
    python3 "$TV_APP_DIR/tui.py" --check-playable "$channel" || return 1
    local woke
    woke=$(node "$TV_APP_DIR/playback.mjs" prepare) || return 1
    # Checking and waking can take long; a newer choice or 'tv stop' wins meanwhile.
    _tv_owns_session "$session" || { echo "$superseded"; return 1; }
    python3 "$TV_APP_DIR/settings.py" snapshot || return 1
    local hq address
    hq=$(python3 "$TV_APP_DIR/settings.py" hq-enabled) || return 1
    # Serve only on the Mac address that reaches the Apple TV, not on every network.
    address=$(node "$TV_APP_DIR/playback.mjs" address) || return 1
    [[ "$address" =~ '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' ]] || {
        echo "❌ Lokaal netwerkadres richting Apple TV niet gevonden."
        return 1
    }

    _tv_owns_session "$session" || { echo "$superseded"; return 1; }
    # A running relay switches inside its stream: VLC keeps its connection and gets no
    # command at all. (VLC 3.0.24 on tvOS fails on a second item in one session.)
    local relay_channel relay_pending relay_viewers
    if read -r relay_channel relay_pending relay_viewers <<< "$(_tv_relay query)" && [[ -n "$relay_viewers" ]]; then
        if [[ "$relay_channel" != "$channel" || "$relay_pending" != - ]]; then
            _tv_relay send switch "$channel" "$hq" >/dev/null || { echo "❌ Wisselen mislukt."; return 1; }
        fi
        if (( relay_viewers > 0 )); then
            local switched=0
            _tv_relay wait "$channel" "${TV_SWITCH_WAIT:-25}" || switched=$?
            case $switched in
                0) echo "▶ Gewisseld naar $channel op de tv." ;;
                2) echo "❌ $channel start niet; het vorige kanaal blijft spelen. Bekijk Beheer → Streamlog." ;;
                *) echo "❌ Wisselen naar $channel niet bevestigd. Bekijk Beheer → Streamlog." ;;
            esac
            return $(( switched != 0 ))
        fi
        # The relay runs but nobody watches: VLC opens it below.
    else
        # From here on the job changes; an interrupted start must not leave a server
        # listening without a viewer. Subshells such as $(node …) inherit the trap, so
        # only this shell cleans up; 'return' would lose the status, hence 'exit'.
        # _tv_start always runs in its own process (bin/tv, $(…) in the TUI, the retry).
        local depth=$ZSH_SUBSHELL
        trap '(( ZSH_SUBSHELL > depth )) || _tv_abort_start "$session" "$domain/$label"; exit 130' INT TERM HUP
        launchctl bootout "$domain/$label" 2>/dev/null
        rm -f "$TV_STREAM_LOG" "$TV_STREAM_ERR"

        # A one-shot job: launchd must not restart the relay after it ends (VLC closed
        # the video, the stream went offline, or 'tv stop').
        local job="$cache/$label.plist"
        python3 -c 'import plistlib, sys
job, label, out, err, *args = sys.argv[1:]
with open(job, "wb") as handle:
    plistlib.dump({"Label": label, "ProgramArguments": args, "RunAtLoad": True,
                   "KeepAlive": False, "StandardOutPath": out, "StandardErrorPath": err}, handle)' \
            "$job" "$label" "$TV_STREAM_LOG" "$TV_STREAM_ERR" \
            "$python" "$TV_APP_DIR/relay.py" serve \
            --listen "$address" --port "$TV_STREAM_PORT" --path "/$session" \
            --control "$(_tv_relay_socket)" \
            --stream-script "$TV_APP_DIR/stream.zsh" --streamlink "$streamlink" --ffmpeg "$ffmpeg" \
            --service "$TV_TWITCH_KEYCHAIN_SERVICE" --channel "$channel" --hq "$hq" || {
                echo "❌ Starten mislukt."
                return 1
            }

        # bootout finishes asynchronously; retry briefly while the old job unloads.
        local attempt started=0
        for attempt in {1..20}; do
            launchctl bootstrap "$domain" "$job" 2>/dev/null && { started=1; break; }
            sleep 0.1
        done
        if (( ! started )); then
            echo "❌ Starten mislukt."
            return 1
        fi
        if ! _tv_owns_session "$session"; then
            # 'tv stop' ran during the bootstrap and removed the session: this job is
            # ours and nobody stops it otherwise. A newer start owns the label itself.
            [[ -e "$(_tv_session_file)" ]] || launchctl bootout "$domain/$label" 2>/dev/null
            echo "$superseded"
            return 1
        fi
    fi

    local played=0 output
    output=$(node "$TV_APP_DIR/playback.mjs" play "$channel" 2>&1) || played=$?
    # 3: VLC dropped the stream at once. Right after a wake that is likely the
    # profile choice closing VLC; the profile retry sees the close and restarts once.
    if (( played == 3 )) && [[ "$woke" == woke ]] && (( retry )); then
        echo "Apple TV is net gewekt en VLC sloot direct; SofaStream start het kanaal één keer opnieuw."
        _tv_profile_retry "$channel" "$session"
        return 0
    fi
    if (( played == 0 )); then
        [[ -n "$output" ]] && print -r -- "$output"
        [[ "$woke" == woke ]] && (( retry )) && _tv_profile_retry "$channel" "$session"
        return 0
    fi
    [[ -n "$output" ]] && print -r -- "$output" >&2
    # Nobody connected: do not leave a server waiting on the network.
    grep -qs 'Got HTTP request' "$TV_STREAM_LOG" || launchctl bootout "$domain/$label" 2>/dev/null
    return 1
}

_tv_menu() {
    command -v fzf >/dev/null || {
        echo "❌ fzf ontbreekt. Installeer met: brew install fzf"
        return 1
    }
    _tv_fullscreen _tv_menu_loop
}

# The menu owns the terminal like less or top: its own screen at full height, so
# progress lines and earlier output never stack above it, and the terminal is back
# as it was on exit. fzf runs inline (--height=100%) inside that screen; without
# --height it switches screens itself and drops back to the normal one on exit.
_tv_fullscreen() {
    setopt localoptions localtraps
    if [[ -n "$TV_FULLSCREEN" ]]; then
        "$@"
        return
    fi
    local -x TV_FULLSCREEN=1
    trap '_tv_leave_screen; exit 130' INT TERM HUP
    print -n $'\e[?1049h'
    _tv_clear
    {
        "$@"
    } always {
        _tv_leave_screen
    }
}

_tv_leave_screen() {
    print -n $'\e[?1049l'
}

_tv_clear() {
    print -n $'\e[H\e[2J'
}

# A short notice while the menu waits; the next draw replaces it.
_tv_progress() {
    _tv_clear
    print -r -- $'\n\n    '"$1"
}

_tv_menu_loop() {
    local favfile="$TV_CONFIG_DIR/favorites"
    mkdir -p "$TV_CONFIG_DIR"
    touch "$favfile"

    local items channel choice remove view_label input_title close_label
    local -a logfiles
    local metadata_helper="$TV_APP_DIR/tui.py"
    local -x TV_TUI_VIEW=live
    local -x TV_TUI_COLUMNS=${COLUMNS:-100}
    local -x TV_TUI_NOTICE=''
    local -a refresh_args
    local -a finder_style=(
        --ansi --height=100% --layout=reverse
        --border=rounded --margin=1 --padding=1,2
        --pointer='▸' --prompt='Zoek › ' --info=inline-right
        --color='bg:#101019,fg:#cbd5e1,bg+:#29213e,fg+:#ffffff,hl:#c4b5fd,hl+:#e9d5ff,border:#7c3aed,label:#c4b5fd,header:#94a3b8,prompt:#c4b5fd,pointer:#a78bfa,info:#64748b,spinner:#a78bfa'
    )

    while true; do
        _tv_clear
        TV_TUI_COLUMNS=${COLUMNS:-100}
        items=$(python3 "$metadata_helper" --view "$TV_TUI_VIEW" --color "${refresh_args[@]}") || return 1
        refresh_args=()
        close_label=Terug
        [[ "$TV_TUI_VIEW" == live ]] && close_label=Sluiten
        case "$TV_TUI_VIEW" in
            live) view_label=' LIVE NU · favorieten eerst ' ;;
            offline) view_label=' OFFLINE ' ;;
            unknown) view_label=' STATUS ONBEKEND ' ;;
            manage) view_label=' BEHEER & APPLE TV ' ;;
        esac

        choice=$(printf "%s\n" "$items" | FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' command fzf \
            "${finder_style[@]}" \
            --border-label=" SOFASTREAM${TV_DEV_MODE:+ · DEV}  /  APPLE TV " \
            --list-label="$view_label" --list-border=top \
            --header-lines=4 --header-first \
            --bind='start,every(2):bg-transform-border-label:node "$TV_APP_DIR/stream-status.mjs" --label' \
            --footer="[Favoriet]  [Verversen]  [$close_label]"$'\nKlik/Enter openen · Rechtsklik/Ctrl-F ster · Esc wissen/terug' --footer-border=top \
            --no-sort --track --id-nth=1 \
            --delimiter=$'\t' \
            --with-nth=2.. \
            --accept-nth=1 \
            --bind='enter:wait+accept-non-empty,ctrl-j:wait+accept-non-empty,left-click:accept-non-empty,right-click:trigger(ctrl-f),esc:cancel' \
            --bind='zero:change-header(Geen resultaten · Esc wist je zoekopdracht),change:change-header(),load:change-header()' \
            --bind='click-footer:transform:case "$FZF_CLICK_FOOTER_WORD" in "[Favoriet]") echo "trigger(ctrl-f)";; "[Verversen]") echo "trigger(ctrl-r)";; "[Terug]"|"[Sluiten]") echo "abort";; esac' \
            --bind='ctrl-r:change-header(Twitch-status verversen…)+reload(python3 "$TV_APP_DIR/tui.py" --view "$TV_TUI_VIEW" --color --force)' \
            --bind='ctrl-f:reload(python3 "$TV_APP_DIR/tui.py" --toggle-key {1} --render-after-action --view "$TV_TUI_VIEW" --color)') || {
                if [[ "$TV_TUI_VIEW" != live ]]; then
                    TV_TUI_VIEW=live
                    continue
                fi
                return 0
            }

        [[ -z "$choice" ]] && continue

        case "$choice" in
            view:live|view:offline|view:unknown|view:manage)
                TV_TUI_VIEW="${choice#view:}"
                ;;

            action:other|action:add)
                input_title=' ANDERE STREAMER OPENEN '
                [[ "$choice" == action:add ]] && input_title=' FAVORIET TOEVOEGEN '
                channel=$(FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' command fzf \
                    "${finder_style[@]}" --height=12 --min-height=10 --disabled --no-info \
                    --border-label="$input_title" --prompt='Kanaal › ' \
                    --header=$'Typ een Twitch-kanaalnaam of plak een Twitch-link.\nEnter bevestigen · Esc/Ctrl-C annuleren' \
                    --bind='enter:accept-or-print-query,ctrl-j:accept-or-print-query,esc:abort' </dev/null) || {
                        TV_TUI_NOTICE='Invoer geannuleerd.'
                        continue
                    }
                if [[ -z "${channel//[[:space:]]/}" ]]; then
                    TV_TUI_NOTICE='Invoer geannuleerd.'
                elif [[ "$choice" == action:add ]]; then
                    TV_TUI_NOTICE=$(python3 "$metadata_helper" --add "$channel" 2>&1) || :
                else
                    _tv_progress 'Kanaal controleren en openen op Apple TV…'
                    TV_TUI_NOTICE=$(_tv_start "$channel" 2>&1) || :
                fi
                ;;

            action:remove)
                if [[ ! -s "$favfile" ]]; then
                    TV_TUI_NOTICE='Er zijn geen kanalen om te verwijderen.'
                    continue
                fi
                remove=$(FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' command fzf \
                    "${finder_style[@]}" \
                    --border-label=' KANAAL VERWIJDEREN ' \
                    --prompt='Verwijder › ' \
                    --header='Klik / Enter verwijderen · Esc terug' \
                    --bind='enter:wait+accept-non-empty,ctrl-j:wait+accept-non-empty,left-click:accept-non-empty,esc:cancel' < "$favfile") || continue

                if [[ -n "$remove" ]]; then
                    TV_TUI_NOTICE=$(python3 "$metadata_helper" --remove "$remove" 2>&1) || :
                fi
                ;;

            action:import)
                _tv_progress 'GUI-follows importeren…'
                TV_TUI_NOTICE=$(tv fav import 2>&1) || :
                ;;

            action:status)
                _tv_progress 'Stream- en tv-status ophalen…'
                TV_TUI_NOTICE=$(tv status 2>&1) || :
                TV_TUI_NOTICE="Op $(date +%H:%M:%S) · $TV_TUI_NOTICE"
                ;;

            action:pair)
                if tv pair; then
                    TV_TUI_NOTICE='Apple TV gekoppeld voor automatisch wakker maken en VLC openen.'
                else
                    TV_TUI_NOTICE='Koppelen niet afgerond. Je kunt dit later opnieuw kiezen.'
                fi
                ;;

            action:settings)
                _tv_settings
                TV_TUI_NOTICE='Instellingen gesloten. Je selectie geldt bij de volgende kanaalkeuze.'
                ;;

            action:stop)
                _tv_progress 'Tv-stream stoppen…'
                TV_TUI_NOTICE=$(tv stop 2>&1) || :
                ;;

            action:log)
                logfiles=()
                [[ -f $TV_STREAM_LOG ]] && logfiles+=("$TV_STREAM_LOG")
                [[ -s $TV_STREAM_ERR ]] && logfiles+=("$TV_STREAM_ERR")
                if (( ${#logfiles} )); then
                    # -X: stay on the menu's screen; less would otherwise leave it on exit.
                    less -X -P 'q: terug  •  F: live volgen  •  :n: volgend log' +G "${logfiles[@]}"
                else
                    TV_TUI_NOTICE='Nog geen Streamlink-log.'
                fi
                ;;

            channel:*)
                channel="${choice#channel:}"
                if [[ "$TV_TUI_VIEW" == offline ]]; then
                    TV_TUI_NOTICE="$channel is offline. Kies een live kanaal."
                else
                    _tv_progress 'Kanaal controleren en openen op Apple TV…'
                    TV_TUI_NOTICE=$(_tv_start "$channel" 2>&1) || :
                fi
                ;;

            noop)
                TV_TUI_NOTICE='Geen kanaal geselecteerd. Kies een overzicht of Beheer & Apple TV.'
                ;;

            *)
                TV_TUI_NOTICE="Actie niet herkend: $choice"
                ;;
        esac
    done
}

_tv_settings() {
    _tv_fullscreen _tv_settings_loop
}

_tv_settings_loop() {
    local rows choice notice=''
    while true; do
        _tv_clear
        rows=$(python3 "$TV_APP_DIR/settings.py" menu) || return 1
        choice=$(print -r -- "$rows" | FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' command fzf \
            --height=100% --layout=reverse --border=rounded --margin=1 --padding=1,2 \
            --border-label=" SOFASTREAM${TV_DEV_MODE:+ @DEV} · INSTELLINGEN " \
            --header-lines=2 --header-first --header="$notice" --prompt='Kies › ' \
            --color='bg:#101019,fg:#cbd5e1,bg+:#29213e,fg+:#ffffff,border:#7c3aed,prompt:#c4b5fd,pointer:#a78bfa' \
            --pointer='▸' --no-sort --delimiter=$'\t' --with-nth=2.. --accept-nth=1 \
            --bind='enter:accept-non-empty,ctrl-j:accept-non-empty,left-click:accept-non-empty,esc:abort') || return 0
        case "$choice" in
            device:*) notice=$(python3 "$TV_APP_DIR/settings.py" select "${choice#device:}" 2>&1) || : ;;
            scan)
                _tv_progress 'Apple TVs zoeken op het lokale netwerk…'
                notice=$(python3 "$TV_APP_DIR/settings.py" scan 2>&1) || :
                ;;
            pair)
                if tv pair; then notice='Apple TV gekoppeld.'; else notice='Koppelen niet afgerond.'; fi
                ;;
            auto|hq|dev-copy) notice=$(python3 "$TV_APP_DIR/settings.py" "$choice" 2>&1) || : ;;
            dev-info) notice=$(python3 "$TV_APP_DIR/settings.py" dev-info 2>&1) || : ;;
        esac
    done
}

tv() {
    local label="$TV_LAUNCH_LABEL"
    local domain="gui/$(id -u)"
    local favfile="$TV_CONFIG_DIR/favorites"
    local tv_notice

    case "$1" in
        --version)
            echo "SofaStream $(cat "$TV_APP_DIR/../VERSION")${TV_DEV_MODE:+ (development)}"
            ;;

        configure)
            python3 "$TV_APP_DIR/settings.py" configure "$2" "$3"
            ;;

        settings|instellingen)
            _tv_settings
            ;;

        dev)
            python3 "$TV_APP_DIR/settings.py" dev-info
            ;;

        "")
            _tv_menu
            ;;

        --help|-h|help)
            local command_name=tv
            [[ "$TV_DEV_MODE" == 1 ]] && command_name=sofastream@dev
            cat <<EOF
📺 SofaStream — Twitch → Apple TV

Gebruik:
  $command_name                    Open interactieve TUI
  $command_name <channel>          Start channel direct

  $command_name status             Toon huidige status
  $command_name stop               Stop huidige stream
  $command_name log                Volg Streamlink-log
  $command_name configure <host> [naam]  Stel Apple TV-adres in
  $command_name settings           Instellingen en Apple TV-selector
  $command_name pair               Koppel automatisch wakker maken en VLC openen (pincode op tv)

  $command_name fav add <channel>  Voeg favoriet toe
  $command_name fav remove <name>  Verwijder kanaal en ster uit tv
  $command_name fav list           Toon alle kanalen in tv
  $command_name fav import         Importeer GUI-follows; behoud bestaande favorieten

  $command_name --help             Toon deze help

In het menu:
  Live kanalen: sterren eerst, daarna op kijkeraantal (hoog naar laag).
  Offline kanalen staan in een apart overzicht.
  Klik of Enter opent een kanaal of menu; de knoppen onderaan zijn klikbaar.
  Ctrl-F zet een ster aan/uit op het geselecteerde kanaal.
  Rechtsklik op een kanaal zet de ster ook aan/uit.
  Ctrl-R ververst; Esc wist eerst de zoekopdracht en gaat daarna terug.
  In invoervelden annuleert Esc direct; in het lege hoofdmenu sluit Esc af.

Voorbeelden:
  $command_name
  $command_name ohnepixel
  $command_name fav add ohnepixel
  $command_name stop

Playback:
  Streamlink low-latency → HTTP :$TV_STREAM_PORT → Apple TV
  Na eenmalig '$command_name pair': zo nodig Apple TV wekken en VLC openen bij kanaalkeuze.
EOF
            ;;

        status)
            node "$TV_APP_DIR/playback.mjs" status
            ;;

        pair)
            "$TV_REMOTE_PYTHON" "$TV_APP_DIR/remote.py" pair
            ;;

        stop)
            # Cancel first: stopping VLC closes the stream, which must not trigger a retry,
            # and a start that is still checking or waking must not go on afterwards.
            _tv_cancel_profile_retry
            _tv_end_session
            # Stop the relay first; VLC then ends the item itself (no 'ended' command).
            if launchctl bootout "$domain/$label" 2>/dev/null; then
                echo "Streamlink: gestopt."
            else
                echo "Streamlink: niet actief."
            fi
            tv_notice=$(node "$TV_APP_DIR/playback.mjs" stop 2>&1) || tv_notice='VLC: stoppen niet bevestigd; geen verbinding of reactie.'
            [[ -n "$tv_notice" ]] && print -r -- "$tv_notice"
            return 0
            ;;

        log)
            if [[ -f $TV_STREAM_LOG ]]; then
                tail -f "$TV_STREAM_LOG"
            else
                echo "Nog geen Streamlink-log."
            fi
            ;;

        fav)
            mkdir -p "$TV_CONFIG_DIR"
            touch "$favfile"

            case "$2" in
                import)
                    node "$TV_APP_DIR/gui-importer/import.mjs" --import
                    ;;

                add)
                    [[ -z "$3" ]] && {
                        echo "Gebruik: tv fav add <channel>"
                        return 1
                    }

                    python3 "$TV_APP_DIR/tui.py" --add "$3"
                    ;;

                remove|rm)
                    [[ -z "$3" ]] && {
                        echo "Gebruik: tv fav remove <channel>"
                        return 1
                    }

                    python3 "$TV_APP_DIR/tui.py" --remove "$3"
                    ;;

                list)
                    if [[ -s "$favfile" ]]; then
                        cat "$favfile"
                    else
                        echo "Nog geen kanalen in tv."
                    fi
                    ;;

                *)
                    echo "Gebruik: tv fav {add|remove|list|import}"
                    return 1
                    ;;
            esac
            ;;

        -*)
            echo "Onbekende optie: $1"
            echo "Gebruik: tv --help"
            return 1
            ;;

        *)
            _tv_start "$1"
            ;;
    esac
}
