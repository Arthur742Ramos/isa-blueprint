"""Shell completion script generation.

``isabelle-blueprint completion {bash,zsh,fish}`` prints a ready-to-source
completion script.  The scripts are generated from the live list of subcommands
so they never drift from the parser, and they complete subcommand names (then
fall back to the shell's default file completion for arguments).  No third-party
dependency (such as argcomplete) is required.
"""
from __future__ import annotations

SUPPORTED_SHELLS = ("bash", "zsh", "fish")


def render_completion(shell: str, prog: str, commands: list[str]) -> str:
    """Return a completion script for ``shell``.

    ``prog`` is the executable name (e.g. ``isabelle-blueprint``) and
    ``commands`` is the ordered list of subcommand names.
    """

    if shell == "bash":
        return _bash(prog, commands)
    if shell == "zsh":
        return _zsh(prog, commands)
    if shell == "fish":
        return _fish(prog, commands)
    raise ValueError(f"unsupported shell {shell!r}; choose one of: {', '.join(SUPPORTED_SHELLS)}")


def _func_slug(prog: str) -> str:
    return prog.replace("-", "_").replace(".", "_")


def _bash(prog: str, commands: list[str]) -> str:
    words = " ".join(commands)
    fn = f"_{_func_slug(prog)}_completion"
    return f"""# bash completion for {prog}
# Install: source <({prog} completion bash)
{fn}() {{
    local cur prev words cword
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{words}" -- "$cur") )
        return 0
    fi
    COMPREPLY=( $(compgen -f -- "$cur") )
    return 0
}}
complete -F {fn} {prog}
"""


def _zsh(prog: str, commands: list[str]) -> str:
    words = " ".join(commands)
    fn = f"_{_func_slug(prog)}_completion"
    return f"""#compdef {prog}
# zsh completion for {prog}
# Install: source <({prog} completion zsh)
{fn}() {{
    local -a commands
    commands=({words})
    if (( CURRENT == 2 )); then
        compadd -- $commands
    else
        _files
    fi
}}
compdef {fn} {prog}
"""


def _fish(prog: str, commands: list[str]) -> str:
    lines = [
        f"# fish completion for {prog}",
        f"# Install: {prog} completion fish | source",
        f"complete -c {prog} -f",
    ]
    for command in commands:
        lines.append(
            f"complete -c {prog} -n '__fish_use_subcommand' -a {command}"
        )
    return "\n".join(lines) + "\n"
