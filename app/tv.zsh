_tv_start() {
    local channel="$1"
    local label="$TV_LAUNCH_LABEL"
    local domain="gui/$(id -u)"
    local streamlink="$(command -v streamlink)"

    [[ -z "$streamlink" ]] && {
        echo "❌ Streamlink niet gevonden."
        return 1
    }

    channel=$(python3 "$TV_APP_DIR/tui.py" --normalize-channel "$channel") || return 1

    # Validate the channel before waking the TV or switching apps.
    python3 "$TV_APP_DIR/tui.py" --check-playable "$channel" || return 1
    node "$TV_APP_DIR/playback.mjs" prepare || return 1
    python3 "$TV_APP_DIR/settings.py" snapshot || return 1

    launchctl bootout "$domain/$label" 2>/dev/null
    rm -f "$TV_STREAM_LOG" "$TV_STREAM_ERR"

    if launchctl submit \
        -l "$label" \
        -o "$TV_STREAM_LOG" \
        -e "$TV_STREAM_ERR" \
        -- "$streamlink" \
        --twitch-low-latency \
        --player-external-http \
        --player-external-http-continuous no \
        --player-external-http-interface 0.0.0.0 \
        --player-external-http-port "$TV_STREAM_PORT" \
        "https://www.twitch.tv/$channel" best
    then
        node "$TV_APP_DIR/playback.mjs" play "$channel"
    else
        echo "❌ Starten mislukt."
        return 1
    fi
}

_tv_menu() {
    local favfile="$TV_CONFIG_DIR/favorites"
    mkdir -p "$TV_CONFIG_DIR"
    touch "$favfile"

    command -v fzf >/dev/null || {
        echo "❌ fzf ontbreekt. Installeer met: brew install fzf"
        return 1
    }

    local items channel choice remove view_label input_title close_label
    local -a logfiles
    local metadata_helper="$TV_APP_DIR/tui.py"
    local -x TV_TUI_VIEW=live
    local -x TV_TUI_COLUMNS=${COLUMNS:-100}
    local -x TV_TUI_NOTICE=''
    local -a refresh_args
    local -a finder_style=(
        --ansi --height=~85% --min-height=16 --layout=reverse
        --border=rounded --margin=1 --padding=1,2
        --pointer='▸' --prompt='Zoek › ' --info=inline-right
        --color='bg:#101019,fg:#cbd5e1,bg+:#29213e,fg+:#ffffff,hl:#c4b5fd,hl+:#e9d5ff,border:#7c3aed,label:#c4b5fd,header:#94a3b8,prompt:#c4b5fd,pointer:#a78bfa,info:#64748b,spinner:#a78bfa'
    )

    while true; do
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
                    echo 'Kanaal controleren en openen op Apple TV…'
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
                echo 'GUI-follows importeren…'
                TV_TUI_NOTICE=$(tv fav import 2>&1) || :
                ;;

            action:status)
                echo 'Stream- en tv-status ophalen…'
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
                echo 'Tv-stream stoppen…'
                TV_TUI_NOTICE=$(tv stop 2>&1) || :
                ;;

            action:log)
                logfiles=()
                [[ -f $TV_STREAM_LOG ]] && logfiles+=("$TV_STREAM_LOG")
                [[ -s $TV_STREAM_ERR ]] && logfiles+=("$TV_STREAM_ERR")
                if (( ${#logfiles} )); then
                    less -P 'q: terug  •  F: live volgen  •  :n: volgend log' +G "${logfiles[@]}"
                else
                    TV_TUI_NOTICE='Nog geen Streamlink-log.'
                fi
                ;;

            channel:*)
                channel="${choice#channel:}"
                if [[ "$TV_TUI_VIEW" == offline ]]; then
                    TV_TUI_NOTICE="$channel is offline. Kies een live kanaal."
                else
                    echo 'Kanaal controleren en openen op Apple TV…'
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
    local rows choice notice=''
    while true; do
        rows=$(python3 "$TV_APP_DIR/settings.py" menu) || return 1
        choice=$(print -r -- "$rows" | FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' command fzf \
            --height=~85% --min-height=16 --layout=reverse --border=rounded --margin=1 --padding=1,2 \
            --border-label=" SOFASTREAM${TV_DEV_MODE:+ @DEV} · INSTELLINGEN " \
            --header-lines=2 --header-first --header="$notice" --prompt='Kies › ' \
            --color='bg:#101019,fg:#cbd5e1,bg+:#29213e,fg+:#ffffff,border:#7c3aed,prompt:#c4b5fd,pointer:#a78bfa' \
            --pointer='▸' --no-sort --delimiter=$'\t' --with-nth=2.. --accept-nth=1 \
            --bind='enter:accept-non-empty,ctrl-j:accept-non-empty,left-click:accept-non-empty,esc:abort') || return 0
        case "$choice" in
            device:*) notice=$(python3 "$TV_APP_DIR/settings.py" select "${choice#device:}" 2>&1) || : ;;
            scan)
                echo 'Apple TVs zoeken op het lokale netwerk…'
                notice=$(python3 "$TV_APP_DIR/settings.py" scan 2>&1) || :
                ;;
            pair)
                if tv pair; then notice='Apple TV gekoppeld.'; else notice='Koppelen niet afgerond.'; fi
                ;;
            auto|dev-copy) notice=$(python3 "$TV_APP_DIR/settings.py" "$choice" 2>&1) || : ;;
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
            cat <<'EOF'
📺 SofaStream — Twitch → Apple TV

Gebruik:
  tv                    Open interactieve TUI
  tv <channel>          Start channel direct

  tv status             Toon huidige status
  tv stop               Stop huidige stream
  tv log                Volg Streamlink-log
  tv configure <host> [naam]  Stel Apple TV-adres in
  tv settings           Instellingen en Apple TV-selector
  tv pair               Koppel automatisch wakker maken en VLC openen (pincode op tv)

  tv fav add <channel>  Voeg favoriet toe
  tv fav remove <name>  Verwijder kanaal en ster uit tv
  tv fav list           Toon alle kanalen in tv
  tv fav import         Importeer GUI-follows; behoud bestaande favorieten

  tv --help             Toon deze help

In het menu:
  Live kanalen: sterren eerst, daarna op kijkeraantal (hoog naar laag).
  Offline kanalen staan in een apart overzicht.
  Klik of Enter opent een kanaal of menu; de knoppen onderaan zijn klikbaar.
  Ctrl-F zet een ster aan/uit op het geselecteerde kanaal.
  Rechtsklik op een kanaal zet de ster ook aan/uit.
  Ctrl-R ververst; Esc wist eerst de zoekopdracht en gaat daarna terug.
  In invoervelden annuleert Esc direct; in het lege hoofdmenu sluit Esc af.

Voorbeelden:
  tv
  tv ohnepixel
  tv fav add ohnepixel
  tv stop

Playback:
  Streamlink low-latency → HTTP :8765 → Apple TV
  Na eenmalig 'tv pair': zo nodig Apple TV wekken en VLC openen bij kanaalkeuze.
EOF
            ;;

        status)
            node "$TV_APP_DIR/playback.mjs" status
            ;;

        pair)
            "$TV_REMOTE_PYTHON" "$TV_APP_DIR/remote.py" pair
            ;;

        stop)
            tv_notice=$(node "$TV_APP_DIR/playback.mjs" stop 2>&1) || tv_notice='VLC: stoppen niet bevestigd; geen verbinding of reactie.'
            if launchctl bootout "$domain/$label" 2>/dev/null; then
                echo "Streamlink: gestopt."
            else
                echo "Streamlink: niet actief."
            fi
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
