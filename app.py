"""Desktop interface for the local ModelScope generator."""
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import imageio.v2 as imageio
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = ROOT / "ui-settings.json"
DEFAULTS = dict(prompt="Will Smith eating spaghetti", negative_prompt="", duration=2,
                fps=8, steps=25, guidance=9.0, seed=42, width=256, height=256)


def validate_settings(values):
    """Return engine arguments and the exact duration implied by rounded frames."""
    settings = dict(values)
    settings["prompt"] = str(settings["prompt"]).strip()
    if not settings["prompt"]:
        raise ValueError("Enter a prompt describing your video.")
    for name in ("fps", "steps", "seed", "width", "height"):
        try:
            settings[name] = int(str(settings[name]))
        except ValueError:
            raise ValueError(f"{name.title()} must be a whole number.") from None
    for name in ("duration", "guidance"):
        try:
            settings[name] = float(settings[name])
        except ValueError:
            raise ValueError(f"{name.title()} must be a number.") from None
        if not math.isfinite(settings[name]):
            raise ValueError(f"{name.title()} must be finite.")
    if settings["fps"] < 1 or settings["fps"] > 60:
        raise ValueError("Playback FPS must be between 1 and 60.")
    if settings["duration"] <= 0:
        raise ValueError("Duration must be greater than zero.")
    frames = round(settings["duration"] * settings["fps"])
    if not 2 <= frames <= 512:
        raise ValueError("Choose a duration and FPS resulting in 2 to 512 frames.")
    if not 1 <= settings["steps"] <= 200:
        raise ValueError("Steps must be between 1 and 200.")
    if not 0 <= settings["guidance"] <= 30:
        raise ValueError("Guidance must be between 0 and 30.")
    if not -1 <= settings["seed"] < 2**63:
        raise ValueError("Seed must be -1 (random), or 0 to 9223372036854775807.")
    if any(not 64 <= settings[k] <= 1024 or settings[k] % 8 for k in ("width", "height")):
        raise ValueError("Width and height must be multiples of 8, from 64 to 1024.")
    settings["frames"] = frames
    return settings


def engine_command(settings):
    # pythonw launches the UI without a console; use python.exe for captured logs.
    python = Path(sys.executable).with_name("python.exe")
    args = [str(python), "-u", str(ROOT / "generate.py")]
    for name in ("prompt", "negative_prompt", "fps", "steps", "guidance", "seed",
                 "width", "height", "frames"):
        args.append("--" + name.replace("_", "-") + "=" + str(settings[name]))
    return args


class ModelScopeApp:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.busy = False
        self.cancelled = False
        self.closing = False
        self.events = queue.Queue()
        self.reader = None
        self.preview_job = None
        self.preview_path = None
        self.last_output = None
        self.output_paths = []
        self.editable = []
        self.photo = None
        self.denoising = False
        root.title("ModelScope Studio · Local Video Generator")
        root.geometry("1120x850")
        root.minsize(960, 760)
        root.configure(bg="#141a26")
        self.style()
        self.values = {k: tk.StringVar(value=str(v)) for k, v in DEFAULTS.items()
                       if k not in ("prompt", "negative_prompt")}
        self.status = tk.StringVar(value="Ready · RTX 3060 defaults")
        self.duration_label = tk.StringVar()
        self.preview_status = tk.StringVar(value="Your generated video will appear here")
        self.build()
        self.restore()
        for name in ("duration", "fps", "width", "height", "steps"):
            self.values[name].trace_add("write", self.update_duration)
        self.update_duration()
        self.refresh_outputs()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_job = root.after(100, self.poll)

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background="#141a26", foreground="#e6edf7", font=("Segoe UI", 10))
        style.configure("TFrame", background="#141a26")
        style.configure("TLabelframe", bordercolor="#344057")
        style.configure("TLabelframe.Label", foreground="#9fb6de", font=("Segoe UI Semibold", 10))
        style.configure("TEntry", fieldbackground="#202b3d", foreground="#e6edf7", insertcolor="white")
        style.configure("TSpinbox", fieldbackground="#202b3d", foreground="#e6edf7", arrowsize=16)
        style.configure("TButton", background="#2b3a52", foreground="white", padding=(12, 7))
        style.map("TButton", background=[("active", "#3b5275"), ("disabled", "#222a36")])
        style.configure("Accent.TButton", background="#366cda", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#4784f5"), ("disabled", "#283b59")])
        style.configure("TProgressbar", troughcolor="#202b3d", background="#69a6ff")

    def build(self):
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        ttk.Label(outer, text="ModelScope Studio", font=("Segoe UI Semibold", 23)).grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text="2023 text-to-video · Runs locally on your GPU", foreground="#9eafc6").grid(row=1, column=0, sticky="w", pady=(0, 16))
        body = ttk.Frame(outer)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=4, uniform="panels")
        body.columnconfigure(1, weight=5, uniform="panels")
        body.rowconfigure(0, weight=1)
        left_panel = ttk.Frame(body)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        scroll_host = ttk.Frame(left_panel)
        scroll_host.pack(fill="both", expand=True)
        self.form_canvas = tk.Canvas(scroll_host, background="#141a26", highlightthickness=0, width=1, height=1)
        form_scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=self.form_canvas.yview)
        form_scrollbar.pack(side="right", fill="y")
        self.form_canvas.pack(side="left", fill="both", expand=True)
        self.form_canvas.configure(yscrollcommand=form_scrollbar.set)
        left = ttk.Frame(self.form_canvas)
        form_window = self.form_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda _: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind("<Configure>", lambda e: self.form_canvas.itemconfigure(form_window, width=e.width))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(left, text="Describe your video", font=("Segoe UI Semibold", 11)).pack(anchor="w")
        self.prompt = self.textbox(left, 4)
        ttk.Label(left, text="Negative prompt (optional)").pack(anchor="w", pady=(10, 0))
        self.negative = self.textbox(left, 2)
        settings = ttk.LabelFrame(left, text="Generation settings", padding=12)
        settings.pack(fill="x", pady=12)
        for col in (0, 1):
            settings.columnconfigure(col, weight=1)
        fields = [("duration", "Length (seconds)", 0.25, 64, 0.25),
                  ("fps", "Playback FPS", 1, 60, 1),
                  ("steps", "Diffusion steps", 1, 200, 1),
                  ("guidance", "Prompt guidance (CFG)", 0, 30, 0.5),
                  ("width", "Width", 64, 1024, 8),
                  ("height", "Height", 64, 1024, 8),
                  ("seed", "Seed (-1 = random)", -1, 2**32 - 1, 1)]
        for index, (name, label, low, high, step) in enumerate(fields):
            row, col = divmod(index, 2)
            cell = ttk.Frame(settings)
            cell.grid(row=row, column=col, sticky="ew", padx=(0, 10) if col == 0 else 0, pady=(0, 8))
            ttk.Label(cell, text=label).pack(anchor="w")
            widget = ttk.Spinbox(cell, textvariable=self.values[name], from_=low, to=high, increment=step, width=16)
            widget.pack(fill="x", pady=(3, 0))
            self.editable.append(widget)
        ttk.Label(left_panel, textvariable=self.duration_label, foreground="#89b7ff", wraplength=405).pack(anchor="w", pady=(6, 0))
        ttk.Label(left, text="More frames increase video length and memory use. Higher FPS also increases the frame count for your chosen length. Start at 2 seconds, 8 FPS, 256×256.", wraplength=405, foreground="#9eafc6").pack(anchor="w", pady=(6, 10))
        actions = ttk.Frame(left_panel)
        actions.pack(fill="x", pady=(8, 8))
        self.generate_button = ttk.Button(actions, text="Generate video", style="Accent.TButton", command=self.generate)
        self.generate_button.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.reset_button = ttk.Button(left_panel, text="Restore default settings", command=self.reset)
        self.reset_button.pack(anchor="w")
        self.editable.append(self.reset_button)

        preview = ttk.LabelFrame(right, text="Video preview", padding=10)
        preview.pack(fill="both", expand=True)
        self.preview = tk.Label(preview, width=1, height=1, text="Generate a video or select one below", bg="#0c111b", fg="#9eafc6", font=("Segoe UI", 11))
        self.preview.pack(fill="both", expand=True, ipady=25)
        ttk.Label(preview, textvariable=self.preview_status).pack(anchor="w", pady=(7, 0))
        playback = ttk.Frame(right)
        playback.pack(fill="x", pady=8)
        self.play_button = ttk.Button(playback, text="Pause preview", command=self.toggle_preview, state="disabled")
        self.play_button.pack(side="left")
        self.open_button = ttk.Button(playback, text="Open video", command=self.open_video, state="disabled")
        self.open_button.pack(side="left", padx=6)
        ttk.Button(playback, text="Output folder", command=self.open_outputs).pack(side="right")
        history_bar = ttk.Frame(right)
        history_bar.pack(fill="x")
        ttk.Label(history_bar, text="Recent videos").pack(side="left")
        self.reuse_button = ttk.Button(history_bar, text="Reuse settings", command=self.reuse_settings)
        self.reuse_button.pack(side="right")
        self.editable.append(self.reuse_button)
        history_frame = ttk.Frame(right)
        history_frame.pack(fill="x", pady=(4, 0))
        self.history = tk.Listbox(history_frame, height=4, bg="#202b3d", fg="#e6edf7", selectbackground="#366cda", borderwidth=0, highlightthickness=0, exportselection=False, font=("Segoe UI", 9))
        self.history.pack(side="left", fill="x", expand=True)
        scroll = ttk.Scrollbar(history_frame, orient="vertical", command=self.history.yview)
        scroll.pack(side="right", fill="y")
        self.history.configure(yscrollcommand=scroll.set)
        self.history.bind("<<ListboxSelect>>", self.select_video)
        ttk.Label(outer, textvariable=self.status).grid(row=3, column=0, sticky="w", pady=(12, 4))
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.grid(row=4, column=0, sticky="ew")
        log_frame = ttk.LabelFrame(outer, text="Activity log", padding=5)
        log_frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.log = tk.Text(log_frame, height=5, wrap="word", bg="#0c111b", fg="#a9bad4", font=("Consolas", 9), borderwidth=0, state="disabled")
        self.log.pack(side="left", fill="x", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)
        def scroll_form(event):
            self.form_canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"
        def bind_scrolling(widget):
            widget.bind("<MouseWheel>", scroll_form)
            for child in widget.winfo_children():
                bind_scrolling(child)
        bind_scrolling(left)

    def textbox(self, parent, height):
        widget = tk.Text(parent, width=1, height=height, wrap="word", bg="#202b3d", fg="#e6edf7", insertbackground="white", relief="flat", font=("Segoe UI", 10), padx=8, pady=6, undo=True)
        widget.pack(fill="x", pady=(4, 0))
        self.editable.append(widget)
        return widget

    def set_values(self, settings):
        for key, variable in self.values.items():
            variable.set(str(settings.get(key, DEFAULTS[key])))
        for widget, key in ((self.prompt, "prompt"), (self.negative, "negative_prompt")):
            widget.delete("1.0", "end")
            widget.insert("1.0", settings.get(key, DEFAULTS[key]))

    def restore(self):
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            settings = validate_settings({**DEFAULTS, **saved})
        except (OSError, ValueError, TypeError, KeyError):
            settings = DEFAULTS
        self.set_values(settings)

    def reset(self):
        self.set_values(DEFAULTS)

    def get_values(self):
        return dict({k: v.get() for k, v in self.values.items()},
                    prompt=self.prompt.get("1.0", "end-1c"),
                    negative_prompt=self.negative.get("1.0", "end-1c"))

    def save_settings(self):
        try:
            settings = validate_settings(self.get_values())
            SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def update_duration(self, *_):
        try:
            fps = int(self.values["fps"].get())
            frames = round(float(self.values["duration"].get()) * fps)
            actual = frames / fps
            self.duration_label.set(f"{frames} frames · {actual:g} seconds at {fps} FPS")
        except (ValueError, ZeroDivisionError, OverflowError):
            self.duration_label.set("Enter a valid length and FPS")

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 600:
            self.log.delete("1.0", "100.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def generate(self):
        if self.busy:
            return
        try:
            settings = validate_settings(self.get_values())
        except ValueError as exc:
            messagebox.showerror("Check settings", str(exc), parent=self.root)
            return
        self.save_settings()
        self.cancelled = False
        self.denoising = False
        self.busy = True
        self.last_output = None
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status.set("Loading model…")
        self.generate_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        for widget in self.editable:
            widget.configure(state="disabled")
        self.append_log(f"Starting {settings['frames']} frames, {settings['width']}×{settings['height']}, {settings['steps']} steps")
        try:
            self.process = subprocess.Popen(engine_command(settings), cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
                env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
        except OSError as exc:
            self.append_log(str(exc))
            self.finish(1)
            return
        threading.Thread(target=self.read_output, args=(self.process,), daemon=True).start()

    def read_output(self, process):
        try:
            for line in process.stdout:
                if line.strip():
                    self.events.put(("line", line.strip()))
        finally:
            process.stdout.close()
            self.events.put(("done", process.wait()))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "done":
                    self.finish(value)
                else:
                    self.append_log(value)
                    match = re.search(r"(\d+)/(\d+)\s*\[", value)
                    if value == "Generating video...":
                        self.denoising = True
                    if match and self.denoising:
                        done, total = map(int, match.groups())
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=100 * done / max(total, 1))
                        self.status.set(f"Generating · step {done} of {total}" if done < total else "Encoding video…")
                    if value.startswith("Saved: "):
                        self.last_output = Path(value[7:])
        except queue.Empty:
            pass
        if not self.closing:
            self.poll_job = self.root.after(100, self.poll)

    def finish(self, returncode):
        self.busy = False
        self.process = None
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.cancel_button.configure(state="disabled")
        self.generate_button.configure(state="normal")
        for widget in self.editable:
            widget.configure(state="normal")
        if self.cancelled:
            self.status.set("Generation cancelled")
            self.progress["value"] = 0
        elif returncode == 0 and self.last_output and self.last_output.exists():
            self.status.set(f"Saved · {self.last_output.name}")
            self.progress["value"] = 100
            self.refresh_outputs(self.last_output)
        else:
            self.status.set("Generation failed · see the activity log")
            self.progress["value"] = 0
            messagebox.showerror("Generation failed", "See the activity log for details. For CUDA out-of-memory errors, reduce the length or resolution and close other GPU-heavy apps.", parent=self.root)

    def cancel(self):
        if self.process is not None and self.process.poll() is None:
            self.cancelled = True
            self.status.set("Cancelling…")
            self.cancel_button.configure(state="disabled")
            # Stop only this application's generation process and its child tree.
            try:
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.append_log(f"Could not stop generation: {exc}")
                self.cancel_button.configure(state="normal")

    def refresh_outputs(self, select=None):
        self.output_paths = sorted((ROOT / "outputs").glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        self.history.delete(0, "end")
        for path in self.output_paths:
            self.history.insert("end", path.name)
        if self.output_paths:
            index = self.output_paths.index(select) if select in self.output_paths else 0
            self.history.selection_set(index)
            self.history.see(index)
            self.load_preview(self.output_paths[index])

    def select_video(self, _=None):
        selection = self.history.curselection()
        if selection:
            self.load_preview(self.output_paths[selection[0]])

    def stop_preview(self):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
            self.preview_job = None
        if self.reader is not None:
            self.reader.close()
            self.reader = None

    def load_preview(self, path):
        self.stop_preview()
        self.preview_path = path
        try:
            self.reader = imageio.get_reader(str(path))
            meta = self.reader.get_meta_data()
            self.preview_delay = max(16, round(1000 / max(meta.get("fps", 8), 1)))
            self.preview_status.set(f"{meta['size'][0]}×{meta['size'][1]} · {meta.get('duration', 0):g}s · {meta.get('fps', 8):g} FPS")
            self.open_button.configure(state="normal")
            self.play_button.configure(state="normal", text="Pause preview")
            self.preview_frame()
        except Exception as exc:
            self.stop_preview()
            self.preview_status.set("Could not preview this video. Use Open video.")
            self.append_log(f"Preview: {exc}")

    def preview_frame(self):
        self.preview_job = None
        if self.reader is None:
            return
        try:
            try:
                frame = self.reader.get_next_data()
            except IndexError:
                frame = self.reader.get_data(0)
            picture = Image.fromarray(frame)
            scale = min(max(200, self.preview.winfo_width() - 12) / picture.width,
                        max(160, self.preview.winfo_height() - 12) / picture.height, 2.0)
            picture = picture.resize((max(1, round(picture.width * scale)),
                                      max(1, round(picture.height * scale))), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(picture)
            self.preview.configure(image=self.photo, text="")
            self.preview_job = self.root.after(self.preview_delay, self.preview_frame)
        except Exception as exc:
            self.append_log(f"Preview stopped: {exc}")
            self.stop_preview()
            self.play_button.configure(text="Play preview")

    def toggle_preview(self):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
            self.preview_job = None
            self.play_button.configure(text="Play preview")
        elif self.reader is not None:
            self.play_button.configure(text="Pause preview")
            self.preview_frame()
        elif self.preview_path:
            self.load_preview(self.preview_path)

    def reuse_settings(self):
        if not self.preview_path or self.busy:
            return
        try:
            saved = json.loads(self.preview_path.with_suffix(".json").read_text(encoding="utf-8"))
            saved["duration"] = saved["frames"] / saved["fps"]
            self.set_values(validate_settings({**DEFAULTS, **saved}))
            self.status.set("Loaded settings from selected video")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Settings unavailable", str(exc), parent=self.root)

    def open_video(self):
        if self.preview_path and self.preview_path.exists():
            os.startfile(str(self.preview_path))

    def open_outputs(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        os.startfile(str(ROOT / "outputs"))

    def close(self):
        if self.busy and not messagebox.askyesno("Close ModelScope Studio?", "Cancel the current generation and close the app?", parent=self.root):
            return
        self.save_settings()
        self.cancel()
        self.closing = True
        self.root.after_cancel(self.poll_job)
        self.stop_preview()
        self.root.destroy()


def main():
    root = tk.Tk()
    ModelScopeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
