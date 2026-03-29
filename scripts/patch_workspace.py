"""Patch root pyproject.toml to narrow the uv workspace for Docker builds.

Usage: python3 scripts/patch_workspace.py packages/shared packages/controller
"""

import pathlib
import re
import sys

members = sys.argv[1:]
p = pathlib.Path("pyproject.toml")
t = p.read_text()

# Narrow workspace members
member_str = ", ".join(f'"{m}"' for m in members)
t = re.sub(r'members = \["packages/\*"\]', f"members = [{member_str}]", t)

# Remove [tool.uv.sources] and [dependency-groups] entries for absent packages
keep_dirs = {m.split("/")[-1] for m in members}
dir_to_pkg = {
    "shared": "concerto-shared",
    "controller": "concerto-controller",
    "agent": "concerto-agent",
    "chaos": "concerto-chaos",
    "dashboard": "concerto-dashboard",
}
for d, pkg in dir_to_pkg.items():
    if d not in keep_dirs:
        t = re.sub(rf"^{re.escape(pkg)} = .*\n", "", t, flags=re.MULTILINE)
        t = re.sub(rf'^\s*"{re.escape(pkg)}",?\n', "", t, flags=re.MULTILINE)

p.write_text(t)
