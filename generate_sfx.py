"""Generate 10 SFX .wav files for the timeline editor."""
import math
import os
import random
import struct
import wave

SAMPLE_RATE = 44100

def write_wav(path, samples, sr=SAMPLE_RATE):
    """Write float samples [-1,1] to a 16-bit WAV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        for s in samples:
            s = max(-1.0, min(1.0, s))
            f.writeframes(struct.pack('<h', int(s * 32767)))
    print(f"  Created {path} ({len(samples)/sr:.2f}s)")

def envelope(n, attack=0.01, decay=0.0, sustain=1.0, release=0.1, sr=SAMPLE_RATE):
    """Generate an ADSR envelope."""
    env = []
    a_samples = int(attack * sr)
    d_samples = int(decay * sr)
    r_samples = int(release * sr)
    s_samples = max(0, n - a_samples - d_samples - r_samples)
    for i in range(a_samples):
        env.append(i / max(1, a_samples))
    for i in range(d_samples):
        env.append(1.0 - (1.0 - sustain) * (i / max(1, d_samples)))
    for i in range(s_samples):
        env.append(sustain)
    for i in range(r_samples):
        env.append(sustain * (1.0 - i / max(1, r_samples)))
    while len(env) < n:
        env.append(0)
    return env[:n]

def sine(freq, duration, volume=1.0):
    n = int(duration * SAMPLE_RATE)
    return [volume * math.sin(2 * math.pi * freq * i / SAMPLE_RATE) for i in range(n)]

def noise(duration, volume=1.0):
    n = int(duration * SAMPLE_RATE)
    return [volume * (random.random() * 2 - 1) for _ in range(n)]

def mix(*tracks):
    length = max(len(t) for t in tracks)
    result = [0.0] * length
    for t in tracks:
        for i in range(len(t)):
            result[i] += t[i]
    peak = max(abs(s) for s in result) or 1
    return [s / peak for s in result]

def apply_env(samples, env):
    return [s * e for s, e in zip(samples, env)]

# ── 1. Emphasis: Vine Boom ──
def gen_vine_boom():
    dur = 0.8
    n = int(dur * SAMPLE_RATE)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        # Sub-bass that drops in frequency
        freq = 80 * math.exp(-t * 3)
        s = math.sin(2 * math.pi * freq * t)
        # Add harmonic
        s += 0.5 * math.sin(2 * math.pi * freq * 2 * t)
        # Distortion
        s = math.tanh(s * 2)
        samples.append(s)
    env = envelope(n, attack=0.005, decay=0.1, sustain=0.6, release=0.5)
    return apply_env(samples, env)

# ── 2. Emphasis: Bass Drop ──
def gen_bass_drop():
    dur = 1.2
    n = int(dur * SAMPLE_RATE)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 200 * math.exp(-t * 2) + 30
        s = math.sin(2 * math.pi * freq * t)
        s += 0.4 * math.sin(2 * math.pi * freq * 0.5 * t)
        s = math.tanh(s * 1.5)
        samples.append(s)
    env = envelope(n, attack=0.01, decay=0.2, sustain=0.5, release=0.7)
    return apply_env(samples, env)

# ── 3. Emphasis: Metal Clang ──
def gen_metal_clang():
    dur = 0.6
    n = int(dur * SAMPLE_RATE)
    freqs = [800, 1340, 2100, 3200, 4500]
    tracks = []
    for f in freqs:
        t_samples = []
        for i in range(n):
            t = i / SAMPLE_RATE
            s = math.sin(2 * math.pi * f * t + random.random() * 0.1)
            s *= math.exp(-t * (4 + f / 1000))
            t_samples.append(s)
        tracks.append(t_samples)
    result = mix(*tracks)
    env = envelope(n, attack=0.001, decay=0.05, sustain=0.3, release=0.4)
    return apply_env(result, env)

# ── 4. Humor: Comedy Ding ──
def gen_comedy_ding():
    dur = 0.5
    n = int(dur * SAMPLE_RATE)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        s = math.sin(2 * math.pi * 2400 * t)
        s += 0.5 * math.sin(2 * math.pi * 3600 * t)
        s *= math.exp(-t * 6)
        samples.append(s)
    env = envelope(n, attack=0.001, decay=0.05, sustain=0.2, release=0.3)
    return apply_env(samples, env)

# ── 5. Humor: Record Scratch ──
def gen_record_scratch():
    dur = 0.4
    n = int(dur * SAMPLE_RATE)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        # Filtered noise with pitch sweep
        freq = 300 + 2000 * (1 - t / dur)
        s = (random.random() * 2 - 1)
        s *= math.sin(2 * math.pi * freq * t)
        samples.append(s)
    env = envelope(n, attack=0.005, decay=0.05, sustain=0.7, release=0.15)
    return apply_env(samples, env)

# ── 6. Humor: Sad Trombone ──
def gen_sad_trombone():
    dur = 1.5
    n = int(dur * SAMPLE_RATE)
    # Four descending notes: Bb4 F4 D4 Bb3
    notes = [(466, 0.35), (349, 0.35), (294, 0.35), (233, 0.55)]
    samples = [0.0] * n
    pos = 0
    for freq, note_dur in notes:
        nn = int(note_dur * SAMPLE_RATE)
        for i in range(nn):
            if pos + i >= n:
                break
            t = i / SAMPLE_RATE
            s = math.sin(2 * math.pi * freq * t)
            s += 0.3 * math.sin(2 * math.pi * freq * 2 * t)
            s += 0.15 * math.sin(2 * math.pi * freq * 3 * t)
            # Vibrato
            s *= 1 + 0.02 * math.sin(2 * math.pi * 5 * t)
            e = min(1.0, i / (0.02 * SAMPLE_RATE)) * max(0, 1 - (i - nn * 0.7) / (nn * 0.3)) if i > nn * 0.7 else min(1.0, i / (0.02 * SAMPLE_RATE))
            samples[pos + i] = s * e * 0.7
        pos += nn
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]

# ── 7. Shock: Deep Boom ──
def gen_deep_boom():
    dur = 1.5
    n = int(dur * SAMPLE_RATE)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 40 * math.exp(-t * 1.5) + 20
        s = math.sin(2 * math.pi * freq * t)
        s += 0.7 * math.sin(2 * math.pi * freq * 0.5 * t)
        s += 0.3 * (random.random() * 2 - 1) * math.exp(-t * 4)
        s = math.tanh(s * 2.5)
        samples.append(s)
    env = envelope(n, attack=0.005, decay=0.3, sustain=0.4, release=0.9)
    return apply_env(samples, env)

# ── 8. Shock: Dramatic Hit ──
def gen_dramatic_hit():
    dur = 1.0
    n = int(dur * SAMPLE_RATE)
    # Orchestra hit = many frequencies at once
    freqs = [130, 165, 196, 262, 330, 392, 523, 660, 784]
    tracks = []
    for f in freqs:
        t_samples = []
        for i in range(n):
            t = i / SAMPLE_RATE
            s = math.sin(2 * math.pi * f * t)
            s *= math.exp(-t * 2)
            t_samples.append(s * 0.5)
        tracks.append(t_samples)
    # Add noise burst
    noise_track = []
    for i in range(n):
        t = i / SAMPLE_RATE
        noise_track.append((random.random() * 2 - 1) * 0.4 * math.exp(-t * 8))
    tracks.append(noise_track)
    result = mix(*tracks)
    env = envelope(n, attack=0.003, decay=0.1, sustain=0.3, release=0.6)
    return apply_env(result, env)

# ── 9. Transition: Riser ──
def gen_riser():
    dur = 1.5
    n = int(dur * SAMPLE_RATE)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        progress = t / dur
        freq = 200 * math.exp(progress * 3)
        s = math.sin(2 * math.pi * freq * t)
        s += 0.3 * (random.random() * 2 - 1) * progress
        samples.append(s * progress)
    env = envelope(n, attack=1.2, decay=0.0, sustain=1.0, release=0.1)
    return apply_env(samples, env)

# ── 10. Transition: Whoosh ──
def gen_whoosh():
    dur = 0.5
    n = int(dur * SAMPLE_RATE)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        progress = t / dur
        s = (random.random() * 2 - 1)
        # Bandpass sweep
        center = 500 + 4000 * math.sin(progress * math.pi)
        s *= math.sin(2 * math.pi * center * t)
        bell = math.sin(progress * math.pi)
        samples.append(s * bell)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]

# ── Generate all ──
def main():
    sfx_dir = os.path.join(os.path.dirname(__file__), "assets", "sfx")
    print("Generating SFX files...\n")

    generators = {
        "emphasis/vine-boom":     gen_vine_boom,
        "emphasis/bass-drop":     gen_bass_drop,
        "emphasis/metal-clang":   gen_metal_clang,
        "humor/comedy-ding":      gen_comedy_ding,
        "humor/record-scratch":   gen_record_scratch,
        "humor/sad-trombone":     gen_sad_trombone,
        "shock/deep-boom":        gen_deep_boom,
        "shock/dramatic-hit":     gen_dramatic_hit,
        "transition/riser":       gen_riser,
        "transition/whoosh":      gen_whoosh,
    }

    for name, gen_fn in generators.items():
        path = os.path.join(sfx_dir, name + ".wav")
        samples = gen_fn()
        write_wav(path, samples)

    print(f"\nDone! {len(generators)} SFX files generated in {sfx_dir}")

if __name__ == "__main__":
    main()
