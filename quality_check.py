"""Live quality test — downloads and analyzes every output."""
import sys, os, json, time, urllib.request, urllib.parse, struct, zlib, tempfile
sys.path.insert(0, 'plugins/gimp/comfyui-connector')
for m in list(sys.modules):
    if 'spellcaster' in m: del sys.modules[m]
from spellcaster_core.workflows import *

# ComfyUI server URL — override via env var SPELLCASTER_COMFYUI_URL.
SERVER = os.environ.get('SPELLCASTER_COMFYUI_URL', 'http://127.0.0.1:8188')

def upload(server, path, name):
    with open(path, 'rb') as f: data = f.read()
    boundary = 'sc'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
            f'filename="{name}"\r\nContent-Type: image/png\r\n\r\n').encode() + data + \
           f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"' \
           f'\r\n\r\ntrue\r\n--{boundary}--\r\n'.encode()
    urllib.request.urlopen(urllib.request.Request(
        f'{server}/upload/image', data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}), timeout=30)

def run(server, wf, timeout=300):
    body = json.dumps({'prompt': wf}).encode()
    try:
        resp = json.loads(urllib.request.urlopen(urllib.request.Request(
            f'{server}/prompt', data=body,
            headers={'Content-Type': 'application/json'}), timeout=10).read())
    except Exception as e:
        return None, f"submit: {e}"
    pid = resp.get('prompt_id')
    if not pid: return None, f"no pid"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            h = json.loads(urllib.request.urlopen(
                f'{server}/history/{pid}', timeout=5).read())
            if pid in h:
                st = h[pid].get('status', {}).get('status_str', '')
                if st == 'error':
                    for mt, md in h[pid].get('status', {}).get('messages', []):
                        if mt == 'execution_error':
                            return None, f"[{md.get('node_type','?')}] {md.get('exception_message','')[:100]}"
                    return None, 'error'
                imgs = []
                for out in h[pid].get('outputs', {}).values():
                    for img in out.get('images', []):
                        imgs.append((img['filename'], img.get('subfolder', ''),
                                     img.get('type', 'output')))
                return imgs, None
        except:
            pass
        time.sleep(2)
    return None, 'timeout'

def download(server, fn, sf='', ft='output'):
    params = urllib.parse.urlencode({'filename': fn, 'subfolder': sf, 'type': ft})
    with urllib.request.urlopen(f'{server}/view?{params}', timeout=30) as r:
        return r.read()

def analyze(data):
    if len(data) < 50: return {'error': 'corrupt', 'size': len(data)}
    w = struct.unpack('>I', data[16:20])[0]
    h = struct.unpack('>I', data[20:24])[0]
    return {'w': w, 'h': h, 'kb': len(data) // 1024}

# Find real image on server
print("Finding test image...", flush=True)
info = json.loads(urllib.request.urlopen(
    f'{SERVER}/object_info/LoadImage', timeout=10).read())
all_inputs = info['LoadImage']['input']['required']['image'][0]
real_img = None
for f in all_inputs:
    if not f.startswith(('gimp_', 'sc_', 'guild_', 'spellcaster_')):
        # Download and check size
        try:
            d = download(SERVER, f, '', 'input')
            a = analyze(d)
            if a.get('kb', 0) > 50:  # at least 50KB = real image
                real_img = f
                print(f"  Using: {f} ({a['w']}x{a['h']}, {a['kb']}KB)")
                break
        except:
            pass
if not real_img:
    # Create gradient
    real_img = 'sc_qualtest.png'
    tmp = tempfile.mktemp(suffix='.png')
    w, h = 512, 768
    raw = b''
    for y in range(h):
        raw += b'\x00'
        for x in range(w):
            raw += bytes([int(x/w*200)+50, int(y/h*180)+40, 140])
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw)
    with open(tmp, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        for ct, d in [(b'IHDR', ihdr), (b'IDAT', idat), (b'IEND', b'')]:
            c = ct + d
            f.write(struct.pack('>I', len(d)) + c +
                    struct.pack('>I', zlib.crc32(c) & 0xffffffff))
    upload(SERVER, tmp, real_img)
    os.unlink(tmp)
    print(f"  Created gradient: {real_img}")

IMG = real_img
SDXL = 'SDXL\\Realistic\\juggernautXL_v9Rundiffusionphoto2.safetensors'
SD15 = 'SD-1.5\\juggernaut_reborn.safetensors'
p_sdxl = {'arch': 'sdxl', 'ckpt': SDXL, 'width': 768, 'height': 768,
           'steps': 8, 'cfg': 2.0, 'sampler': 'dpmpp_sde',
           'scheduler': 'karras', 'denoise': 0.65}

print(f"\n{'='*70}")
print("QUALITY ANALYSIS — downloading and inspecting every output")
print(f"{'='*70}\n")

tests = [
    ('txt2img SDXL',
     lambda: build_txt2img(p_sdxl,
         'a beautiful woman sitting in a cafe, natural window light, '
         'photorealistic, detailed face, shallow depth of field',
         'blurry, bad quality, deformed, ugly', 42)),
    ('Klein img2img',
     lambda: build_klein_img2img(IMG, 'Klein 9B',
         'a detailed professional photograph, sharp focus, natural lighting',
         42, steps=4, denoise=0.55)),
    ('Klein Generate Object',
     lambda: build_klein_generate_object(IMG,
         'a red sports car, side view, studio lighting, isolated',
         42, steps=6)),
    ('Generate Anything SDXL',
     lambda: build_generate_anything(
         'a medieval sword with ornate golden handle, centered, '
         'studio product photo', 'blurry, cropped', 42, p_sdxl)),
    ('IC-Light',
     lambda: build_iclight(IMG, SD15,
         'dramatic golden hour light from the left, warm tones, long shadows',
         'flat, overexposed', 42, multiplier=0.22)),
    ('Normal Map',
     lambda: build_normal_map(IMG)),
    ('Upscale 4x',
     lambda: build_upscale(IMG, '4x_foolhardy_Remacri.pth')),
    ('SAM3 segment person',
     lambda: build_sam3_segment(IMG, 'person')),
    ('Klein Detail Face',
     lambda: build_klein_face_detail(IMG,
         'extremely detailed face, sharp iris, natural skin pores',
         42, steps=4, denoise=0.35)),
    ('Klein Repose',
     lambda: build_klein_repose(IMG, 'Klein 9B',
         'standing confidently, arms at sides, facing camera',
         42, steps=8, denoise=0.82)),
]

results = []
for name, builder in tests:
    print(f"{'─'*50}")
    print(f"TEST: {name}", flush=True)
    try:
        wf = builder()
        nodes = sorted({v.get('class_type', '?')
                        for v in wf.values()
                        if isinstance(v, dict) and 'class_type' in v})
        print(f"  Pipeline: {len(wf)} nodes")

        start = time.time()
        imgs, err = run(SERVER, wf, timeout=300)
        elapsed = time.time() - start

        if err:
            print(f"  STATUS: FAIL ({elapsed:.0f}s) {err}")
            results.append((name, 'FAIL', err))
            continue

        print(f"  STATUS: OK ({elapsed:.0f}s) {len(imgs)} output(s)")

        for fn, sf, ft in imgs:
            try:
                data = download(SERVER, fn, sf, ft)
                a = analyze(data)
                w, h, kb = a.get('w', 0), a.get('h', 0), a.get('kb', 0)
                print(f"  OUTPUT: {fn}")
                print(f"    {w}x{h}  {kb} KB")

                warnings = []
                if kb < 5:
                    warnings.append("BLANK/CORRUPT (<5KB)")
                elif kb < 20 and w > 256:
                    warnings.append("LIKELY SOLID COLOR (<20KB for large img)")
                if w == 0 or h == 0:
                    warnings.append("ZERO DIMENSIONS")

                if warnings:
                    for warn in warnings:
                        print(f"    WARNING: {warn}")
                else:
                    print(f"    QUALITY: OK")
            except Exception as e:
                print(f"  DOWNLOAD ERROR: {e}")

        results.append((name, 'OK', f"{elapsed:.0f}s"))
    except Exception as e:
        print(f"  BUILD ERROR: {e}")
        results.append((name, 'BUILD_ERROR', str(e)[:60]))

print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
for name, status, detail in results:
    icon = "OK" if status == 'OK' else "FAIL"
    print(f"  [{icon:4s}] {name:30s} {detail}")
ok = sum(1 for _, s, _ in results if s == 'OK')
print(f"\n{ok}/{len(results)} passed")
