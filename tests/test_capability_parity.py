from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

import yaml

from isabelle_blueprint.cli import _build_parser

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "capability-parity.toml"


def _inventory() -> dict:
    return tomllib.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _cli_surface(mapping: dict[str, list[str]]) -> set[str]:
    return {item for values in mapping.values() for item in values}


def _cli_commands_and_aliases() -> tuple[set[str], dict[str, str]]:
    parser = _build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    canonical_by_parser: dict[int, str] = {}
    aliases: dict[str, str] = {}
    for name, command_parser in subparsers.choices.items():
        key = id(command_parser)
        canonical = canonical_by_parser.setdefault(key, name)
        if name != canonical:
            aliases[name] = canonical
    return set(canonical_by_parser.values()), aliases


def test_inventory_classifies_every_cli_command_and_alias() -> None:
    inventory = _inventory()
    commands, aliases = _cli_commands_and_aliases()
    classified = {command for group in inventory["cli"]["omissions"].values() for command in group}
    for surface in ("mcp", "vscode", "action"):
        classified.update(inventory[surface]["cli"])

    assert inventory["schema_version"] == 1
    assert inventory["cli"]["aliases"] == aliases
    assert classified == commands


def test_mcp_tool_registrations_match_inventory() -> None:
    inventory = _inventory()
    source = (ROOT / "isabelle_blueprint" / "mcp_server.py").read_text(encoding="utf-8")
    registered = set(re.findall(r'@server\.tool\(name="([^"]+)"\)', source))
    expected = set(inventory["mcp"]["native_tools"])
    expected.update(_cli_surface(inventory["mcp"]["cli"]))

    assert registered == expected


def test_vscode_contributions_registrations_and_cli_wiring_match_inventory() -> None:
    inventory = _inventory()
    package = json.loads((ROOT / "vscode" / "package.json").read_text(encoding="utf-8"))
    source = (ROOT / "vscode" / "src" / "extension.ts").read_text(encoding="utf-8")
    contributed = {item["command"] for item in package["contributes"]["commands"]}
    registered = set(re.findall(r'registerCommand\(\s*"([^"]+)"', source, flags=re.MULTILINE))
    expected_contributed = set(inventory["vscode"]["native_commands"])
    expected_contributed.update(_cli_surface(inventory["vscode"]["cli"]))
    expected_registered = expected_contributed | set(inventory["vscode"]["internal_commands"])

    assert contributed == expected_contributed
    assert registered == expected_registered

    for cli_command, command_ids in inventory["vscode"]["cli"].items():
        for command_id in command_ids:
            if ".run" not in command_id:
                continue
            pattern = (
                rf'registerCommand\("{re.escape(command_id)}".{{0,240}}'
                rf'runBlueprintCommand\("{re.escape(cli_command)}"'
            )
            assert re.search(pattern, source, flags=re.DOTALL), command_id


def test_action_cli_steps_match_inventory() -> None:
    inventory = _inventory()
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    invoked: list[str] = []
    for step in action["runs"]["steps"]:
        match = re.match(r"isabelle-blueprint ([a-z-]+)", step.get("run", ""))
        if match:
            invoked.append(match.group(1))

    assert len(invoked) == len(set(invoked))
    assert set(invoked) == _cli_surface(inventory["action"]["cli"])
