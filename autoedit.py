#!/usr/bin/env python3
"""Auto Edit: turn a raw talking video into a 9:16 reel with cuts, hook, captions and optional sound.

Runs on your Mac or Windows PC. No API keys. Nothing is ever posted, and your original file is never changed.
"""
import argparse
import hashlib
import html
import json
import math
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
MAC, WINDOWS = sys.platform == "darwin", sys.platform == "win32"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
HF_LOCAL = HOME / "node_modules/hyperframes/bin/hyperframes.mjs"
# Run HyperFrames through node, not its .bin shim: on Windows that shim is a .cmd file, which mangles arguments.
HYPERFRAMES = [shutil.which("node") or "node", str(HF_LOCAL)] if HF_LOCAL.exists() else ["hyperframes"]
MASK_MODEL = HOME / "models/selfie_multiclass_256x256.tflite"
WORK = Path.home() / ".auto-edit-work"
os.environ.update(HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1")
HOOK_TOP = 288  # below this line is clear of the app's top bar
WEAK = set("a an the and or but so of to in on at for with from my your our is are was were be that this if as "
           "ang ng sa na at si yung 'yung ko mo ka ay kung pero kasi para".split())

CSS = """
@font-face { font-family:"TTS"; src:url("fonts/TikTokSans.ttf"); font-weight:300 900; }
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1080px; height:1920px; background:transparent; overflow:hidden; }
body { font-family:"TTS", sans-serif; color:#fff; }
#root { position:relative; width:1080px; height:1920px; overflow:hidden; background:transparent; }
.cap { position:absolute; left:0; right:0; top:1025px; z-index:150; text-align:center; font-weight:550; font-size:52px;
  line-height:60px; color:#fff; white-space:nowrap; text-shadow:0 0 13px rgba(0,0,0,.2); }
.hook { position:absolute; left:50%; transform:translateX(-50%); width:max-content; max-width:720px; top:980px; z-index:150;
  background:#fff; color:#111; text-align:center; font-weight:700; font-size:54px; line-height:1.14; padding:22px 30px; border-radius:20px; }
.big { position:absolute; left:0; right:0; top:450px; z-index:50; text-align:center; font-weight:900; letter-spacing:-.03em;
  line-height:1; white-space:nowrap; text-shadow:0 12px 50px rgba(0,0,0,.45); }
.split { display:flex; justify-content:center; gap:320px; }
.card { position:absolute; z-index:50; width:315px; background:#fff; color:#111; border-radius:26px; padding:22px 24px;
  font-size:31px; font-weight:600; line-height:1.28; box-shadow:0 24px 60px rgba(0,0,0,.42); overflow:hidden; }
.card img { display:block; width:100%; border-radius:14px; }
"""


class Stop(Exception):
    """A problem with a clear message for the person running this."""


def run(cmd, what):
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode:
        tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-8:])
        raise Stop(f"{what} failed.\n{tail}\n\nRun `autoedit doctor` to check your setup.")
    return done


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "stream=codec_type,width,height,color_transfer,start_time:stream_side_data=rotation:format=duration",
               "-of", "json", str(path)], "Reading the video").stdout
    info = json.loads(out)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise Stop(f"{path.name} has no video track.")
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not audio:
        raise Stop(f"{path.name} has no audio. Auto Edit needs speech to cut and caption.")
    rotation = next((abs(int(d.get("rotation", 0))) for d in video.get("side_data_list", [])), 0)
    w, h = video["width"], video["height"]
    return {"w": h if rotation == 90 else w, "h": w if rotation == 90 else h,
            "hdr": any(k in video.get("color_transfer", "") for k in ("arib", "2084")),
            "duration": float(info["format"]["duration"]),
            "audio_late": float(audio.get("start_time", 0)) - float(video.get("start_time", 0))}


def source_audio(src, meta, out):
    """The original sound, lined up with the picture's first frame, as one file both the voice detector and the mix use."""
    import numpy as np
    audio = read_audio(src)
    shift = round(meta["audio_late"] * SR)
    audio = np.concatenate([np.zeros(shift), audio]) if shift > 0 else audio[-shift:]
    save_wav(out, audio)
    return audio


def prepare(src, out, meta, crop_x, ranges):
    """One pass: 1080x1920, 30 fps, SDR, with the pauses cut. Phone HDR must become SDR here, or the reel comes out washed grey.

    Hard cuts, no zoom. The camera stays still unless the editor picks a line to punch in on."""
    tone = "scale=in_color_matrix=bt2020:out_color_matrix=bt709,eq=contrast=1.06:saturation=1.12," if meta["hdr"] else ""
    keep = "+".join(f"between(n,{round(a * FPS)},{round(b * FPS) - 1})" for a, b in ranges)
    graph = out.with_suffix(".filter")
    graph.write_text(f"[0:v]{tone}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(iw-{W})*{crop_x}:(ih-{H})/2,"
                     f"fps={FPS},select='{keep}',setpts=N/{FPS}/TB,format=yuv420p,"
                     f"setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[v]", encoding="utf-8")
    # A working copy: quick to write and nearly lossless, since the export encodes it once more.
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-/filter_complex", str(graph), "-map", "[v]", "-an", "-map_metadata", "-1",
         "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", str(out)], "Preparing the video")


def cut_audio(audio, ranges, out):
    """The same cuts as the picture, sample-exact, each with a 10 ms fade so a cut never clicks."""
    import numpy as np
    parts = []
    for a, b in ranges:
        part = audio[round(a * SR):round(b * SR)]
        part = np.concatenate([part, np.zeros(round((b - a) * SR) - len(part))])  # past the end of the sound: silence, so sync holds
        fade = min(int(SR * 0.01), len(part) // 3)
        ramp = np.linspace(0, 1, fade)
        part[:fade] *= ramp
        part[len(part) - fade:] *= ramp[::-1]
        parts.append(part)
    save_wav(out, np.concatenate(parts))


def save_wav(path, samples, channels=1):
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], channels, axis=1).tobytes())


def voice_ranges(path):
    """Where a voice detector hears speech. Volume can't tell a word from a rubbing shirt or a click; this can."""
    audio = path.with_suffix(".16k.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(audio)], "Extracting audio")
    out = run(["whisper-vad-speech-segments", "-f", str(audio), "-vm", str(HOME / "models/ggml-silero-v5.1.2.bin")], "Finding your voice").stdout
    return [(float(a) / 100, float(b) / 100) for a, b in re.findall(r"start = ([\d.]+), end = ([\d.]+)", out)]


def find_silences(path, audio, noise, min_gap):
    """Keep only what is voice AND within 11 dB of this speaker's level, so pauses inside a sentence go too."""
    import numpy as np
    voice = voice_ranges(path)
    if not voice:
        raise Stop("No speech was found in this video. Auto Edit is for videos where someone is talking.")
    size = int(SR * 0.02)
    frames = audio[:len(audio) // size * size].reshape(-1, size)
    level = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    in_voice = np.zeros(len(level), dtype=bool)
    for a, b in voice:
        in_voice[int(a / 0.02):int(b / 0.02) + 1] = True
    speaking = np.percentile(level[in_voice], 75)
    noise = speaking - 11 if noise is None else noise
    loud = np.flatnonzero(in_voice & (level >= noise))
    speech, start, gap = [], None, max(int(min_gap / 0.02), 1)
    for i, frame in enumerate(loud):
        start = frame if start is None else start
        if i + 1 == len(loud) or loud[i + 1] - frame > gap or not in_voice[frame:loud[i + 1]].all():
            speech.append((start, frame + 1))
            start = None
    silences, at = [], 0
    for a, b in speech:
        if a > at:
            silences.append((at * 0.02, a * 0.02))
        at = b
    if at < len(level):
        silences.append((at * 0.02, len(level) * 0.02))
    return silences


def keep_ranges(duration, silences, manual, tail=0.06, lead=0.02):
    """Everything except silences and manual cuts. Keeps each word's own fade so endings aren't clipped.

    Every cut lands on a frame boundary, so the sound cut to match can never drift from the lips."""
    removed = [(a + tail if a > 0 else 0, b - lead if b < duration else duration) for a, b in silences]
    removed += manual
    removed = [(math.ceil(a * FPS) / FPS, math.floor(b * FPS) / FPS) for a, b in removed]  # shrink, never trim a word
    end = math.floor(duration * FPS) / FPS
    keep, at = [], 0.0
    for a, b in sorted(x for x in removed if x[1] > x[0]):
        if a > at:
            keep.append((at, min(a, end)))
        at = max(at, b)
    if at < end:
        keep.append((at, end))
    return [(a, b) for a, b in keep if b - a >= 0.15]


def swift_tool():
    """personmask.swift, compiled once. Running the .swift file directly recompiles it on every edit, which costs seconds each time."""
    src, tool = HOME / "personmask.swift", HOME / ".build/personmask"
    if not tool.exists() or tool.stat().st_mtime < src.stat().st_mtime:
        tool.parent.mkdir(exist_ok=True)
        run(["swiftc", "-O", str(src), "-o", str(tool)], "Building the person finder")
    return tool


def person_mask(video, out, what, spans=()):
    """A greyscale video, white where the speaker is: Apple's Vision on a Mac, Google's MediaPipe elsewhere.

    Given spans, only those seconds are worked out: a cutout only matters while a graphic is behind you."""
    frames = ",".join(f"{max(math.floor(a * FPS) - 1, 0)}-{math.ceil(b * FPS) + 1}" for a, b in spans)
    cmd = [str(swift_tool())] if MAC else [sys.executable, str(HOME / "personmask.py")]
    run(cmd + [str(video), str(out)] + ([frames] if frames else []), what)


def transcribe(video, folder, model, lang):
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "speech.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)], "Extracting audio")
    cmd = [*HYPERFRAMES, "transcribe", str(audio), "-d", str(folder), "-m", model]
    if lang:
        cmd += ["-l", lang]
    run(cmd, "Transcribing")
    return [(w["text"].strip(), float(w["start"]), float(w["end"]))
            for w in json.loads((folder / "transcript.json").read_text(encoding="utf-8")) if w["text"].strip()]


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
    return text[0].upper() + text[1:], picked[-1][2]


def head_top(video, seconds, folder):
    """Highest point the speaker's head reaches during the hook, in pixels."""
    import numpy as np
    clip, mask = folder / "hook-part.mp4", folder / "hook-mask.mp4"
    # 10 frames a second is plenty to catch the highest point, at a third of the work.
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-t", f"{seconds:.3f}", "-vf", "fps=10", "-an", "-c:v", "libx264", "-preset", "ultrafast", str(clip)],
        "Reading the hook")
    person_mask(clip, mask, "Finding your head")
    raw = run_bytes(["ffmpeg", "-v", "error", "-i", str(mask), "-vf", "scale=108:192,format=gray", "-f", "rawvideo", "-"])
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 192, 108)
    rows = np.flatnonzero(((frames > 128).sum(axis=2) >= 4).any(axis=0))  # 4 pixels wide, so a stray speck isn't a head
    return int(rows[0]) * 10 if len(rows) else H


def hook_place(text, top):
    """The band above the head, from the app's top bar to the hairline. A tight frame shrinks the card, never lowers it."""
    band = top - 20 - HOOK_TOP
    for size in (54, 48, 42):
        lines = -(-len(text) * size * 0.54 // 840)
        if lines * size * 1.14 + 44 <= band:
            return f"top:{HOOK_TOP}px;max-width:900px;font-size:{size}px"
    return None


def plain(text):
    return re.sub(r"[^\w']", "", text).lower()


def find_word(words, wanted, after=0.0):
    """When the speaker says this word, so a graphic lands on it."""
    for text, start, _end in words:
        if start >= after and plain(text) == plain(wanted):
            return start
    return None


def graphics(words, duration, behind, popups):
    """Turn the words someone picked into timed graphics. A word they never said is skipped with a warning."""
    big, cards, at = [], [], 0.0
    for wanted in behind:
        start = find_word(words, wanted, at)
        if start is None:
            print(f'    Skipped "{wanted}": it isn\'t in the transcript.')
            continue
        big.append((start, wanted.upper()))
        at = start + 0.1
    for wanted, content in popups:
        start = find_word(words, wanted)
        if start is None:
            print(f'    Skipped pop-up "{wanted}": it isn\'t in the transcript.')
        else:
            cards.append((start, content))
    big = [(s, min(s + 1.9, big[i + 1][0] - 0.05 if i + 1 < len(big) else duration), t) for i, (s, t) in enumerate(big)]
    cards.sort(key=lambda c: c[0])
    spots = [(14, 330, -6), (752, 300, 5), (14, 600, 4), (752, 545, -4)]  # beside the head, above the shoulders
    placed = []
    for i, (s, content) in enumerate(cards):
        later = cards[i + 4][0] - 0.05 if i + 4 < len(cards) else duration
        placed.append((s, min(s + 3.2, later, duration), *spots[i % 4], content))
    return big, placed


class Page:
    """One transparent layer of the reel, as an HTML page: its elements, their GSAP timing, and when each is on screen."""

    def __init__(self):
        self.tops, self.js, self.spans, self.files = [], [], [], []

    def add(self, cid, start, end, inner, cls, style=""):
        style = f' style="{style}"' if style else ""
        self.tops.append(f'<div class="{cls}" id="{cid}"{style} data-start="{start:.3f}" data-duration="{end - start:.3f}" '
                         f'data-track-index="{len(self.tops) + 10}">{inner}</div>')
        if start > 0:  # without this a caption is visible from frame 0
            self.js.append(f'tl.set("#{cid}", {{autoAlpha:0}}, 0); tl.set("#{cid}", {{autoAlpha:1}}, {start:.3f});')
        self.js.append(f'tl.set("#{cid}", {{autoAlpha:0}}, {end:.3f});')
        self.spans.append((start, end))

    def write(self, folder, duration):
        folder.mkdir(parents=True)
        (folder / "fonts").mkdir()
        shutil.copy(HOME / "fonts/TikTokSans.ttf", folder / "fonts/TikTokSans.ttf")
        for src, name in self.files:
            shutil.copy(src, folder / name)
        nl = "\n"
        custom = HOME / "custom.css"  # yours to edit: updates never touch it
        css = CSS + (custom.read_text(encoding="utf-8") if custom.exists() else "")
        (folder / "index.html").write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>reel</title><style>{css}</style></head>
<body>
<div id="root" data-composition-id="reel" data-start="0" data-duration="{duration:.3f}" data-width="{W}" data-height="{H}">
{nl.join(self.tops)}
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{nl.join(self.js)}
window.__timelines["reel"] = tl;
</script>
</div>
</body></html>
""", encoding="utf-8")


def composition(words, duration, hook, hook_end, big=(), cards=(), hook_style=None):
    """Two layers: big words and cards go behind the speaker, the hook and captions in front."""
    captions = chunks([w for w in words if w[1] >= hook_end - 0.05])
    front, back = Page(), Page()
    if hook:
        front.add("hook", 0, hook_end, html.escape(hook), "hook", hook_style or "")
    for k, (a, b, text) in enumerate(big):
        n = len(text)
        size = int(min(250, 1000 / n)) if n <= 6 else int(1500 / n)
        half = (n + 1) // 2
        inner = f"<span>{html.escape(text[:half])}</span><span>{html.escape(text[half:])}</span>" if n <= 6 else html.escape(text)
        back.add(f"big{k}", a, b, inner, "big split" if n <= 6 else "big", f"font-size:{size}px")
        back.js.append(f'tl.fromTo("#big{k}", {{scale:.86, y:40}}, {{scale:1, y:0, duration:.26, ease:"back.out(1.5)"}}, {a:.3f});')
        back.js.append(f'tl.to("#big{k}", {{scale:1.04, duration:{max(b - a - .26, .01):.3f}, ease:"none"}}, {a + .26:.3f});')
    for k, (a, b, x, y, rot, content) in enumerate(cards):
        art = Path(content).expanduser()
        if art.is_file():
            name = f"card{k}{art.suffix.lower()}"
            back.files.append((art, name))
            inner = f'<img src="{name}" alt="">'
        else:
            inner = html.escape(content)
        back.add(f"card{k}", a, b, inner, "card", f"left:{x}px;top:{y}px")
        back.js.append(f'tl.fromTo("#card{k}", {{scale:.5, rotation:{rot * 3}, y:70}}, {{scale:1, rotation:{rot}, y:0, duration:.34, ease:"back.out(1.7)"}}, {a:.3f});')
    for k, (text, start) in enumerate(captions):
        end = captions[k + 1][1] if k + 1 < len(captions) else duration
        if end > start:
            front.add(f"cap{k}", start, end, html.escape(text), "cap")
    return front, back, len(captions)


def stills(page, duration, moving, folder, what):
    """Photograph a layer once per change while nothing moves, and every frame while something does.

    Captions only appear and disappear, so a reel needs about 80 stills instead of 2,000 frames from Chrome: the slow
    part on a small laptop. Returns an ffmpeg concat list that plays the stills back frame-exact."""
    marks = sorted({0.0, duration, *(min(max(t, 0.0), duration) for span in page.spans for t in span)})
    shots = []  # (frame to photograph, first frame it covers, frame after the last)
    for a, b in zip(marks, marks[1:]):
        f0, f1 = math.ceil(a * FPS - 1e-6), math.ceil(b * FPS - 1e-6)  # the frames whose time falls in [a, b)
        if f1 <= f0:
            continue
        if any(x < b and a < y for x, y in moving):
            shots += [(f, f, f + 1) for f in range(f0, f1)]
        else:
            shots.append(((f0 + f1 - 1) // 2, f0, f1))
    # Round up to 0.1 ms: still inside the frame, and past any timing mark, which are whole milliseconds.
    times = [f"{math.ceil(f / FPS * 10000) / 10000:.4f}" for f, _a, _b in shots]
    out = run([*HYPERFRAMES, "snapshot", str(folder), "--at", ",".join(times), "--no-end", "--keep", "-o", str(folder / "stills"), "--json"],
              what).stdout
    pictures = [Path(p["path"]) for p in json.loads(out[out.index("{"):])["frames"]]
    if len(pictures) != len(shots):
        raise Stop(f"{what} failed: asked for {len(shots)} stills, got {len(pictures)}.")
    lines = ["ffconcat version 1.0"]
    for picture, (_f, f0, f1) in zip(pictures, shots):
        # Without the frame rate, stills sit on a 1/25 s clock and some captions land a frame late.
        lines += [f"file '{picture.name}'", f"option framerate {FPS}", f"duration {round(f1 * 1e6 / FPS) - round(f0 * 1e6 / FPS)}us"]
    lines += lines[-3:-1]  # the concat format ignores the last entry's duration unless the file is listed again
    listing = folder / "stills/list.txt"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


def read_audio(path, filters="", extra=()):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", *extra, "-i", str(path)] + (["-af", filters] if filters else []) + ["-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    return np.frombuffer(run_bytes(cmd), dtype="<f4").astype(float)


def run_bytes(cmd):
    done = subprocess.run(cmd, capture_output=True)
    if done.returncode:
        raise Stop(f"Reading audio failed.\n{done.stderr.decode(errors='replace')[-500:]}")
    return done.stdout


def mix(speech, out_wav, duration, hook_end, sound_times, music):
    """Voice on top. Music sits at 25% under the hook, then 10%, and dips whenever someone is talking."""
    import numpy as np
    import sfx
    n = int(SR * duration)
    final = np.zeros(n)
    voice = read_audio(speech, "highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=80")[:n]
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
    for t, name, gain in sound_times:
        s = read_audio(HOME / f"sounds/{name}.mp3")
        s = gain * s / max(np.abs(s).max(), 1e-6)
        peak = int(np.convolve(np.abs(s), np.ones(240) / 240, mode="same").argmax())
        i = int(SR * t) - peak  # the loudest moment lands on the frame, not the sound's start
        if i < 0:
            s, i = s[-i:], 0
        final[i:i + len(s)] += s[:max(n - i, 0)]
    final *= 0.89 / max(np.abs(final).max(), 0.89)
    save_wav(out_wav, final, channels=2)


def sound_cues(ranges, hook, hook_end, big=(), cards=()):
    """Real recorded sounds on what appears on screen. Cuts get a quiet whoosh only where nothing else is happening."""
    cues = [(0.0, "pop1", 0.16)] if hook else []
    for k, (a, _b, _text) in enumerate(big):
        cues += [(a, ("whoosh1", "whoosh3")[k % 2], 0.20), (a, "hit1", 0.24)]
    for k, card in enumerate(cards):
        cues += [(card[0], ("paper1", "paper2")[k % 2], 0.24), (card[0], ("pop1", "pop2")[k % 2], 0.14)]
    busy = sorted(c[0] for c in cues)
    at, last = 0.0, hook_end
    for a, b in ranges[:-1]:
        at += b - a
        if at - last >= 3 and all(abs(at - t) >= 1.5 for t in busy):
            cues.append((at, "whoosh2", 0.12))
            last = at
    return cues


def probe_duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], "Reading the video").stdout)


def export(video, audio, layers, mask, out, graph):
    """Stack the layers in one pass: video, graphics behind you, you cut out on top of them, then hook and captions."""
    inputs = ["-i", str(video), "-i", str(audio)]
    parts, base = [], "[0:v]"

    def add_input(*flags):
        inputs.extend(flags)
        return inputs.count("-i") - 1

    if mask:
        parts.append("[0:v]split[base][p]")
        base = "[base]"
    for name in ("back", "front"):
        if name not in layers:
            continue
        if name == "front" and mask:
            # The erode/dilate pass drops thin room objects, like a mic arm, from the cutout. At a third of the size it
            # does the same job about six times faster.
            k = add_input("-i", str(mask))
            clean = "erosion," * 3 + "dilation," * 3
            parts.append(f"[{k}:v]format=gray,scale={W // 3}:{H // 3},{clean}scale={W}:{H}:flags=bicubic,gblur=sigma=1.2,"
                         f"curves=all='0/0 0.25/0 0.7/1 1/1'[a]")
            parts += ["[p][a]alphamerge[person]", f"{base}[person]overlay=format=auto[withyou]"]
            base = "[withyou]"
        k = add_input("-f", "concat", "-safe", "0", "-i", str(layers[name]))
        parts.append(f"[{k}:v]fps={FPS},format=rgba[{name}]")
        parts.append(f"{base}[{name}]overlay=format=auto:eof_action=pass[{name}on]")
        base = f"[{name}on]"
    parts.append(f"{base}format=yuv420p[v]")
    graph.write_text(";\n".join(parts), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-/filter_complex", str(graph), "-map", "[v]", "-map", "1:a", "-map_metadata", "-1",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-af", "loudnorm=I=-15:TP=-1.5:LRA=9",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", "-shortest", str(out)], "Exporting")


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

    print(f"1/5 Cutting the pauses from {src.name} ({meta['duration']:.0f}s)")
    if meta["w"] > meta["h"]:
        print("    Landscape video: cropping the centre to vertical. Use --crop-x 0 (left) to 1 (right) if you're off-centre.")
    original = job / "original.wav"
    sound = source_audio(src, meta, original)
    manual = [tuple(float(x) for x in c.split("-")) for c in args.cut]
    silences = [] if args.no_cuts else find_silences(original, sound, args.noise, args.gap)
    ranges = keep_ranges(meta["duration"], silences, manual)
    if not ranges:
        raise Stop("Everything was detected as silence. Try --noise -45, or --no-cuts.")
    cut_video, speech = job / "cut.mp4", job / "speech.wav"
    prepare(src, cut_video, meta, args.crop_x, ranges)
    cut_audio(sound, ranges, speech)
    duration = min(sum(b - a for a, b in ranges), probe_duration(cut_video))
    print(f"    {meta['duration']:.1f}s down to {duration:.1f}s, {len(ranges) - 1} cuts")

    print("2/5 Transcribing on this computer (the first run downloads a speech model, about 500 MB)")
    words = transcribe(speech, job / "t", args.model, args.lang)
    if not words or is_phantom(words):
        raise Stop("No speech was found in this video. Auto Edit is for videos where someone is talking.")
    words = fix_words(words, [f.split("=", 1) for f in args.fix if "=" in f])

    popups = [p.split("=", 1) for p in args.popup if "=" in p]
    behind = [w.strip() for w in ",".join(args.behind).split(",") if w.strip()]
    big, cards = graphics(words, duration, behind, popups)
    mask = None
    if args.behind or args.popup:
        if not big and not cards:
            raise Stop("None of the words you picked for graphics are in the video. Run `autoedit transcript` to see the words.")
        print("    Cutting you out of the background for the graphics")
        mask = job / "mask.mp4"
        person_mask(cut_video, mask, "Cutting you out of the background", [(g[0], g[1]) for g in big + cards])

    if args.no_hook or (mask and not args.hook):  # big words already do the hook's job; two would fight
        hook, hook_end = None, 0
    else:
        hook, hook_end = first_sentence(words)
        if args.hook:
            hook, hook_end = args.hook, min(max(hook_end, 2.5), 6)
    hook_style = None
    if hook:
        hook_style = hook_place(hook, head_top(cut_video, hook_end, job))
        if not hook_style:
            print("    No room above your head for the hook, so it sits on your chest. Leave more headroom when filming to put it on top.")
    print("3/5 Drawing hook and captions" + (f'\n    Hook: "{hook}"' if hook else ""))
    front, back, count = composition(words, duration, hook, hook_end, big, cards, hook_style)
    front.write(job / "front", duration)
    layers = {"front": stills(front, duration, (), job / "front", "Drawing the captions")}
    if back.spans:
        back.write(job / "back", duration)
        layers["back"] = stills(back, duration, back.spans, job / "back", "Drawing the graphics")

    print("4/5 Mixing sound")
    audio = job / "audio.wav"
    cues = sound_cues(ranges, hook, hook_end, big, cards) if args.sfx else []
    music = str(Path(args.music).expanduser()) if args.music and args.music != "bed" else args.music
    mix(speech, audio, duration, hook_end, cues, music)

    print("5/5 Exporting")
    out.parent.mkdir(parents=True, exist_ok=True)
    export(cut_video, audio, layers, mask, out, job / "export.filter")
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

    def has_mediapipe():
        try:
            import mediapipe  # noqa: F401
            return MASK_MODEL.exists()
        except ImportError:
            return False

    def fix(mac):
        return mac if MAC else "re-run the installer"

    check("ffmpeg", bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")), fix("brew install ffmpeg"))
    check("voice detector", bool(shutil.which("whisper-vad-speech-segments")) and (HOME / "models/ggml-silero-v5.1.2.bin").exists(),
          fix("brew install whisper-cpp, then re-run the installer"))
    check("Node", bool(shutil.which("node")), fix("brew install node"))
    check("HyperFrames", HF_LOCAL.exists() or bool(shutil.which("hyperframes")), f"cd {HOME} && npm install")
    check("numpy", has_numpy(), "re-run the installer")
    if MAC:
        check("Apple developer tools (for finding your head)", subprocess.run(["xcode-select", "-p"], capture_output=True).returncode == 0,
              "xcode-select --install")
    else:
        check("MediaPipe (for finding your head)", has_mediapipe(), "re-run the installer")
    check("sound effects", (HOME / "sounds/hit1.mp3").exists(), "re-run the installer")
    check("caption font", (HOME / "fonts/TikTokSans.ttf").exists(), "re-run the installer")
    print(f"Free disk space: {shutil.disk_usage(Path.home()).free // 1024 ** 3} GB (keep at least 5 GB free)")
    if shutil.which("node") and (HF_LOCAL.exists() or shutil.which("hyperframes")):
        print("\nHyperFrames' own check:")
        subprocess.run([*HYPERFRAMES, "doctor"])
    print("\nReady." if ok else "\nFix the lines marked NO, then run this again.")
    return ok


def ask(question):
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def dragged_path(raw):
    """Mac Terminal escapes dragged paths; Windows wraps them in quotes (PowerShell adds "& "); someone typing one might do neither."""
    if Path(raw).expanduser().exists():
        return raw
    if WINDOWS:
        return re.sub(r"^&\s*", "", raw).strip().strip("\"'")  # shlex would eat the backslashes in a Windows path
    try:
        parts = shlex.split(raw)
    except ValueError:
        return raw
    return parts[0] if len(parts) == 1 else raw


def wizard(video=None):
    """Double-click mode: a few questions, nothing else. On Windows a video dropped on the icon arrives as `video`."""
    print("Auto Edit\n")
    raw = video or input("Drag your video into this window, then press Enter: ").strip()
    if not raw:
        raise Stop("No video given.")
    argv = [dragged_path(raw)]
    if video:
        print(f"Video: {argv[0]}")
    print("\nWhich style?\n  1. Clean: cuts, hook and captions\n  2. Behind you: big words behind your head, plus the captions")
    if input("Type 1 or 2 [1]: ").strip() == "2":
        picked = input("Which words do you say that should appear big? Separate with commas, 2 to 5 is plenty: ").strip()
        if picked:
            argv += ["--behind", picked]
    else:
        hook = input("Type your hook, or press Enter to use your first sentence: ").strip()
        if hook:
            argv += ["--hook", hook]
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
    elif argv[:1] == ["ask"]:  # the Windows desktop shortcut, with any video dropped on it
        argv = wizard(argv[1] if len(argv) > 1 else None)
    elif not argv:
        argv = wizard()
    p = argparse.ArgumentParser(prog="autoedit", description=__doc__,
                                epilog="Other commands: autoedit doctor, autoedit transcript VIDEO, autoedit ask [VIDEO]")
    p.add_argument("video")
    p.add_argument("--sfx", action="store_true", help="add sound effects")
    p.add_argument("--music", metavar="FILE", help="music file you have the rights to, or 'bed' for the built-in beat")
    p.add_argument("--hook", help="your own hook text (default: the first sentence, if it's short)")
    p.add_argument("--no-hook", action="store_true", help="captions only")
    p.add_argument("--no-cuts", action="store_true", help="keep the pauses")
    p.add_argument("--behind", action="append", default=[], metavar="WORDS", help="words to show big behind you when you say them, comma-separated, e.g. \"fear,lazy\"")
    p.add_argument("--popup", action="append", default=[], metavar="WORD=CONTENT", help="pop-up card behind you when you say WORD. CONTENT is short text or an image file")
    p.add_argument("--cut", action="append", default=[], metavar="START-END", help="also remove this part, in seconds of the original, e.g. 12.3-14.1")
    p.add_argument("--fix", action="append", default=[], metavar="WRONG=RIGHT", help="correct a misheard word in captions")
    p.add_argument("--gap", type=float, default=0.3, help="shortest pause to remove, seconds")
    p.add_argument("--noise", type=float, help="what counts as silence, in dB (default: 11 dB under your speaking level; try -45 if words get clipped)")
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
