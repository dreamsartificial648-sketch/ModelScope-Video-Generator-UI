# ModelScope Text-to-Video 1.7B (2023)

Original checkpoint: https://huggingface.co/ali-vilab/text-to-video-ms-1.7b

## Start

1. Double-click Setup.bat if you need to install or repair the isolated environment.
2. Double-click Launch UI.bat for the desktop app. Enter a prompt and click Generate video.
3. Watch the looping preview or click Open video. Videos and matching JSON settings are saved in outputs.

The first generation downloads FP16 safetensors weights (several GB) into cache.
Later runs reuse them. No API key or paid service is required. Keep cache to avoid
redownloading. The .venv environment belongs only to this project.

## Customize from PowerShell in this folder

```powershell
.\.venv\Scripts\python.exe generate.py --prompt "An astronaut riding a horse" --seed 42 --steps 25 --frames 16 --fps 8
.\.venv\Scripts\python.exe generate.py --prompt "A cat surfing" --seed -1 --negative-prompt "blurry"
.\.venv\Scripts\python.exe generate.py --check
.\.venv\Scripts\python.exe generate.py --offline --prompt "A robot dancing"
.\.venv\Scripts\python.exe generate.py --help
```

Defaults: 256x256, 16 frames, 8 fps (2 seconds), 25 steps, guidance 9, seed 42.
FP16, model CPU offload, VAE slicing and UNet forward chunking reduce memory use.
Start with defaults on the RTX 3060 12 GB. Longer clips and larger resolutions
increase memory use. Close other GPU-heavy apps if CUDA runs out of memory.
Try --frames 8 for a smaller run. Cancel with Ctrl+C.

Edit generate.py to build on the pipeline. It pins the checkpoint revision and
uses safetensors. Python 3.10 and the CUDA 12.6 PyTorch wheel are installed via
Setup.bat; the system CUDA toolkit is not required. requirements.txt pins the
main Python libraries. installed-versions.txt records the tested environment.

Model documentation: https://huggingface.co/docs/diffusers/v0.35.1/en/api/pipelines/text_to_video

## Compatibility

This legacy pipeline is deprecated by Diffusers. Keep the supplied dependency
versions when extending this project; upgrading libraries can remove old APIs.
A tokenizer FutureWarning during loading does not stop generation.

## Verified on this computer

Successfully generated "Will Smith eating spaghetti", seed 42, 25 steps,
16 frames, 256x256, 8 FPS. Denoising took 152 seconds. The first run also
included downloading weights. Exported MP4 was decoded and confirmed to contain
16 RGB frames at the expected resolution and FPS (2 seconds). Sample frames were
visually inspected. CUDA availability and pip dependency checks passed.


## Desktop app

Launch UI.bat opens app.py using the existing environment. No new packages or
setup steps are needed. Run.bat remains the command-line prompt launcher.

Controls: prompt, negative prompt, length in seconds, playback FPS, diffusion
steps, prompt guidance (CFG), width, height, and seed (-1 for a random seed).
The app shows the frame count and exact playback duration after rounding.
For example, 4 seconds at 8 FPS generates 32 frames. Increasing FPS while keeping
the requested length fixed generates more frames; the model does not interpolate
frames. Higher steps can improve refinement but take longer. CFG controls prompt
strength. Large frame counts and resolutions use more memory; selectable values
are not a guarantee that every combination will fit in 12 GB of VRAM.

Generate runs in a separate process while the UI stays responsive. Progress and
errors appear in the activity log. Cancel stops that generation process. The
model reloads for each generation and releases GPU memory when it finishes.

The preview loops inside the app and can be paused. Recent videos can be selected
from the list. Reuse settings loads the selected video's JSON settings, including
its actual seed. Open video uses your normal Windows player. Output folder opens
the saved videos in Explorer. The last valid settings are remembered in
ui-settings.json when you generate or close the app. Restore default settings
returns to the original two-second configuration.

Desktop UI verified on this computer: generated a new GPU video through the UI,
checked frame settings and output selection, preview looping and pause/resume,
settings reuse, input validation, subprocess cancellation, and clean shutdown.
Layout checks passed at 1120x850 and 960x760. The form scrolls in smaller windows,
with Generate, Cancel, duration, progress and activity log kept accessible.
A ModelScope Studio shortcut is also available directly on the desktop.


## ADAM integration

The ADAM Video LoRA workspace can use this folder as its ModelScope runtime.
It reuses the .venv and model cache. PEFT 0.17.1 and Transformers 4.55.4 were
installed and pinned for LoRA support. The standalone generator remains usable.
Select ModelScope in ADAM to train and load ADAM-format ModelScope adapters.
The standalone UI continues to generate with the original base model.
