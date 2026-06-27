# prompts

A collection of ready-to-paste prompts for generating character animation
spritesheets with image models like **ChatGPT (GPT-4o / image)**, **Gemini**, or
similar. Each `.md` file is one animation (idle, walk, attack, …).

Pair these with [`clean_spritesheet.py`](../clean_spritesheet.py) in the repo root
to strip the background and re-grid the frames into a clean, ready-to-use sheet.

## How to use

1. Open ChatGPT / Gemini and **upload your base character image first**. Every
   prompt assumes the model already has your character in context.
2. Copy the contents of the prompt file you want (e.g. `idle.md`) and send it.
3. Download the generated spritesheet.
4. Clean it up with the cleaner — 4×4 is the default grid, so just pass the file:
   ```bash
   python clean_spritesheet.py generated.png
   # -> generated.<timestamp>.png
   ```

## System requirements / conventions

Every prompt in this folder follows the same rules. Use these as the spec when
writing new prompts so the whole collection stays consistent and works with the
cleaner.

- **Base character is pre-uploaded.** Prompts never describe the character; they
  reference "this character" and assume the uploaded image is the source of truth
  for appearance, proportions, palette, and style.
- **Always a 4×4 spritesheet — 16 frames total.** 4 columns × 4 rows, read in
  row-major order (left→right, top→bottom) as the animation sequence.
- **Transparent background, always.** The prompt must explicitly ask for a true
  transparent (alpha) background, not a solid color.
- **Ready to use.** Ask for consistent framing/scale across all 16 frames and the
  character centered in each cell, with no text, labels, or watermarks.
- **No grid lines, no shadows.** Explicitly forbid grid lines, borders, or dividers
  between cells, and any shadows (drop shadows and ground/cast shadows). They confuse
  the cleaner's frame detection and bleed into neighboring cells.
- **Animation over translation.** Prompts should describe *believable motion*
  (e.g. breathing, weight shift, secondary motion on hair/cloth) rather than
  naively sliding the same static image around.
- **Loopable.** Unless stated otherwise, frame 16 should lead cleanly back into
  frame 1 so the animation loops seamlessly.

## Writing a new prompt

Create a new `<name>.md` (one animation per file) and keep it short — a single
imperative paragraph the user can paste directly. It must restate the
non-negotiables every time: **4×4 / 16 frames**, **transparent background**,
**no grid lines or shadows**, **ready to use**, and **real animation (not a static
image moved around)**.

## Available prompts

| File | Animation |
| --- | --- |
| [`idle.md`](idle.md) | Idle / breathing loop |
