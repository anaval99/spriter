"""
Clean up an AI-generated spritesheet.

Steps:
  1. Auto-detect background color from the four corners.
  2. Convert background-colored pixels to true alpha transparency
     (with a soft ramp for anti-aliased edges, and a border flood-fill
     so interior near-bg pixels are not eaten).
  3. Find each character via connected-components on the alpha mask.
  4. Re-place each character, centered, in a uniform grid
     (default 6 cols x 2 rows).

Handles white, pink, gray, or any other solid color background that
appears in the four corners. JPEG noise is tolerated via a color
distance threshold and a `min_area` filter on connected components.

Usage:
    python clean_spritesheet.py input.png output.png [--cols 6 --rows 2]
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage


def detect_bg_color(rgb: np.ndarray, sample: int = 16) -> np.ndarray:
    """Median color across the four corner patches. Robust to JPEG noise."""
    H, W = rgb.shape[:2]
    s = sample
    patches = [
        rgb[:s, :s],
        rgb[:s, W - s:],
        rgb[H - s:, :s],
        rgb[H - s:, W - s:],
    ]
    all_px = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)
    return np.median(all_px, axis=0).astype(np.float32)


def build_alpha(rgb: np.ndarray, bg_color: np.ndarray,
                hard_dist: float = 18.0, soft_dist: float = 40.0) -> np.ndarray:
    """
    Soft alpha by RGB distance from the background color:
      distance <= hard_dist            -> alpha 0
      hard_dist < distance < soft_dist -> linear ramp
      distance >= soft_dist            -> alpha 255

    Then rescue interior near-bg pixels by flood-filling background only
    from the image border. Anything classified as bg but not reachable
    from a border is restored to opaque (e.g. a pale highlight inside a
    helmet).
    """
    diff = rgb.astype(np.float32) - bg_color.astype(np.float32)
    dist = np.sqrt((diff ** 2).sum(axis=2))

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--rows", type=int, default=2)
    ap.add_argument("--bg-color", type=str, default=None,
                    help="override auto-detection, e.g. '253,232,237'")
    ap.add_argument("--hard-dist", type=float, default=18.0,
                    help="color distance below which pixels are fully transparent")
    ap.add_argument("--soft-dist", type=float, default=40.0,
                    help="color distance above which pixels are fully opaque")
    ap.add_argument("--padding", type=int, default=8)
    ap.add_argument("--min-area", type=int, default=2000,
                    help="ignore connected blobs smaller than this many pixels")
    args = ap.parse_args()

    src = Image.open(args.input).convert("RGB")
    rgb = np.array(src)
    print(f"loaded {args.input}: {src.size[0]}x{src.size[1]}")

    if args.bg_color:
        bg = np.array([int(x) for x in args.bg_color.split(",")], dtype=np.float32)
    else:
        bg = detect_bg_color(rgb)
    print(f"background color: RGB({int(bg[0])}, {int(bg[1])}, {int(bg[2])})")

    alpha = build_alpha(rgb, bg, args.hard_dist, args.soft_dist)
    print(f"foreground coverage: {(alpha > 0).mean() * 100:.1f}%")

    boxes = extract_characters(alpha, args.min_area)
    print(f"found {len(boxes)} connected components (expected {args.rows * args.cols})")

    if len(boxes) != args.rows * args.cols:
        print("WARN: blob count doesn't match grid. Falling back to nominal grid split.")
        h, w = rgb.shape[:2]
        cell_h, cell_w = h // args.rows, w // args.cols
        boxes = []
        for r in range(args.rows):
            for c in range(args.cols):
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
        boxes = sort_boxes_to_grid(boxes, args.rows, args.cols)

    rgba = np.dstack([rgb, alpha])
    max_h = max(b[1] - b[0] for b in boxes)
    max_w = max(b[3] - b[2] for b in boxes)
    cell_h = max_h + 2 * args.padding
    cell_w = max_w + 2 * args.padding
    print(f"output cell size: {cell_w}x{cell_h}")

    out = np.zeros((cell_h * args.rows, cell_w * args.cols, 4), dtype=np.uint8)
    for idx, (y0, y1, x0, x1) in enumerate(boxes):
        r, c = idx // args.cols, idx % args.cols
        char = rgba[y0:y1, x0:x1]
        ch, cw = char.shape[:2]
        py = r * cell_h + (cell_h - ch) // 2
        px = c * cell_w + (cell_w - cw) // 2
        out[py:py + ch, px:px + cw] = char

    Image.fromarray(out, "RGBA").save(args.output)
    print(f"wrote {args.output}: {out.shape[1]}x{out.shape[0]}")


if __name__ == "__main__":
    main()
