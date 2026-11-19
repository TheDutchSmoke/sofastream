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
        echo "✕ Streamlink niet gevonden."
        return 1
    }
    [[ -z "$ffmpeg" ]] && {
        echo "✕ ffmpeg niet gevonden. Installeer met: brew install ffmpeg"
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
        echo "✕ Lokaal netwerkadres richting Apple TV niet gevonden."
        return 1
    }

    _tv_owns_session "$session" || { echo "$superseded"; return 1; }
    # A running relay switches inside its stream: VLC keeps its connection and gets no
    # command at all. (VLC 3.0.24 on tvOS fails on a second item in one session.)
    local relay_channel relay_pending relay_viewers relay_version version
    [[ -r "$TV_APP_DIR/../VERSION" ]] && version=$(<"$TV_APP_DIR/../VERSION")
    if read -r relay_channel relay_pending relay_viewers relay_version <<< "$(_tv_relay query)" && [[ -n "$relay_viewers" ]] \
        && [[ -z "$version" || "$relay_version" == "$version" ]]; then
        if [[ "$relay_channel" != "$channel" || "$relay_pending" != - ]]; then
            _tv_relay send switch "$channel" "$hq" >/dev/null || { echo "✕ Wisselen mislukt."; return 1; }
        fi
        if (( relay_viewers > 0 )); then
            local switched=0
            _tv_relay wait "$channel" "${TV_SWITCH_WAIT:-25}" || switched=$?
            case $switched in
                0) echo "▶ Gewisseld naar $channel op de tv." ;;
                2) echo "✕ $channel start niet; het vorige kanaal blijft spelen. Bekijk Beheer → Streamlog." ;;
                *) echo "✕ Wisselen naar $channel niet bevestigd. Bekijk Beheer → Streamlog." ;;
            esac
            return $(( switched != 0 ))
        fi
        # The relay runs but nobody watches: VLC opens it below.
    else
        # Not running, or still the version from before 'brew upgrade': that one's files
        # (stream.zsh for the next source) are gone, so it is replaced below.
        # From here on the job changes; an interrupted start must not leave a server
        # listening without a viewer. Subshells such as $(node …) inherit the trap, so
        # only this shell cleans up; 'return' would lose the status, hence 'exit'.
        # _tv_start always runs in its own process (bin/tv, $(…) in the TUI, the retry).
        local depth=$ZSH_SUBSHELL
        trap '(( ZSH_SUBSHELL > depth )) || _tv_abort_start "$session" "$domain/$label"; exit 130' INT TERM HUP
        launchctl bootout "$domain/$label" 2>/dev/null
        # Keep the previous session's log (Beheer → Streamlog shows the current one).
        local file
        for file in "$TV_STREAM_LOG" "$TV_STREAM_ERR"; do
            [[ -f "$file" ]] && mv -f "$file" "$file.1"
        done

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
            --service "$TV_TWITCH_KEYCHAIN_SERVICE" --channel "$channel" --hq "$hq" --version "$version" || {
                echo "✕ Starten mislukt."
                return 1
            }

        # bootout finishes asynchronously; retry briefly while the old job unloads.
        local attempt started=0
        for attempt in {1..20}; do
            launchctl bootstrap "$domain" "$job" 2>/dev/null && { started=1; break; }
            sleep 0.1
        done
        if (( ! started )); then
            echo "✕ Starten mislukt."
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
        echo "✕ fzf ontbreekt. Installeer met: brew install fzf"
        return 1
    }
    _tv_fullscreen _tv_menu_loop
}

# The menu is a Teletekst page (DESIGN.md): black, nine 256-colour cube colours, a page
# number and running clock on top, coloured buttons below. Every fzf call shares this look.
_tv_fzf_colors='bg:16,fg:231,bg+:21,fg+:231:bold,hl:-1:underline,hl+:-1:underline,border:16,input-border:16,list-border:16,label:231,input-label:231,header:231,footer:231,prompt:51,query:231:regular,disabled:231:regular,ghost:30:regular,pointer:226,info:30,spinner:46,gutter:16'

# Search row info: match count while searching, otherwise the time of the Twitch snapshot.
_tv_fzf_info='if [ -n "$FZF_QUERY" ]; then if [ "$FZF_MATCH_COUNT" = 0 ]; then printf "Geen resultaten · Esc wist"; else printf "%s van %s" "$FZF_MATCH_COUNT" "$FZF_TOTAL_COUNT"; fi; elif [ -n "$TV_TUI_STAND_FILE" ] && read -r stand < "$TV_TUI_STAND_FILE" 2>/dev/null; then printf "stand %s" "$stand"; fi'

# fzf with the shared page: two invisible borders carry the page row (clock) and the stream
# row (polled every 2 s from launchd and the relay log; it never contacts the TV). Binds
# and commands run in POSIX sh. Usage: _tv_fzf PAGE [fzf options…]
_tv_fzf() {
    local page="$1"
    shift
    local tick='start,every(1)'
    [[ "$TV_TUI_MOTION" == 0 ]] && tick=start
    local -a style=(
        --ansi --height=100% --layout=reverse
        --border=top --border-label=' ' --border-label-pos=3
        --input-border=top --input-label=' ' --input-label-pos=3
        --no-separator --no-scrollbar --info=inline-right
        --pointer='▸' --gutter=' ' --highlight-line --cycle --ellipsis='…'
        --footer-border=none
        --bind="$tick:bg-transform-border-label:sh \"\$TV_APP_DIR/tui-clock.sh\" $page${TV_DEV_MODE:+ dev}"
        --bind='start,every(2):bg-transform:node "$TV_APP_DIR/stream-status.mjs" --tui'
    )
    if [[ -n "$NO_COLOR" ]]; then
        style+=(--color=bw)
    else
        style+=(--color="$_tv_fzf_colors")
    fi
    SHELL=/bin/sh FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' command fzf "${style[@]}" "$@"
}

# The bottom row: [Label] key, in fixed Teletekst order and colours; keys only from 60 columns.
# Usage: _tv_buttons LABEL COLOUR KEY [LABEL COLOUR KEY …]
_tv_buttons() {
    local out='' columns=$(_tv_columns)
    while (( $# >= 3 )); do
        [[ -n "$out" ]] && out+='  '
        if [[ -n "$NO_COLOR" ]]; then
            out+="[$1]"
            (( columns >= 60 )) && out+=" $3"
        else
            out+=$'\e[38;5;'"$2m[$1]"$'\e[0m'
            (( columns >= 60 )) && out+=$'\e[38;5;30m'" $3"$'\e[0m'
        fi
        shift 3
    done
    print -r -- "$out"
}

_tv_columns() {
    local size
    size=$(stty size 2>/dev/null)
    if [[ "$size" == <->' '<-> ]] && (( ${size#* } > 0 )); then
        print -r -- "${size#* }"
    else
        print -r -- "${COLUMNS:-80}"
    fi
}

# The number of leading 'header' rows a renderer printed (band, notice, column heads).
_tv_header_rows() {
    local line count=0
    for line in "${(@f)1}"; do
        [[ "$line" == header$'\t'* ]] || break
        count=$(( count + 1 ))
    done
    print -r -- $count
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
    _tv_wait_end
    print -n $'\e[0m\e[?1049l'
}

# Between two fzf runs the page stays black instead of the terminal's own colour.
_tv_clear() {
    _tv_wait_end
    if [[ -n "$NO_COLOR" ]]; then
        print -n $'\e[0m\e[H\e[2J'
    else
        print -n $'\e[0;48;5;16m\e[H\e[2J'
    fi
}

# Title band in zsh for the pages tv.zsh draws itself (wait, pairing). Usage: TITLE RIGHT WIDTH
_tv_band() {
    local title=" $1 " right="$2" width=$3 bg=21 fg=226 rfg=231
    [[ -n "$TV_DEV_MODE" ]] && bg=201 fg=16 rfg=16
    local gap=$(( width - ${#title} - ${#right} - ${#${right:+x}} ))
    (( gap < 0 )) && gap=0
    if [[ -n "$NO_COLOR" ]]; then
        print -rn -- "$title$(printf '%*s' $gap '')$right"
    else
        print -rn -- $'\e[1;38;5;'"$fg;48;5;${bg}m$title"$'\e[0;38;5;'"$rfg;48;5;${bg}m$(printf '%*s' $gap '')$right${right:+ }"$'\e[0;48;5;16m'
    fi
}

# Rows 1, 2 and 4 of a page tv.zsh draws itself, in the same place as in the menu.
_tv_static_page() {
    local page="$1" title="$2" channel="$3" columns=$(_tv_columns)
    _tv_clear
    print -rn -- $'\e[1;3H'"$(FZF_COLUMNS=$columns TV_TUI_MOTION=${TV_TUI_MOTION:-1} sh "$TV_APP_DIR/tui-clock.sh" "$page" ${TV_DEV_MODE:+dev})"
    # Nothing polls the stream here, so this row never looks live: it says what is busy.
    print -rn -- $'\e[2;3H\e[38;5;226m▷ BEZIG'"${channel:+  }"$'\e[1;38;5;231m'"$channel"$'\e[0;48;5;16m'
    print -rn -- $'\e[4;3H'"$(_tv_band "$title" '' $(( columns - 2 )))"
}

# A wait page while an action runs between two fzf runs. The message goes in row 5.
# Usage: _tv_progress PAGE MESSAGE [CHANNEL]
_tv_progress() {
    local page="$1" message="$2" channel="$3"
    _tv_static_page "$page" 'EVEN GEDULD' "$channel"
    print -rn -- $'\e[5;3H\e[38;5;231m'"$message"$'\e[7;3H\e[38;5;30mCtrl-C breekt af.\e[0;48;5;16m\e[8;1H'
    [[ "$TV_TUI_MOTION" == 0 || -n "$NO_COLOR" ]] && return
    _tv_wait_motion "$(_tv_columns)" &
    typeset -g _tv_wait_pid=$!
}

# The only animation outside fzf: a page counter that rolls like a Teletekst decoder
# looking for its page, the clock, and the seconds in the band. It writes only to fixed
# cells and stops when the menu shell is gone; _tv_clear and the exit trap end it first.
_tv_wait_motion() {
    local columns="$1" page=100 started=$SECONDS last=-1 header
    trap 'exit 0' TERM HUP INT
    while kill -0 $$ 2>/dev/null; do
        if (( SECONDS - started != last )); then
            last=$(( SECONDS - started ))
            header=$(FZF_COLUMNS=$columns sh "$TV_APP_DIR/tui-clock.sh" "$page" ${TV_DEV_MODE:+dev})
            print -rn -- $'\e7\e[1;3H'"$header"$'\e[4;3H'"$(_tv_band 'EVEN GEDULD' "$last s" $(( columns - 2 )))"$'\e8'
        fi
        print -rn -- $'\e7\e[1;3H\e[38;5;46mP'"$page"$'\e[0;48;5;16m\e8'
        page=$(( page >= 899 ? 100 : page + 1 ))
        sleep 0.1
    done
}

_tv_wait_end() {
    [[ -n "$_tv_wait_pid" ]] || return 0
    kill -TERM "$_tv_wait_pid" 2>/dev/null
    wait "$_tv_wait_pid" 2>/dev/null
    typeset -g _tv_wait_pid=''
}

# Page 220: rows 1–4 like every page; 'tv pair' prints its lines and reads the PIN below.
_tv_pair_page() {
    _tv_static_page 220 'APPLE TV KOPPELEN'
    print -rn -- $'\e[5;1H\e[38;5;231;48;5;16m'
    tv pair
}

# Pages 201 and 202: one input row, with a live check of what the input becomes.
# Usage: _tv_input other|add. Prints the query; fails when cancelled.
_tv_input() {
    local dialog="$1" page=201 confirm=Openen
    [[ "$dialog" == add ]] && page=202 confirm=Toevoegen
    local -x TV_TUI_DIALOG_HEAD
    TV_TUI_DIALOG_HEAD=$(python3 "$TV_APP_DIR/tui.py" --dialog "$dialog" --color) || return 1
    _tv_fzf $page --disabled --no-info --prompt='  Kanaal › ' --ghost='naam of twitch.tv/…' \
        --header="$TV_TUI_DIALOG_HEAD" --footer="$(_tv_buttons Annuleren 196 Esc "$confirm" 46 Enter)" \
        --bind='change:transform-header(sh "$TV_APP_DIR/tui-check.sh")' \
        --bind='enter:accept-or-print-query,ctrl-j:accept-or-print-query,esc:abort' \
        --bind='click-footer:transform:case "$FZF_CLICK_FOOTER_WORD" in "[Annuleren]") echo abort;; "['"$confirm"']") echo accept-or-print-query;; esac' \
        </dev/null
}

# Run an action and keep its output as the notice; the exit status sets its colour.
_tv_notice() {
    if TV_TUI_NOTICE=$("$@" 2>&1); then
        TV_TUI_NOTICE_KIND=ok
    else
        TV_TUI_NOTICE_KIND=error
    fi
}

_tv_menu_loop() {
    setopt localoptions extendedglob
    local favfile="$TV_CONFIG_DIR/favorites"
    mkdir -p "$TV_CONFIG_DIR"
    touch "$favfile"

    local items channel choice remove page header_rows footer jumps number target
    local -a logfiles
    local metadata_helper="$TV_APP_DIR/tui.py"
    local -x TV_TUI_VIEW=live TV_TUI_COLUMNS TV_TUI_NOTICE='' TV_TUI_NOTICE_KIND='' TV_TUI_NOTICE_ROWS=''
    local -x TV_TUI_RELOAD='' TV_TUI_STAND_FILE=''
    local stand="${TV_CACHE_DIR:-$HOME/.cache/tv}/tui-stand"
    # Cached render for the width fzf reports (resize) and for the stream poll when the
    # channel that goes to the TV changes, so the ▶ in the list follows the stream row.
    local render='python3 "$TV_APP_DIR/tui.py" --render-after-action --view "$TV_TUI_VIEW" --color --columns "$FZF_COLUMNS"'

    while true; do
        _tv_clear
        TV_TUI_COLUMNS=$(_tv_columns)
        TV_TUI_NOTICE_ROWS=''
        items=$(python3 "$metadata_helper" --view "$TV_TUI_VIEW" --color) || return 1
        # --header-lines is fixed for one fzf run; reloads render the same notice height.
        header_rows=$(_tv_header_rows "$items")
        TV_TUI_NOTICE_ROWS=$(( header_rows - 2 ))
        TV_TUI_RELOAD="$render"
        TV_TUI_STAND_FILE="$stand"
        case "$TV_TUI_VIEW" in
            live)
                page=101
                footer=$(_tv_buttons Sluiten 196 Esc Verversen 46 '^R' Favoriet 226 '^F' Beheer 51 200)
                ;;
            offline|unknown)
                page=102
                [[ "$TV_TUI_VIEW" == unknown ]] && page=103
                footer=$(_tv_buttons Terug 196 Esc Verversen 46 '^R' Favoriet 226 '^F' Beheer 51 200)
                ;;
            manage)
                page=200
                TV_TUI_RELOAD='' TV_TUI_STAND_FILE=''
                footer=$(_tv_buttons Terug 196 Esc Instellingen 51 300)
                ;;
        esac
        # Typing a page number opens that page at once; opening a view is harmless.
        # Actions always need Enter.
        jumps='case "$FZF_QUERY" in'
        for number target in 101 view:live 102 view:offline 103 view:unknown 200 view:manage 300 action:settings; do
            (( number == page )) || jumps+=" $number) echo \"become(echo $target)\";;"
        done
        jumps+=' esac'

        choice=$(print -r -- "$items" | _tv_fzf $page \
            --prompt='  Zoek › ' --ghost='kanaal, game of paginanummer' --info-command="$_tv_fzf_info" \
            --header-lines="$header_rows" --footer="$footer" \
            --no-sort --track --id-nth=1 \
            --delimiter=$'\t' \
            --with-nth=2.. \
            --accept-nth=1 \
            --bind='enter:wait+accept-non-empty,ctrl-j:wait+accept-non-empty,left-click:accept-non-empty,right-click:trigger(ctrl-f),esc:cancel' \
            --bind='click-footer:transform:case "$FZF_CLICK_FOOTER_WORD" in "[Favoriet]") echo "trigger(ctrl-f)";; "[Verversen]") echo "trigger(ctrl-r)";; "[Terug]"|"[Sluiten]") echo abort;; "[Beheer]") echo "become(echo view:manage)";; "[Instellingen]") echo "become(echo action:settings)";; esac' \
            --bind="change:transform:$jumps" \
            --bind='ctrl-r:change-prompt(  Ververst… › )+reload(python3 "$TV_APP_DIR/tui.py" --view "$TV_TUI_VIEW" --color --force --columns "$FZF_COLUMNS")' \
            --bind='ctrl-f:reload(python3 "$TV_APP_DIR/tui.py" --toggle-key {1} --render-after-action --view "$TV_TUI_VIEW" --color --columns "$FZF_COLUMNS")' \
            --bind="resize:reload($render)" \
            --bind='load:change-prompt(  Zoek › )') || {
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
                _tv_clear
                channel=$(_tv_input "${choice#action:}") || {
                    TV_TUI_NOTICE='Invoer geannuleerd.' TV_TUI_NOTICE_KIND=info
                    continue
                }
                if [[ -z "${channel//[[:space:]]/}" ]]; then
                    TV_TUI_NOTICE='Invoer geannuleerd.' TV_TUI_NOTICE_KIND=info
                elif [[ "$choice" == action:add ]]; then
                    _tv_notice python3 "$metadata_helper" --add "$channel"
                else
                    _tv_progress $page 'Kanaal controleren en openen op Apple TV…'
                    _tv_notice _tv_start "$channel"
                fi
                ;;

            action:remove)
                if [[ ! -s "$favfile" ]]; then
                    TV_TUI_NOTICE='Er zijn geen kanalen om te verwijderen.' TV_TUI_NOTICE_KIND=info
                    continue
                fi
                _tv_clear
                items=$(python3 "$metadata_helper" --view remove --color) || return 1
                # Page 203 is the one page where Enter removes something: its band is red.
                remove=$(TV_TUI_RELOAD='' TV_TUI_STAND_FILE='' && print -r -- "$items" | _tv_fzf 203 \
                    --prompt='  Verwijder › ' --ghost='typ om te zoeken' --info-command="$_tv_fzf_info" \
                    --header-lines="$(_tv_header_rows "$items")" --footer="$(_tv_buttons Terug 196 Esc)" \
                    --no-sort --delimiter=$'\t' --with-nth=2.. --accept-nth=1 \
                    --bind='enter:wait+accept-non-empty,ctrl-j:wait+accept-non-empty,left-click:accept-non-empty,esc:cancel' \
                    --bind='click-footer:transform:case "$FZF_CLICK_FOOTER_WORD" in "[Terug]") echo abort;; esac') || continue

                if [[ -n "$remove" ]]; then
                    _tv_notice python3 "$metadata_helper" --remove "$remove"
                fi
                ;;

            action:import)
                _tv_progress 204 'GUI-follows importeren…'
                _tv_notice tv fav import
                ;;

            action:status)
                _tv_progress 210 'Stream- en tv-status ophalen…'
                TV_TUI_NOTICE=$(tv status 2>&1)
                # A dated snapshot; the PID stays on the command line ('tv status').
                TV_TUI_NOTICE="Op $(date +%H:%M:%S) · ${TV_TUI_NOTICE// · PID [0-9]##/}"
                TV_TUI_NOTICE_KIND=info
                ;;

            action:pair)
                if _tv_pair_page; then
                    TV_TUI_NOTICE='Apple TV gekoppeld voor automatisch wakker maken en VLC openen.' TV_TUI_NOTICE_KIND=ok
                else
                    TV_TUI_NOTICE='Koppelen niet afgerond. Je kunt dit later opnieuw kiezen.' TV_TUI_NOTICE_KIND=error
                fi
                ;;

            action:settings)
                _tv_settings
                TV_TUI_NOTICE='Instellingen gesloten. Je selectie geldt bij de volgende kanaalkeuze.' TV_TUI_NOTICE_KIND=info
                ;;

            action:stop)
                _tv_progress 211 'Tv-stream stoppen…'
                _tv_notice tv stop
                ;;

            action:log)
                logfiles=()
                [[ -f $TV_STREAM_LOG ]] && logfiles+=("$TV_STREAM_LOG")
                [[ -s $TV_STREAM_ERR ]] && logfiles+=("$TV_STREAM_ERR")
                if (( ${#logfiles} )); then
                    # The log keeps the terminal's own colours. -X: stay on the menu's
                    # screen; less would otherwise leave it on exit.
                    print -n $'\e[0m\e[H\e[2J'
                    less -X -P 'q: terug  •  F: live volgen  •  :n: volgend log' +G "${logfiles[@]}"
                else
                    TV_TUI_NOTICE='Nog geen Streamlink-log.' TV_TUI_NOTICE_KIND=info
                fi
                ;;

            channel:*)
                channel="${choice#channel:}"
                if [[ "$TV_TUI_VIEW" == offline ]]; then
                    TV_TUI_NOTICE="$channel is offline. Kies een live kanaal." TV_TUI_NOTICE_KIND=error
                else
                    _tv_progress $page 'Kanaal controleren en openen op Apple TV…' "$channel"
                    _tv_notice _tv_start "$channel"
                fi
                ;;

            noop)
                TV_TUI_NOTICE='Geen kanaal geselecteerd. Kies een overzicht of Beheer & Apple TV.' TV_TUI_NOTICE_KIND=info
                ;;

            *)
                TV_TUI_NOTICE="Actie niet herkend: $choice" TV_TUI_NOTICE_KIND=error
                ;;
        esac
    done
}

_tv_settings() {
    _tv_fullscreen _tv_settings_loop
}

_tv_settings_loop() {
    local rows choice
    local -x TV_TUI_NOTICE='' TV_TUI_NOTICE_KIND='' TV_TUI_NOTICE_ROWS='' TV_TUI_RELOAD='' TV_TUI_STAND_FILE=''
    local -x TV_TUI_COLUMNS
    while true; do
        _tv_clear
        TV_TUI_COLUMNS=$(_tv_columns)
        TV_TUI_NOTICE_ROWS=''
        rows=$(python3 "$TV_APP_DIR/settings.py" menu --color "$TV_TUI_COLUMNS") || return 1
        TV_TUI_NOTICE_ROWS=$(( $(_tv_header_rows "$rows") - 2 ))
        choice=$(print -r -- "$rows" | _tv_fzf 300 \
            --prompt='  Kies › ' --ghost='typ om te zoeken' --info-command="$_tv_fzf_info" \
            --header-lines="$(_tv_header_rows "$rows")" --footer="$(_tv_buttons Terug 196 Esc)" \
            --no-sort --delimiter=$'\t' --with-nth=2.. --accept-nth=1 \
            --bind='enter:accept-non-empty,ctrl-j:accept-non-empty,left-click:accept-non-empty,esc:abort' \
            --bind='click-footer:transform:case "$FZF_CLICK_FOOTER_WORD" in "[Terug]") echo abort;; esac' \
            --bind='resize:reload(python3 "$TV_APP_DIR/settings.py" menu --color "$FZF_COLUMNS")') || return 0
        TV_TUI_NOTICE_KIND=''
        case "$choice" in
            device:*) _tv_notice python3 "$TV_APP_DIR/settings.py" select "${choice#device:}" ;;
            scan)
                _tv_progress 300 'Apple TVs zoeken op het lokale netwerk…'
                _tv_notice python3 "$TV_APP_DIR/settings.py" scan
                ;;
            pair)
                if _tv_pair_page; then
                    TV_TUI_NOTICE='Apple TV gekoppeld.' TV_TUI_NOTICE_KIND=ok
                else
                    TV_TUI_NOTICE='Koppelen niet afgerond.' TV_TUI_NOTICE_KIND=error
                fi
                ;;
            auto|hq|dev-copy) _tv_notice python3 "$TV_APP_DIR/settings.py" "$choice" ;;
            dev-info)
                _tv_notice python3 "$TV_APP_DIR/settings.py" dev-info
                [[ "$TV_TUI_NOTICE_KIND" == ok ]] && TV_TUI_NOTICE_KIND=info
                ;;
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
SofaStream — Twitch → Apple TV

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

In het menu (een teletekstpagina):
  Live kanalen: sterren eerst, daarna op kijkeraantal (hoog naar laag).
  Offline kanalen staan in een apart overzicht.
  Klik of Enter opent een kanaal of menu; de knoppen onderaan zijn klikbaar.
  Typ 101 (live), 102 (offline), 103 (onbekend), 200 (beheer) of 300 (instellingen)
  om die pagina direct te openen.
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
