"""The agent skill (`skills/manimgx/SKILL.md`) is what `npx skills add academa-labs/manimgx`
and `gh skill install academa-labs/manimgx` install: they find it by its path,
`skills/<name>/SKILL.md`, and read its front matter, which the Agent Skills specification
(https://agentskills.io/specification) constrains. This checks it against the specification:
the name is its folder's, and the description is 1 to 1,024 characters."""

import re
from pathlib import Path

import yaml

SKILL = Path(__file__).parents[2] / "skills" / "manimgx" / "SKILL.md"


def test_its_front_matter_follows_the_specification() -> None:
    text = SKILL.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n.*", text, re.DOTALL)
    assert match, "SKILL.md opens with its front matter, between two `---` lines"
    fields = yaml.safe_load(match[1])
    assert fields["name"] == SKILL.parent.name
    assert isinstance(fields["description"], str)
    assert 1 <= len(fields["description"]) <= 1024
