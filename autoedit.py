#!/usr/bin/env python3
"""Auto Edit: turn a raw talking video into a 9:16 reel with cuts, hook, captions and optional sound.

Runs on your Mac. No API keys. Nothing is ever posted, and your original file is never changed.
"""
import argparse
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import wave
from pathlib import Path

HOME = Path(__file__).resolve().parent
W, H, FPS, SR = 1080, 1920, 30, 48000
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
HF_LOCAL = HOME / "node_modules/.bin/hyperframes"
HYPERFRAMES = str(HF_LOCAL) if HF_LOCAL.exists() else "hyperframes"
WORK = Path.home() / ".auto-edit-work"
os.environ.update(HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1")
WEAK = set("a an the and or but so of to in on at for with from my your our is are was were be that this if as "
           "ang ng sa na at si yung 'yung ko mo ka ay kung pero kasi para".split())

CSS = """
@font-face { font-family:"TTS"; src:url("fonts/TikTokSans.ttf"); font-weight:300 900; }
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1080px; height:1920px; background:#000; overflow:hidden; }
body { font-family:"TTS", sans-serif; color:#fff; }
#root { position:relative; width:1080px; height:1920px; overflow:hidden; background:#000; }
#base { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.cap { position:absolute; left:0; right:0; top:1023px; z-index:150; text-align:center; font-weight:600; font-size:56px;
  line-height:64px; color:#fff; white-space:nowrap; text-shadow:0 0 14px rgba(0,0,0,.55), 0 2px 4px rgba(0,0,0,.7); }
.hook { position:absolute; left:50%; transform:translateX(-50%); width:max-content; max-width:860px; top:980px; z-index:150;
  background:#fff; color:#111; text-align:center; font-weight:700; font-size:66px; line-height:1.14; padding:24px 34px; border-radius:20px; }
"""


class Stop(Exception):
    """A problem with a clear message for the person running this."""


def run(cmd, what):
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode:
        tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-8:])
        raise Stop(f"{what} failed.\n{tail}\n\nRun `autoedit doctor` to check your setup.")
    return done


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,color_transfer:stream_side_data=rotation:format=duration",
               "-of", "json", str(path)], "Reading the video").stdout
    info = json.loads(out)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise Stop(f"{path.name} has no video track.")
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise Stop(f"{path.name} has no audio. Auto Edit needs speech to cut and caption.")
    rotation = next((abs(int(d.get("rotation", 0))) for d in video.get("side_data_list", [])), 0)
    w, h = video["width"], video["height"]
    return {"w": h if rotation == 90 else w, "h": w if rotation == 90 else h,
            "hdr": any(k in video.get("color_transfer", "") for k in ("arib", "2084")),
            "duration": float(info["format"]["duration"])}


def normalize(src, out, meta, crop_x):
    """1080x1920, 30 fps, SDR. Phone HDR must become SDR here, or the finished reel comes out washed grey."""
    tone = "scale=in_color_matrix=bt2020:out_color_matrix=bt709,eq=contrast=1.06:saturation=1.12," if meta["hdr"] else ""
    vf = (f"{tone}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(iw-{W})*{crop_x}:(ih-{H})/2,"
          f"fps={FPS},format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map_metadata", "-1", "-vf", vf, "-c:v", "libx264", "-crf", "16", "-preset", "fast",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "1", str(out)], "Preparing the video")


def find_silences(path, noise, min_gap):
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise={noise}dB:d={min_gap}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", log)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def keep_ranges(duration, silences, manual, pad=0.1):
    """Everything except silences and manual cuts. Pad keeps the ends of words from being clipped."""
    removed = [(max(0, a + pad) if a > 0 else 0, (b - pad) if b is not None and b < duration else duration) for a, b in silences]
    removed += manual
    keep, at = [], 0.0
    for a, b in sorted(x for x in removed if x[1] > x[0]):
        if a > at:
            keep.append((at, a))
        at = max(at, b)
    if at < duration:
        keep.append((at, duration))
    return [(a, b) for a, b in keep if b - a >= 0.15]


def cut(src, out, ranges, punch):
    """Hard cuts. Every other section punches in 12% so the jump reads as a choice, not a mistake."""
    parts, labels = [], ""
    for i, (a, b) in enumerate(ranges):
        zoom = f"crop=iw/1.12:ih/1.12:(iw-ow)/2:(ih-oh)*0.3,scale={W}:{H}," if punch and i % 2 else ""
        fade = min(0.01, (b - a) / 3)
        parts.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,{zoom}setsar=1[v{i}]")
        parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d={fade:.3f},afade=t=out:st={b - a - fade:.3f}:d={fade:.3f}[a{i}]")
        labels += f"[v{i}][a{i}]"
    parts.append(f"{labels}concat=n={len(ranges)}:v=1:a=1[v][a]")
    graph = out.with_suffix(".filter")
    graph.write_text(";\n".join(parts))
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex_script", str(graph), "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)], "Cutting the video")


def transcribe(video, folder, model, lang):
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "speech.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)], "Extracting audio")
    cmd = [HYPERFRAMES, "transcribe", str(audio), "-d", str(folder), "-m", model]
    if lang:
        cmd += ["-l", lang]
    run(cmd, "Transcribing")
    return [(w["text"].strip(), float(w["start"]), float(w["end"])) for w in json.loads((folder / "transcript.json").read_text()) if w["text"].strip()]


def is_phantom(words):
    """On clips with no speech, Whisper invents YouTube sign-offs. If that's all it heard, nobody spoke."""
    text = re.sub(r"[^a-z ]", "", " ".join(w[0] for w in words).lower())
    return not re.sub(r"thank you|thanks|for watching|please|subscribe|to my channel|like|and|you|bye|music", "", text).strip()


def fix_words(words, fixes):
    table = {a.lower(): b for a, b in fixes}

    def swap(text):
        core = text.strip(".,?!:;'\"")
        return text.replace(core, table[core.lower()]) if core and core.lower() in table else text

    return [(swap(t), a, b) for t, a, b in words]


def chunks(words):
    """2-3 word captions: break at punctuation, and never end a piece on a weak word like 'the' or 'ang'."""
    phrases, current = [], []
    for w in words:
        current.append(w)
        if re.search(r"[.?!:,]$", w[0]):
            phrases.append(current)
            current = []
    if current:
        phrases.append(current)

    def weak(w):
        return w[0].strip(".,?!:'\"").lower() in WEAK

    out = []
    for ph in phrases:
        best = {0: (0, [])}
        for i in range(1, len(ph) + 1):
            options = []
            for size, cost in ((1, 6), (2, 1), (3, 0), (4, 3)):
                j = i - size
                if j in best:
                    long = 40 if len(" ".join(x[0] for x in ph[j:i])) > 26 else 0
                    options.append((best[j][0] + cost + long + (10 if i < len(ph) and weak(ph[i - 1]) else 0), best[j][1] + [(j, i)]))
            best[i] = min(options)
        for j, i in best[len(ph)][1]:
            out.append((" ".join(x[0] for x in ph[j:i]).rstrip(",:"), ph[j][1]))
    return out


def first_sentence(words):
    picked = []
    for w in words:
        picked.append(w)
        if re.search(r"[.?!]$", w[0]):
            break
    text = " ".join(x[0] for x in picked)
    if not picked or len(picked) > 12 or len(text) > 70 or not re.search(r"[.?!]$", text):
        return None, 0
    return text, picked[-1][2]


def composition(folder, video, words, duration, hook, hook_end):
    captions = chunks([w for w in words if w[1] >= hook_end - 0.05])
    tops, js, track = [], [], iter(range(10, 100000))

    def clip(cid, start, end, text, cls):
        tops.append(f'<div class="{cls}" id="{cid}" data-start="{start:.3f}" data-duration="{end - start:.3f}" data-track-index="{next(track)}">{html.escape(text)}</div>')
        if start > 0:  # without this a caption is visible from frame 0
            js.append(f'tl.set("#{cid}", {{autoAlpha:0}}, 0); tl.set("#{cid}", {{autoAlpha:1}}, {start:.3f});')
        js.append(f'tl.set("#{cid}", {{autoAlpha:0}}, {end:.3f});')

    if hook:
        clip("hook", 0, hook_end, hook, "hook")
    for k, (text, start) in enumerate(captions):
        end = captions[k + 1][1] if k + 1 < len(captions) else duration
        if end > start:
            clip(f"cap{k}", start, end, text, "cap")
    shutil.copy(video, folder / "base.mp4")
    (folder / "fonts").mkdir(exist_ok=True)
    shutil.copy(HOME / "fonts/TikTokSans.ttf", folder / "fonts/TikTokSans.ttf")
    nl = "\n"
    (folder / "index.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>reel</title><style>{CSS}</style></head>
<body>
<div id="root" data-composition-id="reel" data-start="0" data-duration="{duration:.3f}" data-width="{W}" data-height="{H}">
<video id="base" src="base.mp4" muted playsinline data-start="0" data-duration="{duration:.3f}" data-track-index="0"></video>
{nl.join(tops)}
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{nl.join(js)}
window.__timelines["reel"] = tl;
</script>
</div>
</body></html>
""")
    return len(captions)


def read_audio(path, filters="", extra=()):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", *extra, "-i", str(path)] + (["-af", filters] if filters else []) + ["-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    return np.frombuffer(run_bytes(cmd), dtype="<f4").astype(float)


def run_bytes(cmd):
    done = subprocess.run(cmd, capture_output=True)
    if done.returncode:
        raise Stop(f"Reading audio failed.\n{done.stderr.decode(errors='replace')[-500:]}")
    return done.stdout


def mix(video, out_wav, duration, hook_end, sound_times, music):
    """Voice on top. Music sits at 25% under the hook, then 10%, and dips whenever someone is talking."""
    import numpy as np
    import sfx
    n = int(SR * duration)
    final = np.zeros(n)
    voice = read_audio(video, "highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=80")[:n]
    voice = voice / max(np.abs(voice).max(), 1e-6)
    final[:len(voice)] += 0.95 * voice
    if music:
        if music == "bed":
            bed = sfx.music_bed(duration, bpm=104, gain=1.0)[:n]
        else:
            bed = read_audio(music, f"afade=t=out:st={max(duration - 1.5, 0):.3f}:d=1.5", ("-stream_loop", "-1", "-t", f"{duration:.3f}"))[:n]
            bed = bed / max(np.abs(bed).max(), 1e-6)
        level = np.full(n, 0.10)
        level[:int(SR * hook_end)] = 0.25
        envelope = np.convolve(np.abs(final), np.ones(2400) / 2400, mode="same")
        duck = 1 - 0.55 * np.clip(envelope / (envelope.max() + 1e-9) * 3, 0, 1)
        final[:len(bed)] += (level * duck)[:len(bed)] * bed
    for t, kind, gain in sound_times:
        s = sfx.KINDS[kind]()
        s = gain * s / max(np.abs(s).max(), 1e-6)
        i = int(SR * t)
        final[i:i + len(s)] += s[:max(n - i, 0)]
    final *= 0.89 / max(np.abs(final).max(), 0.89)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(np.repeat((final * 32767).astype("<i2")[:, None], 2, axis=1).tobytes())


def sound_cues(ranges, hook, hook_end):
    """Light touch: a pop when the hook appears, a soft whoosh on cuts, at least 3 seconds apart."""
    cues = [(0.0, "soft_pop", 0.3)] if hook else []
    at, last = 0.0, hook_end
    for a, b in ranges[:-1]:
        at += b - a
        if at - last >= 3:
            cues.append((at, "soft_whoosh", 0.16))
            last = at
    return cues


def free_path(path):
    if not path.exists():
        return path
    n = 2
    while path.with_name(f"{path.stem}-{n}{path.suffix}").exists():
        n += 1
    return path.with_name(f"{path.stem}-{n}{path.suffix}")


def edit(args):
    src = Path(args.video).expanduser().resolve()
    if not src.is_file():
        raise Stop(f"Can't find this video: {src}")
    if src.suffix.lower() not in VIDEO_EXT:
        raise Stop(f"{src.name} doesn't look like a video ({', '.join(sorted(VIDEO_EXT))}).")
    if args.music and args.music != "bed" and not Path(args.music).expanduser().is_file():
        raise Stop(f"Can't find this music file: {args.music}")
    meta = probe(src)
    out = free_path(Path(args.out).expanduser().resolve() if args.out else src.with_name(f"{src.stem}-edited.mp4"))
    job = WORK / hashlib.sha1(f"{src}{src.stat().st_mtime}".encode()).hexdigest()[:10]
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)

    print(f"1/5 Preparing {src.name} ({meta['duration']:.0f}s)")
    if meta["w"] > meta["h"]:
        print("    Landscape video: cropping the centre to vertical. Use --crop-x 0 (left) to 1 (right) if you're off-centre.")
    norm = job / "norm.mp4"
    normalize(src, norm, meta, args.crop_x)
    print("2/5 Cutting silences")
    manual = [tuple(float(x) for x in c.split("-")) for c in args.cut]
    silences = [] if args.no_cuts else find_silences(norm, args.noise, args.gap)
    ranges = keep_ranges(probe(norm)["duration"], silences, manual)
    if not ranges:
        raise Stop("Everything was detected as silence. Try --noise -45, or --no-cuts.")
    cut_video = job / "cut.mp4"
    cut(norm, cut_video, ranges, not args.no_punch)
    duration = probe(cut_video)["duration"]
    print(f"    {meta['duration']:.1f}s down to {duration:.1f}s, {len(ranges) - 1} cuts")

    print("3/5 Transcribing on this Mac (the first run downloads a speech model, about 500 MB)")
    words = transcribe(cut_video, job / "t", args.model, args.lang)
    if not words or is_phantom(words):
        raise Stop("No speech was found in this video. Auto Edit is for videos where someone is talking.")
    words = fix_words(words, [f.split("=", 1) for f in args.fix if "=" in f])

    if args.no_hook:
        hook, hook_end = None, 0
    else:
        hook, hook_end = first_sentence(words)
        if args.hook:
            hook, hook_end = args.hook, min(max(hook_end, 2.5), 6)
    print("4/5 Rendering hook and captions" + (f'\n    Hook: "{hook}"' if hook else ""))
    project = job / "project"
    project.mkdir()
    count = composition(project, cut_video, words, duration, hook, hook_end)
    picture = job / "picture.mp4"
    run([HYPERFRAMES, "render", str(project), "-o", str(picture), "--sdr", "-f", str(FPS)], "Rendering")

    print("5/5 Mixing sound")
    audio = job / "audio.wav"
    cues = sound_cues(ranges, hook, hook_end) if args.sfx else []
    music = str(Path(args.music).expanduser()) if args.music and args.music != "bed" else args.music
    mix(cut_video, audio, duration, hook_end, cues, music)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(picture), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-map_metadata", "-1",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-af", "loudnorm=I=-15:TP=-1.5:LRA=9",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", "-shortest", str(out)], "Exporting")
    if args.keep:
        print(f"Work files kept: {job}")
    else:
        shutil.rmtree(job, ignore_errors=True)
    print(f"\nDone: {out}\n{count} captions. Watch it before posting: speech recognition can misspell words. Fix one with --fix \"wrong=right\".")
    return out


def show_transcript(args):
    src = Path(args.video).expanduser().resolve()
    if not src.is_file():
        raise Stop(f"Can't find this video: {src}")
    job = WORK / "transcript"
    shutil.rmtree(job, ignore_errors=True)
    words = transcribe(src, job, args.model, args.lang)
    line, start = [], None
    for text, a, _b in words:
        start = a if start is None else start
        line.append(text)
        if re.search(r"[.?!]$", text) or len(line) >= 14:
            print(f"{start:7.2f}  {' '.join(line)}")
            line, start = [], None
    if line:
        print(f"{start:7.2f}  {' '.join(line)}")


def doctor(_args):
    ok = True

    def check(name, good, fix):
        nonlocal ok
        print(f"{'OK ' if good else 'NO '} {name}" + ("" if good else f"\n    Fix: {fix}"))
        ok = ok and good

    def has_numpy():
        try:
            import numpy  # noqa: F401
            return True
        except ImportError:
            return False

    check("ffmpeg", bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")), "brew install ffmpeg")
    check("Node", bool(shutil.which("node")), "brew install node")
    check("HyperFrames", HF_LOCAL.exists() or bool(shutil.which("hyperframes")), f"cd {HOME} && npm install")
    check("numpy", has_numpy(), f"re-run the installer, or {HOME}/.venv/bin/pip install numpy")
    check("caption font", (HOME / "fonts/TikTokSans.ttf").exists(), "re-run the installer")
    print(f"Free disk space: {shutil.disk_usage(Path.home()).free // 1024 ** 3} GB (keep at least 5 GB free)")
    if shutil.which("node") and (HF_LOCAL.exists() or shutil.which("hyperframes")):
        print("\nHyperFrames' own check:")
        subprocess.run([HYPERFRAMES, "doctor"])
    print("\nReady." if ok else "\nFix the lines marked NO, then run this again.")
    return ok


def ask(question):
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def dragged_path(raw):
    """Terminal escapes dragged paths; someone typing one by hand might not."""
    if Path(raw).expanduser().exists():
        return raw
    try:
        parts = shlex.split(raw)
    except ValueError:
        return raw
    return parts[0] if len(parts) == 1 else raw


def wizard():
    """Double-click mode: the three questions, nothing else."""
    print("Auto Edit\n")
    raw = input("Drag your video into this window, then press Enter: ").strip()
    if not raw:
        raise Stop("No video given.")
    argv = [dragged_path(raw)]
    if ask("Add sound effects?"):
        argv.append("--sfx")
    if ask("Add background music?"):
        track = input("Drag your music file here, or press Enter for the built-in beat: ").strip()
        argv += ["--music", dragged_path(track) if track else "bed"]
    return argv


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["doctor"]:
        return 0 if doctor(None) else 1
    transcript_mode = argv[:1] == ["transcript"]
    if transcript_mode:
        argv = argv[1:]
    elif not argv:
        argv = wizard()
    p = argparse.ArgumentParser(prog="autoedit", description=__doc__, epilog="Other commands: autoedit doctor, autoedit transcript VIDEO")
    p.add_argument("video")
    p.add_argument("--sfx", action="store_true", help="add sound effects")
    p.add_argument("--music", metavar="FILE", help="music file you have the rights to, or 'bed' for the built-in beat")
    p.add_argument("--hook", help="your own hook text (default: the first sentence, if it's short)")
    p.add_argument("--no-hook", action="store_true", help="captions only")
    p.add_argument("--no-cuts", action="store_true", help="keep the pauses")
    p.add_argument("--no-punch", action="store_true", help="no zoom on cuts")
    p.add_argument("--cut", action="append", default=[], metavar="START-END", help="also remove this part, in seconds of the original, e.g. 12.3-14.1")
    p.add_argument("--fix", action="append", default=[], metavar="WRONG=RIGHT", help="correct a misheard word in captions")
    p.add_argument("--gap", type=float, default=0.45, help="shortest pause to remove, seconds")
    p.add_argument("--noise", type=float, default=-32, help="what counts as silence, dB (use -45 in a quiet room if speech gets clipped)")
    p.add_argument("--crop-x", type=float, default=0.5, help="landscape only: 0 keeps the left side, 1 the right")
    p.add_argument("--model", default="small", help="speech model: tiny, base, small, medium, large-v3")
    p.add_argument("--lang", help="language code such as en or tl (default: detect)")
    p.add_argument("-o", "--out", help="output file (default: next to the original, ending in -edited)")
    p.add_argument("--keep", action="store_true", help="keep work files")
    args = p.parse_args(argv)
    if transcript_mode:
        show_transcript(args)
        return 0
    if any(not re.fullmatch(r"[\d.]+-[\d.]+", c) for c in args.cut):
        raise Stop("--cut needs START-END in seconds, like 12.3-14.1")
    if not 0 <= args.crop_x <= 1:
        raise Stop("--crop-x must be between 0 and 1")
    edit(args)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(HOME))
    try:
        sys.exit(main())
    except Stop as problem:
        print(f"\n{problem}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
