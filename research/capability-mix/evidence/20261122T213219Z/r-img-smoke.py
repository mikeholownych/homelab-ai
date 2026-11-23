#!/usr/bin/env python3
"""R-img smoke: submit an SDXL-Turbo workflow to a local ComfyUI API and fetch the PNG.

Run on ai-ms-s1-max-01 against 127.0.0.1:8188. Samples GTT before/peak/after.
"""
import json, sys, time, urllib.request, glob

BASE = "http://127.0.0.1:8188"
PROMPT = "red ceramic mug on wood table"
GTT = glob.glob("/sys/class/drm/card*/device/mem_info_gtt_used")[0]

def gtt_gb() -> float:
    return int(open(GTT).read()) / 1e9

def call(path, data=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
wf = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_turbo_1.0_fp16.safetensors"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["1", 1]}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
          "latent_image": ["4", 0], "seed": seed, "steps": 4, "cfg": 1.0,
          "sampler_name": "euler_ancestral", "scheduler": "simple", "denoise": 1.0}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "r-img-mug"}},
}
before = gtt_gb(); peak = before; t0 = time.time()
pid = call("/prompt", {"prompt": wf})["prompt_id"]
while True:
    peak = max(peak, gtt_gb())
    hist = call(f"/history/{pid}")
    if pid in hist and hist[pid].get("status", {}).get("completed") is not None:
        break
    if time.time() - t0 > 600:
        sys.exit("timeout")
    time.sleep(0.25)
wall = time.time() - t0
h = hist[pid]
print(json.dumps({"prompt": PROMPT, "seed": seed, "wall_s": round(wall, 2),
                  "status": h["status"]["status_str"], "outputs": h["outputs"],
                  "gtt_before_gb": round(before, 2), "gtt_peak_gb": round(peak, 2),
                  "gtt_after_gb": round(gtt_gb(), 2)}, indent=2))
