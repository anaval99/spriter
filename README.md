# spritesheet-cleaner

Clean up AI-generated spritesheets (Gemini, ChatGPT, etc.) by removing solid-color backgrounds, fixing frame bleed, and re-aligning characters into a uniform grid.

## What it does

AI image models tend to produce spritesheets with three problems:
1. **No real transparency** — the background is a solid color (white, pink, gray), or a *baked-in checkerboard* (the fake-transparency pattern saved as real pixels), instead of an alpha channel.
2. **Frame bleed** — parts of one character spill into the neighboring cell.
3. **Misalignment** — characters aren't centered consistently in their cells.

This script fixes all three:

- Auto-detects the background from the four corners — a single solid color, or the two colors of a checkerboard pattern.
- Converts background pixels to true alpha with a soft anti-aliased edge. For checkerboards, distance is measured to the color *blend* between the two squares, so the seams disappear too.
- Uses a border flood-fill so pale pixels inside the character (highlights, etc.) aren't eaten.
- Finds each character via connected-components on the alpha mask — so grid misalignment and frame bleed don't matter.
- Re-centers every character in a uniform cell.

## Install

```bash
pip install -r requirements.txt
```

(or `pip install pillow numpy scipy flask` — Flask is only needed for the web UI)

## Web UI

Prefer buttons over the terminal? Run the local web app:

```bash
python app.py
# open http://127.0.0.1:5000
```

Upload a spritesheet, set cols/rows (default 4×4), click **Run cleanup** to see the
transparent result, optionally enter a pixel amount and click **Trim outline** to shave
leftover fringe off each character's edge, then **Download PNG**.

## Usage (CLI)

The only required argument is the input. The output is written next to it as
`<name>.<timestamp>.png`:

```bash
python clean_spritesheet.py my_unclean_image.png
# -> my_unclean_image.20260626-153045.png
```

Pass a second argument to choose the output name explicitly:

```bash
python clean_spritesheet.py input.png output.png
```

Defaults to a 4×4 grid (16 frames). Override with `--cols` / `--rows`:

```bash
python clean_spritesheet.py walk.png walk_clean.png --cols 8 --rows 4
```

### Options

| Flag | Default | What it does |
| --- | --- | --- |
| `--cols` | 4 | Columns in the grid |
| `--rows` | 4 | Rows in the grid |
| `--bg-color` | (auto) | Override bg detection. One color `253,232,237`, or two (checkerboard) separated by `;`: `255,255,255;232,232,231` |
| `--hard-dist` | 18 | Color distance below which a pixel is fully transparent |
| `--soft-dist` | 40 | Distance above which a pixel is fully opaque (ramp between) |
| `--padding` | 8 | Transparent pixels around each character in the output |
| `--min-area` | 2000 | Ignore connected blobs smaller than this (filters JPEG noise) |
| `--trim` | 0 | Erode each character's edge inward by N pixels (removes leftover fringe) |

### Tuning

Most sheets work with defaults. If a character has a color very close to the background (e.g. pale skin on a white bg), the edge may get eaten — raise `--hard-dist` and `--soft-dist` together. If JPEG noise leaks into the foreground as little specks, raise `--min-area`.

If the script reports `WARN: blob count doesn't match grid`, it means two characters are touching, or noise blobs are bigger than `min_area`. It falls back to splitting by the nominal grid in that case, which usually still works but is less clean.

## How it works

1. **Detect bg.** Cluster the four corner patches into up to two colors. Two populated, well-separated clusters → a checkerboard; otherwise the median is the single bg color.
2. **Build alpha.** For each pixel, compute distance to the bg color — or, for a checkerboard, to the line segment between the two colors. Soft ramp from `hard_dist` to `soft_dist` gives anti-aliased edges.
3. **Rescue interior.** Flood-fill bg pixels starting from the image border. Any bg-colored pixel *not* reached from a border is interior — restore to opaque.
4. **Find characters.** `scipy.ndimage.label` on the alpha mask. Each blob bigger than `min_area` is a character.
5. **Sort to grid.** Sort blobs by Y, slice into rows, sort each row by X.
6. **Place.** Compute uniform cell size = max blob bbox + padding. Center each character in its cell.

## License

MIT
