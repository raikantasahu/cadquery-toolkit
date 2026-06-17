"""T11 (CLI) — geometric owners end-to-end through mesh_step_model.

The CLI config references owners by geometry; they resolve via the resolver and
attach to the correct mesh entities — the consumer path for an external STEP.
"""
import json
import os
import subprocess
import sys

import yaml

from helpers import dist

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_cli_geometric_owners(fixtures, tmp_path):
    step = fixtures["hertz"]["step"]
    out = str(tmp_path / "out.json")
    cfg = {
        "mesh": {"elementType": "tet4", "elementSize": 8.0},
        "owners": [
            {"kind": "face", "at": [15, 15, -40], "area": 900,
             "owner": "fixed-bottom"},
            {"kind": "vertex", "at": [0, 0, -10], "part": 1,
             "owner": "contact-block"},
        ],
        "output": {"format": "json"},
    }
    cfg_path = str(tmp_path / "cfg.yaml")
    with open(cfg_path, "w") as f:
        yaml.safe_dump(cfg, f)

    res = subprocess.run(
        [sys.executable, "mesh_step_model.py", step, cfg_path, "-o", out],
        cwd=APP_DIR, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[-800:]

    data = json.load(open(out))
    nodes = {n["id"]: tuple(n["location"]) for n in data["nodes"]}
    conts = {c["owner"]: c for c in data["meshEntityContainers"]}

    assert "fixed-bottom" in conts and "contact-block" in conts
    fb = conts["fixed-bottom"]["nodeIds"]
    assert fb and all(abs(nodes[n][2] + 40.0) < 1e-6 for n in fb)
    cb = conts["contact-block"]["nodeIds"]
    assert cb and all(dist(nodes[n], (0.0, 0.0, -10.0)) < 1e-6 for n in cb)
