"""
Clean up an AI-generated spritesheet.

Steps:
  1. Auto-detect background color from the four corners.
  2. Convert background-colored pixels to true alpha transparency
     (with a soft ramp for anti-aliased edges, and a border flood-fill
     so interior near-bg pixels are not eaten).
  3. Find each character via connected-components on the alpha mask.
  4. Re-place each character, centered, in a uniform grid
     (default 4 cols x 4 rows).

Handles white, pink, gray, or any other solid color background that
appears in the four corners. JPEG noise is tolerated via a color
distance threshold and a `min_area` filter on connected components.

Usage:
    python clean_spritesheet.py input.png [output.png] [--cols 4 --rows 4]

If output is omitted, it is written next to the input as
"<name>.<timestamp>.<ext>" (e.g. idle.png -> idle.20260626-153045.png).
"""
import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def detect_bg_colors(rgb: np.ndarray, border: int = 6) -> np.ndarray:
    """Detect 1 or 2 background colors from a thin ring along the image edge.

    AI image tools often bake the "transparency" checkerboard into the
    image as two alternating near-white/gray colors instead of real alpha.
    The outermost ring of pixels is almost always pure background (centered
    characters don't reach the edge), so we sample it and cluster into two
    groups. If both groups are substantial and only moderately separated
    (consistent with two checker tiles, not a saturated character color),
    we return both; otherwise we return the single dominant color.

    Returns an array of shape (k, 3), k in {1, 2}.
    """
    from scipy.cluster.vq import kmeans2

    H, W = rgb.shape[:2]
    b = max(1, min(border, H // 2, W // 2))
    ring = np.concatenate([
        rgb[:b, :].reshape(-1, 3),
        rgb[-b:, :].reshape(-1, 3),
        rgb[b:-b, :b].reshape(-1, 3),
        rgb[b:-b, -b:].reshape(-1, 3),
    ], axis=0).astype(np.float32)

    # Perfectly uniform ring (no noise) -> single color; skip clustering so
    # kmeans doesn't warn about an empty second cluster.
    if ring.std(axis=0).max() < 2.0:
        return ring.mean(axis=0).astype(np.float32)[None, :]

    centers, labels = kmeans2(ring, 2, minit="++", seed=0)
    counts = np.bincount(labels, minlength=2)
    dominant = int(np.argmax(counts))
    spread = float(np.sqrt(((centers[0] - centers[1]) ** 2).sum()))

    # A checkerboard: both tiles well-represented and within a plausible
    # gray/white separation. A large spread means the minority cluster is a
    # character color that touched the edge, not a second background tile.
    is_checker = counts.min() >= 0.20 * counts.sum() and 12.0 <= spread <= 140.0
    if is_checker:
        return centers.astype(np.float32)
    return centers[dominant].astype(np.float32)[None, :]


def _dist_to_bg(rgb: np.ndarray, bg_colors: np.ndarray) -> np.ndarray:
    """Per-pixel RGB distance to the background.

    For a single bg color this is plain Euclidean distance. For two colors
    (a checkerboard) it's the distance to the *line segment* between them,
    so the two checker colors and every anti-aliased blend in between read
    as background.
    """
    p = rgb.astype(np.float32)
    if len(bg_colors) == 1:
        diff = p - bg_colors[0]
        return np.sqrt((diff ** 2).sum(axis=2))

    a, b = bg_colors[0], bg_colors[1]
    ab = b - a
    ab2 = float(ab @ ab)
    if ab2 < 1e-6:
        diff = p - a
        return np.sqrt((diff ** 2).sum(axis=2))
    t = ((p - a) @ ab) / ab2
    t = np.clip(t, 0.0, 1.0)
    proj = a + t[..., None] * ab
    diff = p - proj
    return np.sqrt((diff ** 2).sum(axis=2))


def build_alpha(rgb: np.ndarray, bg_colors: np.ndarray,
                hard_dist: float = 18.0, soft_dist: float = 40.0) -> np.ndarray:
    """
    Soft alpha by RGB distance from the background:
      distance <= hard_dist            -> alpha 0
      hard_dist < distance < soft_dist -> linear ramp
      distance >= soft_dist            -> alpha 255

    `bg_colors` is a (k, 3) array (k in {1, 2}); distance is measured to the
    nearest background color / blend (see `_dist_to_bg`).

    Then rescue interior near-bg pixels by flood-filling background only
    from the image border. Anything classified as bg but not reachable
    from a border is restored to opaque (e.g. a pale highlight inside a
    helmet).
    """
    dist = _dist_to_bg(rgb, bg_colors)

    span = max(soft_dist - hard_dist, 1e-6)
    alpha = np.clip((dist - hard_dist) * (255.0 / span),
                    0, 255).astype(np.uint8)

    bg_mask = alpha == 0
    border_seed = np.zeros_like(bg_mask)
    border_seed[0, :] = bg_mask[0, :]
    border_seed[-1, :] = bg_mask[-1, :]
    border_seed[:, 0] = bg_mask[:, 0]
    border_seed[:, -1] = bg_mask[:, -1]
    outside_bg = ndimage.binary_propagation(border_seed, mask=bg_mask)

    rescued = bg_mask & ~outside_bg
    alpha[rescued] = 255
    alpha[outside_bg] = 0
    return alpha


def extract_characters(alpha: np.ndarray, min_area: int = 2000):
    """Connected components of foreground -> list of bboxes.

    Uses a single labeling pass plus `find_objects`/`bincount` so cost is
    independent of the number of blobs (no per-label rescan of the image).
    """
    binary = alpha > 32
    labels, n = ndimage.label(binary)
    counts = np.bincount(labels.ravel())
    boxes = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None or counts[i] < min_area:
            continue
        ys, xs = sl
        boxes.append((ys.start, ys.stop, xs.start, xs.stop))
    return boxes


def sort_boxes_to_grid(boxes, rows, cols):
    """Row-major order, tolerant of vertical jitter between same-row frames."""
    if len(boxes) != rows * cols:
        return None
    by_y = sorted(boxes, key=lambda b: (b[0] + b[1]) / 2)
    chunks = [by_y[i * cols:(i + 1) * cols] for i in range(rows)]
    ordered = []
    for chunk in chunks:
        ordered.extend(sorted(chunk, key=lambda b: (b[2] + b[3]) / 2))
    return ordered


def clean_image(rgb: np.ndarray, cols: int = 4, rows: int = 4,
                bg_color: np.ndarray = None, hard_dist: float = 18.0,
                soft_dist: float = 40.0, padding: int = 8,
                min_area: int = 2000):
    """Run the full cleanup pipeline on an RGB array.

    Returns (out_rgba, info) where out_rgba is the composed RGBA spritesheet
    and info is a dict describing what happened (for logging or the UI).
    Shared by the CLI (`main`) and the web server (`app.py`).
    """
    bg = bg_color if bg_color is not None else detect_bg_colors(rgb)

    alpha = build_alpha(rgb, bg, hard_dist, soft_dist)
    coverage = float((alpha > 0).mean() * 100)

    boxes = extract_characters(alpha, min_area)
    found = len(boxes)
    expected = rows * cols
    fell_back = found != expected

    if fell_back:
        h, w = rgb.shape[:2]
        cell_h, cell_w = h // rows, w // cols
        boxes = []
        for r in range(rows):
            for c in range(cols):
                y0, x0 = r * cell_h, c * cell_w
                y1, x1 = y0 + cell_h, x0 + cell_w
                sub = alpha[y0:y1, x0:x1] > 32
                if sub.any():
                    ys, xs = np.where(sub)
                    boxes.append((y0 + ys.min(), y0 + ys.max() + 1,
                                  x0 + xs.min(), x0 + xs.max() + 1))
                else:
                    boxes.append((y0, y1, x0, x1))
    else:
        boxes = sort_boxes_to_grid(boxes, rows, cols)

    rgba = np.dstack([rgb, alpha])
    max_h = max(b[1] - b[0] for b in boxes)
    max_w = max(b[3] - b[2] for b in boxes)
    cell_h = max_h + 2 * padding
    cell_w = max_w + 2 * padding

    out = np.zeros((cell_h * rows, cell_w * cols, 4), dtype=np.uint8)
    for idx, (y0, y1, x0, x1) in enumerate(boxes):
        r, c = idx // cols, idx % cols
        char = rgba[y0:y1, x0:x1]
        ch, cw = char.shape[:2]
        py = r * cell_h + (cell_h - ch) // 2
        px = c * cell_w + (cell_w - cw) // 2
        out[py:py + ch, px:px + cw] = char

    info = {
        "bg_colors": bg,
        "coverage": coverage,
        "found": found,
        "expected": expected,
        "fell_back": fell_back,
        "cell_size": (cell_w, cell_h),
    }
    return out, info


def trim_outline(rgba: np.ndarray, n: int) -> np.ndarray:
    """Erode each character's silhouette inward by `n` pixels.

    Removes the leftover fringe/halo of stray pixels that can ring a
    character after cleanup. Operates on the whole sheet at once: because
    frames are separated by transparent gaps, this shrinks every
    character's outline uniformly. Soft (anti-aliased) edges are preserved
    because we grey-erode the alpha channel rather than a hard binary mask.
    """
    out = rgba.copy()
    if n <= 0:
        return out
    alpha = out[:, :, 3]
    eroded = ndimage.grey_erosion(alpha, size=(2 * n + 1, 2 * n + 1))
    out[:, :, 3] = eroded
    out[eroded == 0, :3] = 0
    return out


def draw_border(rgba: np.ndarray, n: int, color=(0, 0, 0)) -> np.ndarray:
    """Draw a solid outline of width `n` px around each character.

    The outline is drawn *outside* the silhouette with rounded corners: the
    ring is the disk-dilation of the silhouette minus the silhouette itself,
    painted opaque `color` (black by default). Because it grows the footprint
    outward, the width is bounded by the transparent padding around each frame.
    """
    out = rgba.copy()
    if n <= 0:
        return out
    mask = out[:, :, 3] > 32
    yy, xx = np.ogrid[-n:n + 1, -n:n + 1]
    disk = (xx ** 2 + yy ** 2) <= n ** 2          # rounded structuring element
    dilated = ndimage.binary_dilation(mask, structure=disk)
    ring = dilated & ~mask
    out[ring, :3] = color
    out[ring, 3] = 255
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output", nargs="?", default=None,
                    help="output path (default: <input>.<timestamp>.png next to input)")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--bg-color", type=str, default=None,
                    help="override auto-detection. One color '253,232,237', or "
                         "two (for a checkerboard) separated by ';': "
                         "'255,255,255;232,232,231'")
    ap.add_argument("--hard-dist", type=float, default=18.0,
                    help="color distance below which pixels are fully transparent")
    ap.add_argument("--soft-dist", type=float, default=40.0,
                    help="color distance above which pixels are fully opaque")
    ap.add_argument("--padding", type=int, default=8)
    ap.add_argument("--min-area", type=int, default=2000,
                    help="ignore connected blobs smaller than this many pixels")
    ap.add_argument("--trim", type=int, default=0,
                    help="erode each character's edge inward by this many pixels "
                         "(removes leftover fringe); 0 = off")
    ap.add_argument("--border", type=int, default=0,
                    help="draw a solid black outline this many pixels wide around "
                         "each character; 0 = off")
    args = ap.parse_args()

    if args.output:
        output = args.output
        if Path(output).suffix.lower() not in (".png", ""):
            # The output carries transparency, which only PNG can store here.
            output = str(Path(output).with_suffix(".png"))
            print(f"note: forcing PNG output -> {output}")
    else:
        p = Path(args.input)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        # Always PNG: output has an alpha channel, which JPEG can't store.
        output = str(p.with_name(f"{p.stem}.{ts}.png"))

    src = Image.open(args.input).convert("RGB")
    rgb = np.array(src)
    print(f"loaded {args.input}: {src.size[0]}x{src.size[1]}")

    if args.bg_color:
        bg = np.array([[int(x) for x in part.split(",")]
                       for part in args.bg_color.split(";")], dtype=np.float32)
    else:
        bg = None

    out, info = clean_image(rgb, args.cols, args.rows, bg, args.hard_dist,
                            args.soft_dist, args.padding, args.min_area)

    print("background color(s): " +
          ", ".join(f"RGB({int(c[0])}, {int(c[1])}, {int(c[2])})"
                    for c in info["bg_colors"]))
    print(f"foreground coverage: {info['coverage']:.1f}%")
    print(f"found {info['found']} connected components (expected {info['expected']})")
    if info["fell_back"]:
        print("WARN: blob count doesn't match grid. Falling back to nominal grid split.")
    print(f"output cell size: {info['cell_size'][0]}x{info['cell_size'][1]}")

    if args.trim > 0:
        out = trim_outline(out, args.trim)
        print(f"trimmed outline by {args.trim}px")

    if args.border > 0:
        out = draw_border(out, args.border)
        print(f"drew black border {args.border}px wide")

    Image.fromarray(out, "RGBA").save(output)
    print(f"wrote {output}: {out.shape[1]}x{out.shape[0]}")


if __name__ == "__main__":
    main()
