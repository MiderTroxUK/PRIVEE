"""Layout classification by skeletonisation: I, L or U, and nothing else.

Ported from C:\\PRIVEE\\VOLUME\\geometry.py, which classified from the medial axis of the
roof mask rather than from the corners of its outline. Corner counting collapses to
"complex" as soon as a roof has canopies, returns or a fragmented footprint; the skeleton
ignores all of that because it describes how the building extends, not how its edge wiggles.

Two changes against the original:
  * the thresholds are metres here, converted to pixels with the chip's own GSD, so the
    same numbers hold whatever resolution the imagery is fetched at;
  * "Unknown" is never returned. A shape that cannot be resolved is reported as I, the
    most common layout by a wide margin, instead of inventing a fourth class.
"""
from __future__ import annotations

from collections import deque

import cv2
import numpy as np
from shapely.geometry import LineString
from skimage.morphology import skeletonize

TOL_M = 10.0  # RDP tolerance, was 25 px at roughly 0.43 m/px
MIN_SEG_M = 17.0  # a terminal stub shorter than this is not a wing, was 40 px
MIN_RATIO = 0.18  # ... and only pruned if it is also a small share of the whole
ANGLE_DEG = 20.0  # below this a joint is drift, not a bend


def _longest_path(skel):
    """Longest path through the skeleton, by double BFS on its largest component."""
    coords = np.argwhere(skel)
    if len(coords) < 2:
        return []
    pts = {tuple(p) for p in coords}
    adj = {}
    for p in pts:
        r, c = p
        adj[p] = [(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                  if (dr or dc) and (r + dr, c + dc) in pts]

    def bfs(start):
        q, seen, parent, far = deque([start]), {start}, {start: None}, start
        while q:
            cur = q.popleft()
            far = cur
            for n in adj[cur]:
                if n not in seen:
                    seen.add(n)
                    parent[n] = cur
                    q.append(n)
        return far, parent, seen

    seen_all, comps = set(), []
    for node in pts:
        if node not in seen_all:
            _, _, comp = bfs(node)
            seen_all |= comp
            comps.append(comp)
    if not comps:
        return []
    big = max(comps, key=len)
    ends = [p for p in big if len(adj[p]) == 1]
    u, _, _ = bfs(ends[0] if ends else next(iter(big)))
    v, parent, _ = bfs(u)
    path, cur = [], v
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    return path[::-1]


def _prune(coords, min_seg_px):
    """Drop terminal stubs: a short first or last segment is a canopy, not a wing."""
    while len(coords) >= 3:
        seg = [np.linalg.norm(np.array(coords[i + 1]) - np.array(coords[i]))
               for i in range(len(coords) - 1)]
        total = sum(seg)
        if not total:
            break
        if seg[0] < min_seg_px and seg[0] < MIN_RATIO * total:
            coords = coords[1:]
            continue
        if seg[-1] < min_seg_px and seg[-1] < MIN_RATIO * total:
            coords = coords[:-1]
            continue
        break
    return coords


def _angle(v1, v2):
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if not n1 or not n2:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))))


def classify_coords(coords):
    """I, L or U from the simplified centre line. Never anything else."""
    n = len(coords) - 1
    if n <= 0:
        return "I"
    if n == 1:
        return "I"
    seg = [np.array(coords[i + 1]) - np.array(coords[i]) for i in range(n)]
    bends = []
    for i in range(n - 1):
        a = _angle(seg[i], seg[i + 1])
        if a >= ANGLE_DEG:
            cross = seg[i][0] * seg[i + 1][1] - seg[i][1] * seg[i + 1][0]
            bends.append(np.sign(cross))
    if not bends:
        return "I"
    if len(bends) == 1:
        return "L"
    turns = [b for b in bends if b != 0]
    # Two or more bends the same way fold the building back on itself: that is a U. Bends that alternate are a dog-leg, which reads as an L.
    if len(turns) >= 2 and all(t == turns[0] for t in turns):
        return "U"
    return "L"


def analyse_mask(mask, gsd):
    """Roof mask -> (class, skeleton points in mask pixel coordinates).

    The mask is opened then closed before skeletonising, otherwise every notch in the
    segmentation grows its own branch and the centre line becomes a bush.
    """
    m = (np.asarray(mask) > 0)
    pts = np.argwhere(m)
    if len(pts) == 0:
        return "I", []
    (y0, x0), (y1, x1) = pts.min(axis=0), pts.max(axis=0)
    k = max(9, min(25, int(min(y1 - y0, x1 - x0) / 6)))
    k += 1 - k % 2
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    sm = cv2.morphologyEx(m.astype(np.uint8) * 255, cv2.MORPH_OPEN, kern)
    sm = cv2.morphologyEx(sm, cv2.MORPH_CLOSE, kern)

    path = _longest_path(skeletonize(sm > 0))
    if not path:
        return "I", []
    line = LineString([(float(p[1]), float(p[0])) for p in path])
    simp = list(line.simplify(TOL_M / gsd, preserve_topology=True).coords)
    simp = _prune(simp, MIN_SEG_M / gsd)
    return classify_coords(simp), simp
