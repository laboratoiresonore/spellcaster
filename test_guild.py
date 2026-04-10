#!/usr/bin/env python3
"""Live test of all Wizard Guild generation methods against ComfyUI."""
import sys, json, urllib.request, time, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'plugins', 'gimp', 'comfyui-connector'))
import _workflows_v2 as wf

COMFY = 'http://192.168.x.x:8188'
IMG = 'spelltest_input.png'

def submit(workflow):
    body = json.dumps({'prompt': workflow}).encode()
    req = urllib.request.Request(COMFY+'/prompt', data=body, headers={'Content-Type':'application/json'})
    try:
        return json.loads(urllib.request.urlopen(req,timeout=10).read()).get('prompt_id')
    except urllib.error.HTTPError as e:
        err = json.loads(e.read().decode())
        for nid, ne in err.get('node_errors',{}).items():
            for er in ne.get('errors',[]):
                print(f'    VAL {ne.get("class_type","?")}: {er.get("details","")[:150]}')
        return None

def wait(pid, timeout=300):
    t0 = time.time()
    while time.time()-t0 < timeout:
        try:
            r = urllib.request.urlopen(COMFY+'/history/'+pid, timeout=5)
            d = json.loads(r.read())
            if pid in d:
                st = d[pid].get('status',{})
                if st.get('completed'):
                    outs = d[pid].get('outputs',{})
                    img = any('images' in v for v in outs.values())
                    vid = any('gifs' in v for v in outs.values())
                    return 'OK', f'{time.time()-t0:.0f}s {"img" if img else "vid" if vid else "?"}'
                for msg in st.get('messages',[]):
                    if msg[0]=='execution_error':
                        return 'ERROR', msg[1].get('exception_message','?')[:200]
        except: pass
        time.sleep(3)
    return 'TIMEOUT', f'>{timeout}s'

results = []
def run(label, build_fn, timeout=300):
    sys.stdout.write(f'  {label}... '); sys.stdout.flush()
    try: workflow = build_fn()
    except Exception as e:
        print(f'BUILD: {e}')
        results.append((label, 'BUILD', str(e)[:120]))
        return
    pid = submit(workflow)
    if not pid:
        results.append((label, 'REJECT', ''))
        print('REJECTED')
        return
    s, d = wait(pid, timeout)
    results.append((label, s, d))
    print(f'{s} {d}')

# ── Presets ──
sd15 = {'ckpt': r'SD-1.5\v1-5-pruned-emaonly.safetensors', 'arch': 'sd15',
        'width': 512, 'height': 512, 'steps': 8, 'cfg': 7.0,
        'sampler': 'euler', 'scheduler': 'normal', 'loader': 'checkpoint',
        'clip_name1': '', 'clip_name2': '', 'vae_name': ''}

sdxl = {'ckpt': r'SDXL\Realistic\juggernautXL_v9Rundiffusionphoto2.safetensors', 'arch': 'sdxl',
        'width': 512, 'height': 512, 'steps': 10, 'cfg': 5.0,
        'sampler': 'euler', 'scheduler': 'normal', 'loader': 'checkpoint',
        'clip_name1': '', 'clip_name2': '', 'vae_name': ''}

ill = {'ckpt': r'Illustrious\ilustreal_v50VAE.safetensors', 'arch': 'illustrious',
       'width': 512, 'height': 512, 'steps': 10, 'cfg': 6.0,
       'sampler': 'euler', 'scheduler': 'normal', 'loader': 'checkpoint',
       'clip_name1': '', 'clip_name2': '', 'vae_name': ''}

wan_p = {
    'high_model': r'Wan\wan2.2_i2v_high_noise_14B_Q4_K_S.gguf',
    'low_model': r'Wan\wan2.2_i2v_low_noise_14B_Q4_K_S.gguf',
    'clip': 'umt5-xxl-encoder-Q8_0.gguf', 'clip_is_gguf': True,
    'vae': 'wan_2.1_vae.safetensors',
    'steps': 6, 'cfg': 1.0, 'shift': 8.0, 'second_step': 3,
    'high_accel_lora': r'WAN\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors',
    'low_accel_lora': r'WAN\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors',
    'accel_strength': 1.5, 'ip_adapter_model': 'ip-adapter-wan2.1-14b.bin',
}

ltx_p = {
    'unet': r'LTX\ltx-2.3-22b-dev-Q4_K_M.gguf',
    'text_encoder': 'gemma_3_12B_it_fp4_mixed.safetensors',
    'embeddings_connector': r'LTX\ltx-2.3-22b-dev_embeddings_connectors.safetensors',
    'vae': 'LTX23_video_vae_bf16.safetensors',
    'steps': 10, 'cfg': 4.0, 'stg': 1.0, 'rescale': 0.7,
    'distilled_lora': r'ltxv\ltx-2.3-22b-distilled-lora-384.safetensors',
    'latent_upscaler': 'ltx-2.3-spatial-upscaler-x2-1.0.safetensors',
    'lora_prefix': 'ltxv',
}

# ══════════════════════════════════════════════════════════
print("=== IMAGINUS: Image Generation ===")
run('txt2img_sd15', lambda: wf.build_txt2img(sd15, 'wizard in a mystical tavern, warm candlelight', 'blurry ugly', 42))
run('txt2img_sdxl', lambda: wf.build_txt2img(sdxl, 'epic mountain landscape, 8k', 'blurry ugly', 42))
run('txt2img_ill', lambda: wf.build_txt2img(ill, '1girl, blue eyes, garden, masterpiece', 'worst quality', 42))
run('txt2img_sdxl_lora', lambda: wf.build_txt2img(sdxl, 'portrait wizard, detailed skin', 'blurry', 42,
    loras=[{'name': r'SDXL\Detail\Wonderful_Details_XL_V1a.safetensors', 'strength_model': 0.5, 'strength_clip': 0.5}]))

print("\n=== TRANSMUTEX: Image Transform ===")
run('img2img', lambda: wf.build_img2img(IMG, sd15, 'oil painting of medieval castle', 'blurry', 42))
run('style_transfer', lambda: wf.build_style_transfer(IMG, IMG, sd15, 'impressionist', 'ugly', 42))
run('iclight', lambda: wf.build_iclight(IMG, r'SD-1.5\v1-5-pruned-emaonly.safetensors', 'dramatic side light', 'ugly', 42))

print("\n=== MASQUERADE: Face & Identity ===")
run('faceswap', lambda: wf.build_faceswap(IMG, IMG))
run('save_face', lambda: wf.build_save_face_model(IMG, 'guild_test_face'))
run('face_restore', lambda: wf.build_face_restore(IMG, 'codeformer-v0.1.0.pth', 'retinaface_resnet50', 1.0, 0.7))

print("\n=== RESTOREX: Upscale & Restore ===")
run('upscale', lambda: wf.build_upscale(IMG, '4x-UltraSharp.pth'))
run('upscale_blend', lambda: wf.build_upscale_blend(IMG, '4x-UltraSharp.pth', 'RealESRGAN_x4plus.pth'))
run('detail_hallucinate', lambda: wf.build_detail_hallucinate(IMG, '4x-UltraSharp.pth', sd15, 'enhance', 'ugly', 42, 0.35, 7.0))
run('photo_restore', lambda: wf.build_photo_restore(IMG, '4x-UltraSharp.pth', 'codeformer-v0.1.0.pth', 'retinaface_resnet50', 1.0, 0.7, 2, 0.5, 0.3))

print("\n=== ERASEX: Editing & Utility ===")
run('rembg', lambda: wf.build_rembg(IMG))
run('layer_blend', lambda: wf.build_layer_blend(IMG, IMG))

print("\n=== VIDEOMANCER: LTX Video ===")
run('ltx_t2v', lambda: wf.build_ltx_video(ltx_p, 'sunset clouds drifting', 42, width=384, height=256, num_frames=9, fps=8))
run('ltx_i2v', lambda: wf.build_ltx_video(ltx_p, 'portrait breathing gently', 42, width=384, height=256, num_frames=9, fps=8, image_filename=IMG, i2v_strength=0.85))
run('ltx_distilled', lambda: wf.build_ltx_video(ltx_p, 'candle flickering', 42, width=384, height=256, num_frames=9, fps=8, distilled=True, steps=8, cfg=1.0, stg=0.0, rescale=0.0))
run('ltx_upscale', lambda: wf.build_ltx_video(ltx_p, 'ocean waves', 42, width=384, height=256, num_frames=9, fps=8, rtx_scale=2.0))
run('ltx_rife', lambda: wf.build_ltx_video(ltx_p, 'water droplet', 42, width=384, height=256, num_frames=9, fps=8, interpolate=True))
run('ltx_pingpong', lambda: wf.build_ltx_video(ltx_p, 'pendulum swing', 42, width=384, height=256, num_frames=9, fps=8, pingpong=True))

print("\n=== VIDEOMANCER: WAN I2V ===")
run('wan_raw', lambda: wf.build_wan_video(IMG, wan_p, 'subtle breathing', 'blurry', 42, width=576, height=320, length=17, turbo=True, rtx_scale=0, interpolate=False, face_swap=False, fps=8), timeout=600)
run('wan_upscale', lambda: wf.build_wan_video(IMG, wan_p, 'soft smile', 'blurry', 42, width=576, height=320, length=17, turbo=True, rtx_scale=2.0, interpolate=False, face_swap=False, fps=8), timeout=600)
run('wan_rife', lambda: wf.build_wan_video(IMG, wan_p, 'slow blink', 'blurry', 42, width=576, height=320, length=17, turbo=True, rtx_scale=0, interpolate=True, face_swap=False, fps=8), timeout=600)
run('wan_faceswap', lambda: wf.build_wan_video(IMG, wan_p, 'turn head', 'blurry', 42, width=576, height=320, length=17, turbo=True, rtx_scale=0, interpolate=False, face_swap=True, fps=8), timeout=600)
run('wan_full', lambda: wf.build_wan_video(IMG, wan_p, 'gentle breathing', 'blurry', 42, width=576, height=320, length=17, turbo=True, rtx_scale=2.0, interpolate=True, face_swap=True, fps=8), timeout=600)

# ══════════════════════════════════════════════════════════
print("\n" + "="*60)
print("WIZARD GUILD TEST RESULTS")
print("="*60)
ok = err = 0
for label, s, d in results:
    if s == 'OK': ok += 1; icon = 'PASS'
    else: err += 1; icon = 'FAIL'
    print(f'  [{icon}] {label}: {s} {d}')
print(f'\n  {ok} passed, {err} failed out of {len(results)}')
