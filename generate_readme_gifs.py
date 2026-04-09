#!/usr/bin/env python3
"""Generate looping GIF animations from scene images for README showcase."""
import json, urllib.request, time, os, sys, uuid

sys.path.insert(0, 'plugins/gimp/comfyui-connector')
import _workflows_v2 as wf

COMFY = 'http://127.0.0.1:8188'
OUT = 'assets/readme'
os.makedirs(OUT, exist_ok=True)

WAN_PRESET = {
    "high_model": "Wan\\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf",
    "low_model": "Wan\\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf",
    "clip": "umt5-xxl-encoder-Q8_0.gguf",
    "vae": "wan_2.1_vae.safetensors",
    "steps": 6, "second_step": 3, "cfg": 1, "shift": 8.0,
    "high_accel_lora": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    "low_accel_lora": "WAN\\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    "accel_strength": 1.5,
}

def upload_image(filepath):
    """Upload an image to ComfyUI input folder."""
    name = f'readme_anim_{uuid.uuid4().hex[:8]}.png'
    data = open(filepath, 'rb').read()
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
        f'Content-Type: image/png\r\n\r\n'
    ).encode() + data + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(f'{COMFY}/upload/image', data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
    urllib.request.urlopen(req, timeout=30)
    return name

def generate_and_wait(workflow, timeout=600):
    """Submit workflow, wait for GIF/video result."""
    body = json.dumps({"prompt": workflow}).encode('utf-8')
    req = urllib.request.Request(f'{COMFY}/prompt', data=body,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        pid = json.loads(r.read())['prompt_id']
    print(f'     queued: {pid[:12]}', end='', flush=True)

    for i in range(int(timeout / 2)):
        time.sleep(2)
        if i % 15 == 0 and i > 0:
            print('.', end='', flush=True)
        try:
            with urllib.request.urlopen(f'{COMFY}/history/{pid}', timeout=5) as r:
                data = json.loads(r.read())
                if pid not in data:
                    continue
                entry = data[pid]
                status = entry.get('status', {})
                if status.get('status_str') == 'error':
                    print(f' ERROR')
                    return None
                outputs = entry.get('outputs', {})
                for nid, out in outputs.items():
                    # GIF output from VHS_VideoCombine
                    if 'gifs' in out:
                        fn = out['gifs'][0]['filename']
                        sf = out['gifs'][0].get('subfolder', '')
                        url = f'{COMFY}/view?filename={fn}&type=output'
                        if sf: url += f'&subfolder={sf}'
                        with urllib.request.urlopen(url, timeout=60) as gr:
                            print(f' done')
                            return gr.read()
                    # Image output (last frame)
                    if 'images' in out:
                        pass  # We want the GIF, keep waiting
        except:
            pass

    print(' timeout')
    return None

def animate(source_image, prompt, output_name, width=480, height=320, length=33):
    """Upload image, generate WAN I2V animation, save as GIF."""
    print(f'  {output_name}:')

    # Upload source
    comfy_name = upload_image(source_image)
    print(f'     uploaded: {comfy_name}')

    # Build WAN I2V workflow with pingpong looping
    try:
        w = wf.build_wan_video(
            image_filename=comfy_name,
            preset=WAN_PRESET,
            prompt_text=prompt,
            negative_text="text, watermark, blurry, deformed, static, frozen",
            seed=42,
            width=width, height=height,
            length=length,
            turbo=True,
            loop=False,
            rtx_scale=1.0,       # No upscale
            interpolate=False,    # Skip RIFE for speed
            face_swap=False,      # Skip for speed
            save_raw=False,
            fps=16,
            pingpong=True,        # Seamless loop
        )
    except Exception as e:
        print(f'     build failed: {e}')
        return False

    # Patch the VHS_VideoCombine node to output GIF instead of MP4
    if "83" in w:
        w["83"]["inputs"]["format"] = "image/gif"
        for k in list(w["83"]["inputs"].keys()):
            if k in ("pix_fmt", "crf"):
                del w["83"]["inputs"][k]

    data = generate_and_wait(w)
    if data:
        path = os.path.join(OUT, output_name)
        open(path, 'wb').write(data)
        print(f'     saved: {len(data)//1024}KB')
        return True
    return False


print('=' * 60)
print('GENERATING README GIF ANIMATIONS')
print('=' * 60)

# Animate the scene backgrounds
animations = [
    ('assets/readme/scene_forest.png', 'gentle wind blowing through enchanted trees, fireflies drifting lazily, moonlight shimmering on leaves, atmospheric, dreamy motion',
     'anim_forest.gif', 480, 272),
    ('assets/readme/scene_tavern.png', 'flickering warm fireplace, candle flames dancing, subtle dust motes drifting in light, cozy atmosphere, gentle living scene',
     'anim_tavern.gif', 480, 272),
    ('assets/readme/scene_library.png', 'floating books drifting slowly, magical particles ascending, candle flames flickering gently, dust motes in light beams, mystical atmosphere',
     'anim_library.gif', 480, 272),
    ('assets/readme/portrait_elf.png', 'subtle breathing, gentle hair movement in breeze, living portrait, slight eye movement, natural micro-expressions',
     'anim_portrait.gif', 320, 480),
]

results = {}
for src, prompt, out, w, h in animations:
    if os.path.exists(src):
        ok = animate(src, prompt, out, w, h)
        results[out] = ok
    else:
        print(f'  SKIP: {src} not found')
        results[out] = False

print('\n' + '=' * 60)
print('RESULTS')
print('=' * 60)
passed = sum(1 for v in results.values() if v)
for name, ok in results.items():
    size = os.path.getsize(os.path.join(OUT, name)) // 1024 if ok and os.path.exists(os.path.join(OUT, name)) else 0
    print(f'  [{"PASS" if ok else "FAIL"}] {name} ({size}KB)')
print(f'\n  {passed}/{len(results)} animations generated')
