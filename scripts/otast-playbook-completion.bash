# Bash completion for the sourceable `otast` command.

_otast_playbook_target_words() {
    local repo
    repo=${OTAST_REPO_ROOT:-${HOME:-}/repos/otast}
    if command -v jq >/dev/null 2>&1 && [[ -f $repo/compatibility/supported-targets.json ]]; then
        jq -r '.targets | keys[]' "$repo/compatibility/supported-targets.json" 2>/dev/null
    fi
}

_otast_playbook_complete() {
    local current command words actions modes commands
    local -a matches target_words root_words

    COMPREPLY=()
    current=${COMP_WORDS[COMP_CWORD]}
    command=${COMP_WORDS[1]:-}

    commands='help commands version doctor status maintain monitor review accept cleanup prepush test audit authority build source synthetic capture fixtures reset refresh upstream action prove export qualify release cd'
    actions='report status preflight apply reboot verify restore boot-recover'
    modes='quick standard full'
    mapfile -t target_words < <(_otast_playbook_target_words)

    if ((COMP_CWORD == 1)); then
        mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$current")
        return 0
    fi

    case $command in
        help)
            mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$current")
            ;;
        test)
            mapfile -t COMPREPLY < <(compgen -W "$modes" -- "$current")
            ;;
        maintain)
            mapfile -t COMPREPLY < <(compgen -W '--quick --full --audit --device-proof --keep' -- "$current")
            ;;
        monitor)
            mapfile -t COMPREPLY < <(compgen -W '--output --keep --no-cleanup' -- "$current")
            ;;
        review)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W "${target_words[*]}" -- "$current")
            else
                mapfile -t COMPREPLY < <(compgen -W '--observed --fixture --name --keep' -- "$current")
            fi
            ;;
        accept)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W "${target_words[*]}" -- "$current")
            else
                mapfile -t COMPREPLY < <(compgen -W '--review --keep' -- "$current")
            fi
            ;;
        cleanup)
            mapfile -t COMPREPLY < <(compgen -W '--category --keep --dry-run all target-monitor target-review maintenance' -- "$current")
            ;;
        action)
            if ((COMP_CWORD == 2)); then
                words='latest'
                root_words=()
                if [[ -d ${HOME:-}/.cache/otast/fake-roots ]]; then
                    for item in "${HOME}"/.cache/otast/fake-roots/*; do
                        [[ -d $item && ! -L $item ]] || continue
                        root_words+=("${item##*/}")
                    done
                fi
                words+=" ${root_words[*]}"
                mapfile -t COMPREPLY < <(compgen -W "$words" -- "$current")
            else
                mapfile -t COMPREPLY < <(compgen -W "$actions" -- "$current")
            fi
            ;;
        refresh)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W 'device fixture upstream' -- "$current")
            else
                mapfile -t COMPREPLY < <(compgen -W '--label --name --prove --restore-clone --fixture --tree --ref --tag --include-prerelease --asset --asset-regex --no-compare latest' -- "$current")
            fi
            ;;
        upstream)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W 'ref fetch-ref assets fetch analyse materialize compare show' -- "$current")
            else
                mapfile -t COMPREPLY < <(compgen -W '--ref --tag --include-prerelease --asset --asset-regex --force --tree --active-tree --candidate-tree --output latest' -- "$current")
            fi
            ;;
        reset|prove)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W 'latest' -- "$current")
                compopt -o filenames 2>/dev/null || true
                mapfile -t matches < <(compgen -d -- "$current")
                COMPREPLY+=("${matches[@]}")
            elif [[ $command == prove ]]; then
                mapfile -t matches < <(compgen -W '--restore-clone' -- "$current")
                COMPREPLY+=("${matches[@]}")
            fi
            ;;
        export)
            if ((COMP_CWORD == 2)); then
                mapfile -t COMPREPLY < <(compgen -W 'latest' -- "$current")
                compopt -o filenames 2>/dev/null || true
                mapfile -t matches < <(compgen -d -- "$current")
                COMPREPLY+=("${matches[@]}")
            else
                compopt -o filenames 2>/dev/null || true
                mapfile -t COMPREPLY < <(compgen -f -- "$current")
            fi
            ;;
        qualify)
            mapfile -t COMPREPLY < <(compgen -W '--fixture --output --skip-device --allow-dirty --help' -- "$current")
            ;;
        release)
            mapfile -t COMPREPLY < <(compgen -W '--version --yes --no-reboot --no-publish --status --reset --help' -- "$current")
            ;;
        authority|build|source|audit|capture)
            compopt -o filenames 2>/dev/null || true
            mapfile -t COMPREPLY < <(compgen -f -- "$current")
            ;;
    esac
}

complete -F _otast_playbook_complete otast
