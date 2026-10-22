"""Local ModelScope 2023 video generation. Run --help for adjustable settings."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(ROOT / "cache"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
MODEL_ID = "ali-vilab/text-to-video-ms-1.7b"
REVISION = "8227dddca75a8561bf858d604cc5dae52b954d01"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", help="English video description; asks if omitted")
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--seed", type=int, default=42, help="Use -1 for a random seed")
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--guidance", type=float, default=9.0)
    parser.add_argument("--check", action="store_true", help="Check dependencies and CUDA only")
    parser.add_argument("--offline", action="store_true", help="Use downloaded weights without network")
    args = parser.parse_args()
    for name in ("steps", "frames", "width", "height", "fps"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name} must be positive")
    if args.width % 8 or args.height % 8:
        parser.error("Width and height must be multiples of 8")
    if args.seed < -1 or args.seed >= 2**63:
        parser.error("Seed must be -1 or between 0 and 2**63 - 1")
    return args


def main():
    args = parse_args()
    import torch
    import diffusers
    import transformers
    from diffusers import TextToVideoSDPipeline, DPMSolverMultistepScheduler
    from diffusers.utils import export_to_video
    import imageio_ffmpeg

    print(f"Python {sys.version.split()[0]} | torch {torch.__version__} | CUDA {torch.version.cuda}", flush=True)
    print(f"diffusers {diffusers.__version__} | transformers {transformers.__version__}", flush=True)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not available. Run Setup.bat to install the CUDA build of PyTorch.")
    gpu = torch.cuda.get_device_properties(0)
    print(f"GPU: {gpu.name} ({gpu.total_memory / 1024**3:.1f} GiB)", flush=True)
    print(f"FFmpeg: {imageio_ffmpeg.get_ffmpeg_exe()}", flush=True)
    if args.check:
        print("Dependencies and CUDA are ready.")
        return
    prompt = args.prompt
    if prompt is None:
        prompt = input("\nDescribe your video [Will Smith eating spaghetti]: ").strip() or "Will Smith eating spaghetti"
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty")
    seed = secrets.randbelow(2**32) if args.seed == -1 else args.seed
    print(f"\nPrompt: {prompt}\nSeed: {seed}", flush=True)
    print("Loading ModelScope (first run downloads several GB into the cache folder)...", flush=True)
    started = time.perf_counter()
    pipe = TextToVideoSDPipeline.from_pretrained(
        MODEL_ID, revision=REVISION, variant="fp16", torch_dtype=torch.float16,
        use_safetensors=True, local_files_only=args.offline,
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    pipe.unet.enable_forward_chunking(chunk_size=1, dim=1)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    print("Generating video...", flush=True)
    with torch.inference_mode():
        result = pipe(
            prompt=prompt, negative_prompt=args.negative_prompt or None,
            num_frames=args.frames, width=args.width, height=args.height,
            num_inference_steps=args.steps, guidance_scale=args.guidance,
            generator=generator,
        )
    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = out_dir / f"modelscope_{stamp}_seed{seed}.mp4"
    export_to_video(result.frames[0], str(output), fps=args.fps)
    metadata = dict(vars(args), prompt=prompt, seed=seed, model_id=MODEL_ID,
                    revision=REVISION, duration_seconds=args.frames / args.fps,
                    elapsed_seconds=round(time.perf_counter() - started, 2),
                    torch=torch.__version__, diffusers=diffusers.__version__,
                    transformers=transformers.__version__, gpu=gpu.name)
    output.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"\nSaved: {output}\nSettings: {output.with_suffix('.json')}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        if "out of memory" in str(exc).lower():
            print("\nClose other GPU-heavy applications, or try --frames 8 --width 256 --height 256.")
        sys.exit(1)
