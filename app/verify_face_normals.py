#!/usr/bin/env python3
"""Check that every boundary face in a mesh JSON points outward.

Outward is judged per face against its parent volume element's centroid (a
point just inside the solid, local to the face — so holes / non-convex parts
are handled correctly). Reports any inward-pointing faces.

Usage:  python3 verify_face_normals.py <mesh.json> [<mesh.json> ...]
"""
import json
import sys
from collections import defaultdict


def _newell(ns, pos):
    nx = ny = nz = 0.0
    k = len(ns)
    for i in range(k):
        x0, y0, z0 = pos[ns[i]]
        x1, y1, z1 = pos[ns[(i + 1) % k]]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return nx, ny, nz


def check(path):
    d = json.load(open(path))
    pos = {n["id"]: tuple(map(float, n["location"])) for n in d["nodes"]}
    n2e = defaultdict(list)
    cent = []
    for f in d["fragments"]:
        for e in f["elements"]:
            en = e["nodes"]
            idx = len(cent)
            cent.append(tuple(sum(pos[t][i] for t in en) / len(en)
                              for i in range(3)))
            for t in en:
                n2e[t].append(idx)

    inward = 0
    total = 0
    for fa in d["boundaryFaces"]:
        fn = fa["nodes"]
        common = set(n2e.get(fn[0], ()))
        for x in fn[1:]:
            common.intersection_update(n2e.get(x, ()))
        if not common:
            continue
        total += 1
        cx, cy, cz = cent[next(iter(common))]
        nx, ny, nz = _newell(fn, pos)
        fc = [sum(pos[t][i] for t in fn) / len(fn) for i in range(3)]
        if nx * (fc[0] - cx) + ny * (fc[1] - cy) + nz * (fc[2] - cz) < 0:
            inward += 1

    status = "OK" if inward == 0 else "FAIL"
    print(f"[{status}] {path}: {inward} inward / {total} boundary faces")
    return inward == 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    ok = all([check(p) for p in sys.argv[1:]])
    sys.exit(0 if ok else 1)
