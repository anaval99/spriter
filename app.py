"""
Simple local web UI for the spritesheet cleaner.

Run:
    pip install -r requirements.txt
    python app.py
    open http://127.0.0.1:5000

Flow: upload a spritesheet -> Run cleanup -> (optionally) Trim outline -> Download.

The server is stateless: the browser keeps the cleaned image and posts it back
to /trim, so the trim amount is always re-derived from the clean base (adjusting
it is non-cumulative). All the heavy lifting reuses clean_spritesheet.py.
"""
import io

import numpy as np
from flask import Flask, request, send_file, render_template_string
from PIL import Image

from clean_spritesheet import clean_image, trim_outline, draw_border

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB


def _png_response(rgba: np.ndarray):
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>spriter</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 820px; margin: 2rem auto;
         padding: 0 1rem; line-height: 1.5; }
  h1 { margin-bottom: .2rem; }
  .sub { color: #888; margin-top: 0; }
  fieldset { border: 1px solid #8884; border-radius: 8px; margin: 1rem 0; padding: 1rem; }
  legend { font-weight: 600; padding: 0 .4rem; }
  label { display: inline-flex; align-items: center; gap: .4rem; margin-right: 1rem; }
  input[type=number] { width: 5rem; }
  button { padding: .5rem 1rem; border-radius: 6px; border: 1px solid #8886;
           background: #4f7cff; color: #fff; cursor: pointer; font-size: 1rem; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  button.secondary { background: #6b7280; }
  #status { min-height: 1.4em; color: #888; margin-top: .6rem; }
  /* checkerboard so transparency is visible in the preview */
  #previewWrap { margin-top: 1rem; border: 1px solid #8884; border-radius: 8px;
                 padding: 1rem; text-align: center;
                 background-color: #fff;
                 background-image:
                   linear-gradient(45deg, #ccc 25%, transparent 25%),
                   linear-gradient(-45deg, #ccc 25%, transparent 25%),
                   linear-gradient(45deg, transparent 75%, #ccc 75%),
                   linear-gradient(-45deg, transparent 75%, #ccc 75%);
                 background-size: 20px 20px;
                 background-position: 0 0, 0 10px, 10px -10px, -10px 0; }
  #preview { max-width: 100%; image-rendering: pixelated; }
  a.download { display: inline-block; margin-top: 1rem; }
</style>
</head>
<body>
  <h1>spriter</h1>
  <p class="sub">Clean AI-generated spritesheets: strip the background, cut frames, re-grid.</p>

  <fieldset>
    <legend>1 &middot; Upload &amp; clean</legend>
    <p><input type="file" id="file" accept="image/*"></p>
    <p>
      <label>Cols <input type="number" id="cols" value="4" min="1"></label>
      <label>Rows <input type="number" id="rows" value="4" min="1"></label>
    </p>
    <button id="cleanBtn" disabled>Run cleanup</button>
  </fieldset>

  <fieldset>
    <legend>2 &middot; Trim &amp; border (optional)</legend>
    <p class="sub" style="margin-top:0">Trim shaves stray pixels off each character's edge;
       border draws a solid black outline around it. Both re-apply from the clean result
       each time (trim first, then border), so you can adjust freely.</p>
    <p>
      <label>Trim by pixel amount <input type="number" id="trim" value="0" min="0"></label>
      <label>Draw border px <input type="number" id="border" value="0" min="0"></label>
    </p>
    <button id="applyBtn" class="secondary" disabled>Apply</button>
  </fieldset>

  <div id="status"></div>

  <div id="previewWrap" hidden>
    <img id="preview" alt="result preview">
    <div><a id="download" class="download" download="spritesheet.png" hidden>Download PNG</a></div>
  </div>

<script>
const $ = (id) => document.getElementById(id);
let baseBlob = null;     // cleaned result, source of truth for trimming
let currentBlob = null;  // what's shown / downloaded

$('file').addEventListener('change', () => {
  $('cleanBtn').disabled = !$('file').files.length;
});

function show(blob) {
  currentBlob = blob;
  const url = URL.createObjectURL(blob);
  $('preview').src = url;
  $('previewWrap').hidden = false;
  const dl = $('download');
  dl.href = url;
  dl.hidden = false;
}

function setStatus(msg) { $('status').textContent = msg; }

$('cleanBtn').addEventListener('click', async () => {
  const f = $('file').files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('image', f);
  fd.append('cols', $('cols').value);
  fd.append('rows', $('rows').value);
  setStatus('Cleaning...');
  $('cleanBtn').disabled = true;
  try {
    const res = await fetch('/clean', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    baseBlob = await res.blob();
    show(baseBlob);
    $('applyBtn').disabled = false;
    setStatus('Cleaned. ' + (res.headers.get('X-Spriter-Info') || ''));
  } catch (e) {
    setStatus('Error: ' + e.message);
  } finally {
    $('cleanBtn').disabled = false;
  }
});

$('applyBtn').addEventListener('click', async () => {
  if (!baseBlob) return;
  const fd = new FormData();
  fd.append('image', baseBlob, 'base.png');
  fd.append('n', $('trim').value);
  fd.append('border', $('border').value);
  setStatus('Applying...');
  $('applyBtn').disabled = true;
  try {
    const res = await fetch('/process', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    show(await res.blob());
    setStatus('Trim ' + $('trim').value + 'px, border ' + $('border').value
              + 'px (from the clean result).');
  } catch (e) {
    setStatus('Error: ' + e.message);
  } finally {
    $('applyBtn').disabled = false;
  }
});
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.post("/clean")
def clean():
    file = request.files.get("image")
    if file is None:
        return "no image uploaded", 400
    cols = max(1, int(request.form.get("cols", 4)))
    rows = max(1, int(request.form.get("rows", 4)))
    rgb = np.array(Image.open(file.stream).convert("RGB"))
    out, info = clean_image(rgb, cols, rows)
    resp = _png_response(out)
    resp.headers["X-Spriter-Info"] = (
        f"found {info['found']}/{info['expected']} frames, "
        f"coverage {info['coverage']:.0f}%"
        + (" (grid fallback)" if info["fell_back"] else "")
    )
    return resp


@app.post("/process")
def process():
    file = request.files.get("image")
    if file is None:
        return "no image uploaded", 400
    n = max(0, int(request.form.get("n", 0)))
    border = max(0, int(request.form.get("border", 0)))
    rgba = np.array(Image.open(file.stream).convert("RGBA"))
    out = trim_outline(rgba, n)
    out = draw_border(out, border)
    return _png_response(out)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
