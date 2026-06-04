"""Shell completion script generation.

``isabelle-blueprint completion {bash,zsh,fish,powershell}`` prints a
ready-to-source completion script.  The scripts are generated from the live
parser so they never drift: they complete subcommand names first, then the
options of the chosen subcommand (any word starting with ``-``), and otherwise
fall back to the shell's default file completion.  No third-party dependency
(such as argcomplete) is required.
"""
from __future__ import annotations

SUPPORTED_SHELLS = ("bash", "zsh", "fish", "powershell")


def render_completion(
    shell: str,
    prog: str,
    commands: list[str],
    options: dict[str, list[str]] | None = None,
) -> str:
    """Return a completion script for ``shell``.

    ``prog`` is the executable name (e.g. ``isabelle-blueprint``), ``commands``
    is the ordered list of subcommand names, and ``options`` optionally maps each
    subcommand name to its option strings (e.g. ``{"lint": ["--json", ...]}``) so
    the generated script can also complete flags after a subcommand.
    """

    options = options or {}
    if shell == "bash":
        return _bash(prog, commands, options)
    if shell == "zsh":
        return _zsh(prog, commands, options)
    if shell == "fish":
        return _fish(prog, commands, options)
    if shell == "powershell":
        return _powershell(prog, commands, options)
    raise ValueError(f"unsupported shell {shell!r}; choose one of: {', '.join(SUPPORTED_SHELLS)}")


def _func_slug(prog: str) -> str:
    return prog.replace("-", "_").replace(".", "_")


def _bash(prog: str, commands: list[str], options: dict[str, list[str]]) -> str:
    words = " ".join(commands)
    fn = f"_{_func_slug(prog)}_completion"
    case_lines = [
        f"        {command}) opts=\"{' '.join(options[command])}\" ;;"
        for command in commands
        if options.get(command)
    ]
    option_block = ""
    if case_lines:
        cases = "\n".join(case_lines)
        option_block = (
            f'    local sub="${{COMP_WORDS[1]}}"\n'
            f'    local opts=""\n'
            f'    case "$sub" in\n'
            f"{cases}\n"
            f"    esac\n"
            f'    if [[ "$cur" == -* ]]; then\n'
            f'        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )\n'
            f"        return 0\n"
            f"    fi\n"
        )
    return f"""# bash completion for {prog}
# Install: source <({prog} completion bash)
{fn}() {{
    local cur
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{words}" -- "$cur") )
        return 0
    fi
{option_block}    COMPREPLY=( $(compgen -f -- "$cur") )
    return 0
}}
complete -F {fn} {prog}
"""


def _zsh(prog: str, commands: list[str], options: dict[str, list[str]]) -> str:
    words = " ".join(commands)
    fn = f"_{_func_slug(prog)}_completion"
    case_lines = [
        f"            {command}) opts=({' '.join(options[command])}) ;;"
        for command in commands
        if options.get(command)
    ]
    option_block = ""
    if case_lines:
        cases = "\n".join(case_lines)
        option_block = (
            f"        local -a opts\n"
            f'        case "${{words[2]}}" in\n'
            f"{cases}\n"
            f"        esac\n"
            f'        if [[ "${{words[CURRENT]}}" == -* ]]; then\n'
            f"            compadd -- $opts\n"
            f"            return\n"
            f"        fi\n"
        )
    return f"""#compdef {prog}
# zsh completion for {prog}
# Install: source <({prog} completion zsh)
{fn}() {{
    local -a commands
    commands=({words})
    if (( CURRENT == 2 )); then
        compadd -- $commands
    else
{option_block}        _files
    fi
}}
compdef {fn} {prog}
"""


def _fish_option_flag(opt: str) -> str:
    if opt.startswith("--"):
        return f"-l {opt[2:]}"
    if opt.startswith("-") and len(opt) == 2:
        return f"-s {opt[1:]}"
    return ""


def _fish(prog: str, commands: list[str], options: dict[str, list[str]]) -> str:
    lines = [
        f"# fish completion for {prog}",
        f"# Install: {prog} completion fish | source",
        f"complete -c {prog} -f",
    ]
    for command in commands:
        lines.append(
            f"complete -c {prog} -n '__fish_use_subcommand' -a {command}"
        )
    for command in commands:
        for opt in options.get(command, []):
            flag = _fish_option_flag(opt)
            if flag:
                lines.append(
                    f"complete -c {prog} -n '__fish_seen_subcommand_from {command}' {flag}"
                )
    return "\n".join(lines) + "\n"


def _ps_quote(opt: str) -> str:
    return "'" + opt.replace("'", "''") + "'"


def _powershell(prog: str, commands: list[str], options: dict[str, list[str]]) -> str:
    words = ", ".join(f"'{command}'" for command in commands)
    option_lines = [
        f"        '{command}' = @({', '.join(_ps_quote(opt) for opt in options[command])})"
        for command in commands
        if options.get(command)
    ]
    if option_lines:
        options_literal = "@{\n" + "\n".join(option_lines) + "\n    }"
    else:
        options_literal = "@{}"
    return f"""# PowerShell completion for {prog}
# Install (current session): {prog} completion powershell | Out-String | Invoke-Expression
# Persist: add the line above to your PowerShell $PROFILE
Register-ArgumentCompleter -Native -CommandName '{prog}' -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $crt = [System.Management.Automation.CompletionResult]
    $commands = @({words})
    $options = {options_literal}
    $priorCount = $commandAst.CommandElements.Count
    if ($wordToComplete) {{ $priorCount-- }}
    if ($priorCount -le 1) {{
        $commands |
            Where-Object {{ $_ -like "$wordToComplete*" }} |
            ForEach-Object {{ $crt::new($_, $_, 'ParameterValue', $_) }}
        return
    }}
    if ($wordToComplete -like '-*') {{
        $sub = $commandAst.CommandElements[1].Extent.Text
        if ($options.ContainsKey($sub)) {{
            $options[$sub] |
                Where-Object {{ $_ -like "$wordToComplete*" }} |
                ForEach-Object {{ $crt::new($_, $_, 'ParameterName', $_) }}
        }}
    }}
}}
"""
