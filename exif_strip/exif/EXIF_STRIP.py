
from flask import Flask, request, send_file, Response, jsonify
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED
from pathlib import Path
import os, datetime

from PIL import Image, ImageSequence, ExifTags

# ---------- Enable HEIC/HEIF/AVIF via pillow-heif when available ----------
try:
    import pillow_heif
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()   # HEIC/HEIF
    except Exception:
        pass
    try:
        from pillow_heif import register_avif_opener  # type: ignore
        register_avif_opener()   # AVIF
    except Exception:
        pass
    print(f"pillow-heif {getattr(pillow_heif, '__version__', '?')} loaded")
except Exception as e:
    print("pillow-heif not available or failed to load:", e)

# ---------- Optional: lossless EXIF removal for JPEG ----------
try:
    import piexif  # type: ignore
except Exception:
    piexif = None

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512MB per request

# ---------- JSON-safe coercion ----------
try:
    from PIL.TiffImagePlugin import IFDRational  # type: ignore
except Exception:
    class IFDRational:
        pass

def to_jsonable(o):
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    if isinstance(o, (bytes, bytearray)):
        try:
            return o.decode("utf-8", "ignore")
        except Exception:
            return f"<{len(o)} bytes>"
    if isinstance(o, IFDRational):
        try:
            return float(o)
        except Exception:
            return str(o)
    if isinstance(o, (list, tuple, set)):
        return [to_jsonable(x) for x in o]
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    try:
        return float(o) if hasattr(o, "__float__") else str(o)
    except Exception:
        return "<unserializable>"

# ---------- helpers ----------
TAGS = {v: k for k, v in ExifTags.TAGS.items()}
GPSTAGS = ExifTags.GPSTAGS
HEIF_EXTS = (".heic", ".heif", ".avif")

def _ratio_to_float(r):
    try:
        return r[0] / r[1]
    except Exception:
        try:
            return float(r)
        except Exception:
            return None

def _dms_to_deg(dms, ref):
    try:
        d = _ratio_to_float(dms[0])
        m = _ratio_to_float(dms[1])
        s = _ratio_to_float(dms[2])
        if d is None or m is None or s is None:
            return None
        val = d + m/60 + s/3600
        if isinstance(ref, bytes):
            ref = ref.decode("ascii", "ignore").upper()
        if ref in ("S", "W"):
            val = -val
        return val
    except Exception:
        return None

def sniff_ext(fmt: str | None, filename: str) -> str:
    if fmt:
        return fmt.upper()
    return Path(filename).suffix.lstrip(".").upper()

def is_image_filename(name: str) -> bool:
    return bool(name) and name.lower().endswith((
        ".jpg",".jpeg",".png",".webp",".tif",".tiff",".gif",
        ".heic",".heif",".bmp",".pbm",".pgm",".ppm",".avif"
    ))

# ---------- parse GPS from raw EXIF blob ----------
def parse_gps_from_exif_bytes(exif_bytes):
    if not exif_bytes:
        return (None, None)
    try:
        import piexif
    except Exception:
        return (None, None)
    try:
        d = piexif.load(exif_bytes)
        gps_ifd = d.get("GPS", {}) or {}
        lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef)
        lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef)
        lat_dms = gps_ifd.get(piexif.GPSIFD.GPSLatitude)
        lon_dms = gps_ifd.get(piexif.GPSIFD.GPSLongitude)
        if not (lat_ref and lon_ref and lat_dms and lon_dms):
            return (None, None)
        def rat_to_float(r):
            try:
                return r[0] / r[1]
            except Exception:
                try:
                    return float(r)
                except Exception:
                    return None
        def dms_to_deg(dms, ref):
            d = rat_to_float(dms[0]); m = rat_to_float(dms[1]); s = rat_to_float(dms[2])
            if None in (d, m, s): return None
            val = d + m/60 + s/3600
            if isinstance(ref, bytes): ref = ref.decode("ascii","ignore").upper()
            if ref in ("S","W"): val = -val
            return val
        lat = dms_to_deg(lat_dms, lat_ref)
        lon = dms_to_deg(lon_dms, lon_ref)
        return (lat, lon)
    except Exception:
        return (None, None)

# ---------- NEW helper to get EXIF bytes from Pillow image ----------
def _get_exif_bytes_from_info(im):
    exif_bytes = im.info.get("exif")
    if isinstance(exif_bytes, (bytes, bytearray)) and exif_bytes:
        return exif_bytes
    meta_list = im.info.get("metadata")
    if isinstance(meta_list, list):
        for block in meta_list:
            try:
                if (block.get("type","").upper() == "EXIF") and isinstance(block.get("data"), (bytes, bytearray)):
                    return block["data"]
            except Exception:
                pass
    return None

# ---------- metadata extraction ----------
def extract_metadata_bytes(data: bytes, filename: str):
    meta = {
        "filename": os.path.basename(filename),
        "format": None,
        "size": None,
        "mode": None,
        "frames": 1,
        "has_alpha": None,
        "exif": {},
        "gps": {},
        "icc_profile": False,
        "icc_bytes": None,
        "xmp": False,
        "xmp_bytes": None,
        "other_info_keys": [],
        "warnings": [],
    }
    try:
        with Image.open(BytesIO(data)) as im:
            meta["format"] = im.format
            meta["size"] = [int(im.width), int(im.height)]
            meta["mode"] = im.mode
            meta["has_alpha"] = "A" in im.getbands()
            meta["frames"] = getattr(im, "n_frames", 1) if hasattr(im, "n_frames") else 1

            # Standard EXIF path
            exif = getattr(im, "getexif", lambda: None)()
            if exif:
                meta["exif"] = {ExifTags.TAGS.get(tid, f"Tag_{tid}"): to_jsonable(v)
                                for tid, v in exif.items()}
                gps_tag_id = TAGS.get("GPSInfo")
                if gps_tag_id and gps_tag_id in exif:
                    gps = exif.get(gps_tag_id)
                    gps_dict = {}
                    try:
                        for k, v in gps.items():
                            name = GPSTAGS.get(k, f"GPS_{k}")
                            gps_dict[name] = to_jsonable(v)
                    except Exception:
                        pass
                    if gps_dict:
                        meta["gps"]["raw"] = gps_dict
                    try:
                        lat = _dms_to_deg(gps.get(2), gps.get(1))
                        lon = _dms_to_deg(gps.get(4), gps.get(3))
                    except Exception:
                        lat = lon = None
                    if lat is not None and lon is not None:
                        meta["gps"]["latlon"] = [lat, lon]

            # --- NEW: Try raw EXIF bytes if GPS missing ---
            try:
                exif_bytes = _get_exif_bytes_from_info(im)
                if exif_bytes:
                    meta.setdefault("exif_raw_bytes", len(exif_bytes))
                    if not meta.get("gps", {}).get("latlon"):
                        lat, lon = parse_gps_from_exif_bytes(exif_bytes)
                        if lat is not None and lon is not None:
                            meta.setdefault("gps", {})["latlon"] = [lat, lon]
            except Exception:
                pass

            # ICC + XMP flags
            if "icc_profile" in im.info:
                icc = im.info.get("icc_profile")
                meta["icc_profile"] = True
                try:
                    meta["icc_bytes"] = len(icc or b"")
                except Exception:
                    meta["icc_bytes"] = None

            for k in ("XML","xml","xmp","XMP","xmpmeta","xmp_data"):
                if k in im.info:
                    meta["xmp"] = True
                    x = im.info[k]
                    try:
                        meta["xmp_bytes"] = len(x if isinstance(x, (bytes, bytearray))
                                                 else (x.encode("utf-8","ignore")))
                    except Exception:
                        meta["xmp_bytes"] = None
                    break

            misc = [k for k in im.info.keys() if k not in
                    ("icc_profile","XML","xml","xmp","XMP","xmpmeta","xmp_data","exif","transparency")]
            meta["other_info_keys"] = sorted(misc)

    except Exception as e:
        meta["warnings"].append(str(e))

    return to_jsonable(meta)

# ---------- stripping logic ----------
def strip_exif_lossless_jpeg_if_possible(data: bytes) -> bytes | None:
    if not piexif:
        return None
    try:
        return piexif.remove(data)
    except Exception:
        return None

def _save_single_frame(im: Image.Image, dst: BytesIO, fmt: str, drop_all_meta: bool):
    clean = Image.new(im.mode, im.size)
    clean.putdata(list(im.getdata()))
    save_kwargs = {}
    if fmt in {"JPEG","JPG","TIFF","PNG","WEBP","HEIF","HEIC","AVIF"}:
        save_kwargs["exif"] = b""
    if "transparency" in im.info and fmt in {"PNG","GIF"} and not drop_all_meta:
        save_kwargs["transparency"] = im.info["transparency"]
    if fmt in {"JPEG","JPG"}:
        save_kwargs["quality"] = 95
        save_kwargs["subsampling"] = "keep"
    clean.save(dst, format=fmt if im.format else None, **save_kwargs)

def _save_multiframe(im: Image.Image, dst: BytesIO, fmt: str, drop_all_meta: bool):
    frames = []
    durations = []
    disposals = []
    try:
        for frame in ImageSequence.Iterator(im):
            f = frame.convert(frame.mode)
            frames.append(f.copy())
            durations.append(frame.info.get("duration", im.info.get("duration", 0)))
            disposals.append(frame.info.get("disposal", im.info.get("disposal", 2)))
    except Exception:
        return _save_single_frame(im, dst, fmt, drop_all_meta)
    save_kwargs = {
        "save_all": True,
        "append_images": frames[1:] if len(frames) > 1 else [],
        "duration": durations if any(durations) else None,
        "loop": im.info.get("loop", 0),
        "disposal": disposals if any(disposals) else None,
    }
    if fmt == "WEBP":
        save_kwargs["exif"] = b""
    save_kwargs = {k: v for k, v in save_kwargs.items() if v is not None}
    if fmt == "GIF":
        conv_frames = []
        for f in frames:
            conv_frames.append(f if f.mode in ("P","L") else f.convert("P", palette=Image.ADAPTIVE))
        first = conv_frames[0]
        first.save(dst, format=fmt, **{**save_kwargs, "append_images": conv_frames[1:]})
        return
    if fmt == "WEBP":
        frames[0].save(dst, format=fmt, **save_kwargs)
        return
    _save_single_frame(frames[0], dst, fmt, drop_all_meta)

def strip_image_bytes(data: bytes, filename: str, drop_all_meta: bool) -> bytes:
    ext = Path(filename).suffix.lower()
    if not drop_all_meta and ext in (".jpg", ".jpeg") and piexif:
        cleaned = strip_exif_lossless_jpeg_if_possible(data)
        if cleaned is not None:
            return cleaned
    with Image.open(BytesIO(data)) as im:
        fmt = sniff_ext(im.format, filename)
        n_frames = getattr(im, "n_frames", 1)
        out = BytesIO()
        if n_frames and n_frames > 1 and fmt in {"GIF","WEBP"}:
            _save_multiframe(im, out, fmt, drop_all_meta)
        else:
            _save_single_frame(im, out, fmt, drop_all_meta)
        return out.getvalue()

INDEX_HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Strip EXIF</title>
  <style>
    :root { --p:#3a86ff; }
    *{box-sizing:border-box}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;margin:2rem;max-width:1100px}
    h1{margin:.2rem 0 1rem}
    #drop{border:2px dashed #ccc;border-radius:12px;padding:3rem;text-align:center}
    #drop.drag{border-color:#999;background:#fafafa}
    .hint{color:#666;margin:.5rem 0 1rem}
    button{padding:.6rem 1rem;border-radius:8px;border:1px solid #ddd;cursor:pointer}
    button.primary{background:var(--p);border-color:var(--p);color:#fff}
    table{width:100%;border-collapse:collapse;margin-top:1rem}
    th,td{padding:.5rem;border-bottom:1px solid #eee;text-align:left}
    td.actions{white-space:nowrap}
    .row{display:flex;gap:.75rem;align-items:center;flex-wrap:wrap}
    .right{margin-left:auto}
    .pill{display:inline-block;padding:.1rem .5rem;border-radius:999px;background:#eee;font-size:.8rem}
    dialog{border:none;border-radius:12px;max-width:900px;width:90%}
    pre{max-height:45vh;overflow:auto;background:#0b1020;color:#d6deff;padding:1rem;border-radius:8px}
    .muted{color:#777}
    label.switch{display:inline-flex;align-items:center;gap:.5rem;user-select:none}
    input[type="checkbox"]{transform:scale(1.1)}
  </style>
</head>
<body>
  <h1>Strip EXIF</h1>
  <p class="hint">Drag & drop photos here, or <input id="file" type="file" multiple accept="image/*">. Preview metadata per file. Then clean and download a ZIP.</p>

  <div id="drop">Drop images here</div>

  <div class="row" style="margin-top:1rem">
    <div class="pill"><span id="count">0</span> file(s) added</div>
    <div class="pill">Selected: <span id="selected">0</span></div>
    <div class="right row">
      <label class="switch">
        <input type="checkbox" id="dropAll">
        <span>Remove <b>all</b> metadata (EXIF + XMP + ICC + misc)</span>
      </label>
      <button id="selectAll">Select all</button>
      <button id="clear">Clear</button>
      <button id="go" class="primary">Clean & Download</button>
    </div>
  </div>

  <table id="tbl" hidden>
    <thead>
      <tr><th></th><th>Name</th><th>Type</th><th>Size</th><th>Frames</th><th>Actions</th></tr>
    </thead>
    <tbody></tbody>
  </table>

  <dialog id="metaDlg">
    <h3 id="metaTitle">Metadata</h3>
    <div id="metaSummary" class="hint"></div>
    <pre id="metaPre">{}</pre>
    <div class="row" style="margin-top:1rem">
      <span class="muted">Tip: “All metadata” removes EXIF plus XMP/ICC/custom chunks. Visuals (like transparency/animation) are preserved.</span>
      <div class="right"><button id="closeMeta">Close</button></div>
    </div>
  </dialog>

<script>
const drop = document.getElementById('drop');
const input = document.getElementById('file');
const tbl = document.getElementById('tbl');
const tbody = tbl.querySelector('tbody');
const countEl = document.getElementById('count');
const selEl = document.getElementById('selected');
const dlg = document.getElementById('metaDlg');
const metaTitle = document.getElementById('metaTitle');
const metaSummary = document.getElementById('metaSummary');
const metaPre = document.getElementById('metaPre');
const dropAll = document.getElementById('dropAll');

let files = []; // [{file, selected:true}]

function bytes(n){ if(n<1024) return n+' B'; if(n<1048576) return (n/1024).toFixed(1)+' KB'; return (n/1048576).toFixed(1)+' MB'; }

function render(){
  countEl.textContent = files.length;
  selEl.textContent = files.filter(x=>x.selected).length;
  tbody.innerHTML = '';
  tbl.hidden = files.length === 0;
  files.forEach((item, idx) => {
    const tr = document.createElement('tr');
    const cb = document.createElement('input'); cb.type='checkbox'; cb.checked=item.selected;
    cb.addEventListener('change', ()=>{ item.selected = cb.checked; selEl.textContent = files.filter(x=>x.selected).length; });
    const td0 = document.createElement('td'); td0.appendChild(cb);
    const td1 = document.createElement('td'); td1.textContent = item.file.name;
    const td2 = document.createElement('td'); td2.textContent = item.file.type || '(unknown)';
    const td3 = document.createElement('td'); td3.textContent = bytes(item.file.size);
    const td4 = document.createElement('td'); td4.textContent = item.file._frames || 1;
    const td5 = document.createElement('td'); td5.className='actions';
    const btnV = document.createElement('button'); btnV.textContent = 'View metadata';
    btnV.addEventListener('click', ()=> inspectFile(item.file));
    td5.appendChild(btnV);
    tr.append(td0, td1, td2, td3, td4, td5);
    tbody.appendChild(tr);
  });
}

function addFiles(list){
  for (const f of list){
    // Accept common image extensions (some browsers omit type for HEIC/AVIF)
    if (!f.type.startsWith('image/') && !/\.(jpe?g|png|webp|tif?f|gif|heic|heif|bmp|pbm|pgm|ppm|avif)$/i.test(f.name)) continue;
    files.push({file:f, selected:true});
  }
  render();
}

input.addEventListener('change', e => addFiles(e.target.files));
['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); }));
drop.addEventListener('drop', e => addFiles(e.dataTransfer.files || []));

document.getElementById('clear').addEventListener('click', ()=>{ files=[]; render(); });
document.getElementById('selectAll').addEventListener('click', ()=>{ files.forEach(f=>f.selected=true); render(); });

document.getElementById('go').addEventListener('click', async ()=>{
  const selected = files.filter(f=>f.selected).map(f=>f.file);
  if (!selected.length) return alert('Select at least one image.');
  const fd = new FormData();
  selected.forEach(f => fd.append('files', f, f.name));
  fd.append('drop_all', dropAll.checked ? '1' : '0');
  const res = await fetch('/strip', { method:'POST', body: fd });
  if (!res.ok) {
    const t = await res.text().catch(()=> 'Error');
    alert('Error processing files: '+t);
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), {
    href: url,
    download: 'cleaned_'+new Date().toISOString().slice(0,19).replace(/[:T]/g,'')+'.zip'
  });
  a.click(); URL.revokeObjectURL(url);
});

document.getElementById('closeMeta').addEventListener('click', ()=> dlg.close());

async function inspectFile(file){
  const fd = new FormData();
  fd.append('file', file, file.name);
  const res = await fetch('/inspect', {method:'POST', body: fd});
  if (!res.ok){ alert('Failed to inspect '+file.name); return; }
  const info = await res.json();
  metaTitle.textContent = 'Metadata: '+file.name;
  const parts = [];
  if (info.format) parts.push('Format: '+info.format);
  if (info.size) parts.push('Size: '+info.size[0]+'×'+info.size[1]);
  parts.push('Alpha: '+(info.has_alpha ? 'yes':'no'));
  parts.push('Frames: '+(info.frames || 1));
  if (info.gps && info.gps.latlon) parts.push('GPS: '+info.gps.latlon.join(', '));
  if (info.xmp) parts.push('XMP: present ('+(info.xmp_bytes||'?')+' bytes)');
  if (info.icc_profile) parts.push('ICC: present ('+(info.icc_bytes||'?')+' bytes)');
  metaSummary.textContent = parts.join('  •  ');
  metaPre.textContent = JSON.stringify(info, null, 2);
  dlg.showModal();
}
</script>
</body>
</html>
"""

# ---------- routes ----------
@app.route("/", methods=["GET"])
def index():
    return Response(INDEX_HTML, mimetype="text/html")

@app.route("/inspect", methods=["POST"])
def inspect():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    name = f.filename or ""
    data = f.read()
    meta = extract_metadata_bytes(data, name)
    if meta.get("format") is None and name.lower().endswith(HEIF_EXTS):
        meta.setdefault("warnings", []).append(
            "HEIC/HEIF/AVIF may require pillow-heif and system libheif. Try: pip install pillow-heif"
        )
    return jsonify(meta)

@app.route("/strip", methods=["POST"])
def strip():
    if "files" not in request.files:
        return "No files", 400
    drop_all_meta = request.form.get("drop_all", "0") == "1"
    buf = BytesIO()
    with ZipFile(buf, "w", compression=ZIP_STORED) as z:
        for f in request.files.getlist("files"):
            name = os.path.basename(f.filename or "file")
            try:
                if not is_image_filename(name):
                    raise ValueError("Unsupported/unknown image type")
                raw = f.read()
                cleaned = strip_image_bytes(raw, name, drop_all_meta)
                z.writestr(name, cleaned)
            except Exception as e:
                z.writestr(name + ".ERROR.txt", f"{type(e).__name__}: {e}")
    buf.seek(0)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(buf, as_attachment=True,
                     download_name=f"cleaned_{stamp}.zip",
                     mimetype="application/zip")

if __name__ == "__main__":
    Image.MAX_IMAGE_PIXELS = None
    app.run(debug=True)
