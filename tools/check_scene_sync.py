#!/usr/bin/env python3
"""Check that src/index.html and src/playground.js still run the same scene.

The two files are the same Babylon scene twice: one wrapped in a page, one
shaped for playground.babylonjs.com. They must not drift, because a fix applied
to one and not the other produces a bug that only appears in the copy nobody
was looking at -- which has already happened once, when the playground was left
on decal projection for a whole commit.

They used to be compared byte for byte. That stopped being possible when the
playground was slimmed down for pasting: it carries short trailing notes where
index.html carries full explanations, and the reasoning moved to docs/.

So the comparison is on CODE only. Comments and blank lines are stripped from
both, then the remainder is diffed. That still catches every real divergence --
a changed uScale, a dropped material property, a renamed node -- while letting
the prose differ, which is the whole point of having slimmed one of them.

Run:  python3 tools/check_scene_sync.py
Exit code 1 if they have drifted.
"""

import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "src" / "index.html"
PLAYGROUND = ROOT / "src" / "playground.js"

# Differences that are meant to exist. Everything else is drift.
#
# ASSET_ROOT points somewhere different in each file -- one is served locally,
# the other over HTTP from GitHub. The rest is page scaffolding that the
# Playground provides for itself: it owns the render loop, the resize handler
# and the inspector, and it has no loading element to hide.
EXPECTED_DIFFERENT = re.compile(
    r"""^(
        const\ ASSET_ROOT\ =
      | scene\.debugLayer\.
      | loadingEl\.
      | createScene\(\)\.then
      | engine\.(runRenderLoop|resize)
      | window\.addEventListener\("resize"
      | scene\.render\(\);
      | \}\)?;?$
    )""",
    re.X,
)


def scene_code(text):
    """The scene's executable lines, stripped of comments and indentation."""
    out = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        # trailing // note on a code line
        line = re.sub(r"\s*//(?![^\s]*['\"]).*$", "", line).strip()
        if line:
            out.append(line)
    return out


def main():
    index_src = INDEX.read_text()
    scripts = re.findall(r"<script>(.*?)</script>", index_src, re.S)
    if not scripts:
        print(f"no inline <script> found in {INDEX}")
        return 1

    a = scene_code(scripts[-1])
    b = scene_code(PLAYGROUND.read_text())

    # Compare only from the shared part onward. index.html additionally has the
    # engine bootstrap, the WebGL fallback, the loading element and the
    # inspector; the playground gets those from the Playground itself.
    def shared(lines):
        for i, l in enumerate(lines):
            if l.startswith("const camera = new BABYLON.ArcRotateCamera"):
                return lines[i:]
        return lines

    a, b = shared(a), shared(b)
    diff = [
        d
        for d in difflib.unified_diff(a, b, "index.html", "playground.js", lineterm="", n=0)
        if d[:1] in "+-" and not d.startswith(("---", "+++"))
    ]
    real = [d for d in diff if not EXPECTED_DIFFERENT.match(d[1:])]

    print(f"index.html {len(a)} code lines, playground.js {len(b)}")
    if not real:
        print("IN SYNC — no code differences")
        return 0
    print(f"DRIFTED — {len(real)} differing code lines:")
    for d in real:
        print("   ", d[:100])
    return 1


if __name__ == "__main__":
    sys.exit(main())
