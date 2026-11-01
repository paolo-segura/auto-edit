#!/usr/bin/env python3
"""Original SFX and a music bed, synthesized in code. No samples, so nothing to license."""
import numpy as np

SR = 48000
_rng = np.random.default_rng(7)


def _env(n, attack=0.002, release=None):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    r = np.exp(-t / release) if release else np.ones(n)
    return a * r


def _noise(n):
    return _rng.standard_normal(n)


def _bandpass(x, lo, hi):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def whoosh(dur=0.32, gain=0.5):
    n = int(SR * dur)
    x = _noise(n)
    out = np.zeros(n)
    seg = 512  # swept band: low -> high -> low, the "air past the mic" shape
    for i in range(0, n, seg):
        p = i / n
        c = 300 + 3200 * np.sin(np.pi * p)
        out[i:i + seg] = _bandpass(x[i:i + seg], c * 0.6, c * 1.6)[: len(out[i:i + seg])]
    shape = np.sin(np.pi * np.linspace(0, 1, n)) ** 1.6
    return gain * out * shape / (np.abs(out).max() + 1e-9)


def key(gain=0.28):
    n = int(SR * 0.035)
    click = _bandpass(_noise(n), 1800, 7000) * _env(n, 0.0005, 0.006)
    body = np.sin(2 * np.pi * _rng.uniform(170, 240) * np.arange(n) / SR) * _env(n, 0.001, 0.012) * 0.5
    x = click / (np.abs(click).max() + 1e-9) + body
    return gain * _rng.uniform(0.8, 1.1) * x / np.abs(x).max()


def enter(gain=0.36):
    return np.concatenate([key(gain * 1.1), np.zeros(int(SR * 0.012))]) + 0


def pop(freq=660, gain=0.35):
    n = int(SR * 0.16)
    t = np.arange(n) / SR
    f = freq * (1 + 0.6 * np.exp(-t / 0.01))  # quick downward chirp
    return gain * np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.001, 0.035)


def ding(freq=1046.5, gain=0.3):
    n = int(SR * 0.9)
    t = np.arange(n) / SR
    x = sum(a * np.sin(2 * np.pi * freq * m * t) for m, a in [(1, 1), (2.01, .35), (3.02, .12)])
    return gain * x * _env(n, 0.002, 0.25) / 1.47


def beep(gain=0.22):
    n = int(SR * 0.07)
    b = np.sin(2 * np.pi * 2700 * np.arange(n) / SR) * _env(n, 0.002, 0.05)
    gap = np.zeros(int(SR * 0.06))
    return gain * np.concatenate([b, gap, b])


def tick(gain=0.3):
    n = int(SR * 0.02)
    return gain * _bandpass(_noise(n), 2500, 9000) * _env(n, 0.0003, 0.003) / 0.5


def thump(gain=0.55):
    n = int(SR * 0.45)
    t = np.arange(n) / SR
    f = 55 + 70 * np.exp(-t / 0.04)
    return gain * np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.12)


KINDS = {"whoosh": whoosh, "whoosh_soft": lambda: whoosh(0.5, 0.25), "key": key, "enter": enter, "pop": pop,
         "pop_hi": lambda: pop(990), "ding": ding, "beep": beep, "tick": tick, "thump": thump}


def music_bed(duration, bpm=100, gain=0.16, seed=3):
    """Original synthesized bed: warm minor-ish pad + soft kick + offbeat hat, 'electric pulse' feel. No samples."""
    rng = np.random.default_rng(seed)
    n = int(SR * duration); t = np.arange(n) / SR
    beat = 60 / bpm
    out = np.zeros(n)
    chords = [(220.0, 261.6, 329.6), (196.0, 246.9, 293.7), (174.6, 220.0, 261.6), (196.0, 246.9, 329.6)]  # Am C E / G B D / F A C / G B E
    bar = beat * 4
    for k in range(int(duration / bar) + 1):
        s, e = int(SR * k * bar), min(n, int(SR * (k + 1) * bar))
        if s >= n: break
        tt = t[s:e] - k * bar
        pad = sum(np.sin(2 * np.pi * f * tt + 0.3 * np.sin(2 * np.pi * 0.4 * tt)) +
                  0.4 * np.sin(2 * np.pi * f * 2.003 * tt) for f in chords[k % 4])
        fade = np.clip(tt / 0.3, 0, 1) * np.clip((bar - tt) / 0.3, 0, 1)
        out[s:e] += 0.18 * pad * fade
        # pulsing low note on 8ths: the "current"
        root = chords[k % 4][0] / 2
        gate = (np.sin(2 * np.pi * (2 / beat) * tt) > 0).astype(float)
        out[s:e] += 0.22 * np.sin(2 * np.pi * root * tt) * (0.35 + 0.65 * gate) * fade
    for i in range(int(duration / beat) + 1):
        s = int(SR * i * beat)
        if s >= n: break
        k = thump(0.9)[: n - s]; out[s:s + len(k)] += k * 0.9
        h0 = int(SR * (i + 0.5) * beat)
        if h0 < n:
            hn = min(int(SR * 0.04), n - h0)
            out[h0:h0 + hn] += 0.12 * _bandpass(rng.standard_normal(hn), 6000, 14000) * _env(hn, 0.0005, 0.01)
    out *= np.clip(t / 1.0, 0, 1) * np.clip((duration - t) / 1.5, 0, 1)  # fade in/out
    return gain * out / (np.abs(out).max() + 1e-9)


def _lowpass(x, hz):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / hz) ** 4)
    return np.fft.irfft(X, len(x))


def slice_(gain=0.35):
    """Fast airy swipe for a knife cut: short rising band of noise."""
    n = int(SR * 0.22); x = _noise(n); out = np.zeros(n); seg = 256
    for i in range(0, n, seg):
        c = 900 + 4200 * (i / n)
        out[i:i + seg] = _bandpass(x[i:i + seg], c * .7, c * 1.4)[: len(out[i:i + seg])]
    return gain * _lowpass(out, 6000) * np.sin(np.pi * np.linspace(0, 1, n)) ** 2 / (np.abs(out).max() + 1e-9)


def wood(freq=1250, gain=0.16):
    """Soft woodblock tick for the timer (warm, not a beep)."""
    n = int(SR * 0.07); t = np.arange(n) / SR
    x = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 1.48 * t)
    return gain * x * _env(n, 0.0008, 0.012) / 1.5


def boom(gain=0.5):
    """Soft low impact for word slams: thump with a little body, no click."""
    n = int(SR * 0.6); t = np.arange(n) / SR
    f = 48 + 40 * np.exp(-t / 0.05)
    return gain * _lowpass(np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.004, 0.18), 400)


def riser(dur=1.2, gain=0.18):
    n = int(SR * dur); x = _noise(n); out = np.zeros(n); seg = 512
    for i in range(0, n, seg):
        c = 300 + 2600 * (i / n) ** 2
        out[i:i + seg] = _bandpass(x[i:i + seg], c * .8, c * 1.25)[: len(out[i:i + seg])]
    return gain * _lowpass(out, 5000) * np.linspace(0, 1, n) ** 2 / (np.abs(out).max() + 1e-9)


def soft_whoosh():
    return _lowpass(whoosh(0.3, 0.32), 5000)


def soft_pop(freq=520):
    return pop(freq, 0.26)


def chime(gain=0.2):
    return _lowpass(ding(784, gain), 5000)


KINDS.update({"slice": slice_, "wood": wood, "boom": boom, "riser": riser, "soft_whoosh": soft_whoosh,
              "soft_pop": soft_pop, "chime": chime, "soft_beep": lambda: _lowpass(beep(0.12), 3000)})
