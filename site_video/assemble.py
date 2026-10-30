"""Timing, the captions' places, the soundtrack, and the plain ffmpeg edit (for anyone without DaVinci Resolve).

Every segment (the opening cards, each scene, the closing card) is a clip of an exact number of frames plus HANDLE
spare frames at each end, and its narration sits a fixed lead-in after the segment starts, so one mixed WAV covers the
whole video in sync. Cuts get a DISSOLVE centered on them (the handles supply the overlap), so they do not move.
"""

import os
from typing import Dict, List, Optional

from .util import DISSOLVE, FPS, HANDLE, RATE, ffmpeg, frames, silence

LEAD, TAIL = 0.5, 0.6          # quiet time at the start and end of each scene's narration
VOICE_AT = {"intro": 0.7, "scene": LEAD, "outro": 0.7}
TITLE_S, PROBLEM_S = 4.5, 5.5   # the opening: the title card, then the problem card when there is one
CAPTION_IN, CAPTION_FADE = 0.5, 8 / 30


def opening(plan: Dict) -> bool:
    """Whether the opening has a problem card after the title."""
    return bool((plan.get("problem") or {}).get("statement"))


def durations(plan: Dict, voice_secs: List[float]) -> List[float]:
    """Seconds per segment, rounded to whole frames: long enough for the plan and for the narration."""
    n = len(plan["scenes"])
    out = [max(TITLE_S + (PROBLEM_S if opening(plan) else 0), voice_secs[0] + VOICE_AT["intro"] + 0.8)]
    for i, s in enumerate(plan["scenes"]):
        out.append(max(float(s["seconds"]), voice_secs[i + 1] + LEAD + TAIL + 0.3))
    out.append(max(5.0, voice_secs[n + 1] + VOICE_AT["outro"] + 1.2))
    return [frames(d) / FPS for d in out]


UNDER_VOICE = 0.18     # a video's own sound, under the narrator


def soundtrack(work: str, voice_wavs: List[Optional[str]], secs: List[float], music: Optional[str], out: str,
               own: Optional[List[Optional[str]]] = None) -> None:
    """One WAV for the whole video: each segment's narration at its lead-in, music under it if given. `own` holds,
    per segment, the sound of the owner's video it shows (or None): at full level alone, quietly under narration."""
    own = own or [None] * len(secs)
    parts = []
    for i, (wav, d) in enumerate(zip(voice_wavs, secs)):
        seg = os.path.join(work, f"aseg_{i:03d}.wav")
        kind = "intro" if i == 0 else "outro" if i == len(secs) - 1 else "scene"
        talk = bool(wav and os.path.exists(wav))
        clip = own[i] if i < len(own) and own[i] and os.path.exists(own[i]) else None
        ms = int(VOICE_AT[kind] * 1000)
        if talk and clip:
            ffmpeg("-i", wav, "-i", clip, "-filter_complex",
                   f"[0:a]adelay={ms}|{ms},apad[v];[1:a]volume={UNDER_VOICE},apad[c];"
                   "[v][c]amix=inputs=2:duration=longest:normalize=0[a]",
                   "-map", "[a]", "-t", f"{d:.4f}", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", seg)
        elif clip:
            ffmpeg("-i", clip, "-af", "apad", "-t", f"{d:.4f}", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", seg)
        elif talk:
            ffmpeg("-i", wav, "-af", f"adelay={ms}|{ms},apad", "-t", f"{d:.4f}", "-ar", str(RATE), "-ac", "2",
                   "-c:a", "pcm_s16le", seg)
        else:
            silence(seg, d)
        parts.append(seg)
    lst = os.path.join(work, "aseg.txt")
    with open(lst, "w") as f:
        f.write("".join(f"file '{p}'\n" for p in parts))
    voice = os.path.join(work, "voice_full.wav")
    ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", voice)
    total = sum(secs)
    if music:
        fade = max(0.0, total - 3.0)
        graph = ("[0:a]asplit=2[v1][v2];[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.30[m];"
                 "[m][v1]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450[d];"
                 f"[d]afade=t=in:d=1.5,afade=t=out:st={fade:.2f}:d=3[mm];"
                 "[v2][mm]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]")
        ffmpeg("-i", voice, "-stream_loop", "-1", "-i", music, "-filter_complex", graph, "-map", "[out]",
               "-t", f"{total:.4f}", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", out)
    else:
        ffmpeg("-i", voice, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-t", f"{total:.4f}", "-ar", str(RATE),
               "-ac", "2", "-c:a", "pcm_s16le", out)
    for p in parts:
        os.unlink(p)


def caption_times(plan: Dict, secs: List[float]) -> List[Dict]:
    """Where each scene's captions sit: [{"scene", "n", "text", "start", "end"}] in seconds of the finished video.
    One caption spans its scene less half a second each side, inside the cuts; two share it."""
    out, t = [], secs[0]
    for i, s in enumerate(plan["scenes"]):
        d = secs[i + 1]
        caps = [c for c in (s.get("captions") or [s.get("caption") or ""]) if c][:2]
        if len(caps) == 2 and d < 7:
            caps = caps[:1]
        span = (d - 2 * CAPTION_IN) / max(1, len(caps))
        for k, c in enumerate(caps):
            a = t + CAPTION_IN + k * span + (0.2 if k else 0)
            b = t + CAPTION_IN + (k + 1) * span - (0.2 if k < len(caps) - 1 else 0)
            if b - a >= 1.2:
                out.append({"scene": i, "n": k, "text": c, "start": round(a, 3), "end": round(b, 3)})
        t += d
    return out


def edit_ffmpeg(work: str, clips: List[str], mix: str, out: str, secs: List[float] = (),
                captions: List[Dict] = ()) -> str:
    """The same edit as in Resolve: the clips with a dissolve centered on each cut (from their handles), the caption
    PNGs over them with short fades, a fade to black at the end, and the soundtrack."""
    n = [frames(d) for d in secs] if secs else None
    if not n:
        raise ValueError("segment lengths are needed for the edit")
    half, k = DISSOLVE // 2, len(clips)
    args, graph, lens = [], [], []
    for i, c in enumerate(clips):
        a = HANDLE - (half if i > 0 else 0)
        b = HANDLE + n[i] + (half if i < k - 1 else 0)
        args += ["-i", c]
        graph.append(f"[{i}:v]trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,fps={FPS}[v{i}]")
        lens.append(b - a)
    acc, last = lens[0], "v0"
    for i in range(1, k):
        graph.append(f"[{last}][v{i}]xfade=transition=fade:duration={DISSOLVE / FPS:.4f}:offset={(acc - DISSOLVE) / FPS:.4f}[x{i}]")
        acc += lens[i] - DISSOLVE
        last = f"x{i}"
    total = sum(n)
    graph.append(f"[{last}]fade=t=out:st={(total - 24) / FPS:.4f}:d={24 / FPS:.4f},format=yuv420p[base]")
    last = "base"
    for j, cap in enumerate(captions):
        idx = k + j
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total / FPS:.3f}", "-i", cap["png"]]
        s0, s1 = cap["start"], cap["end"]
        graph.append(f"[{idx}:v]format=rgba,fade=t=in:st={s0:.3f}:d={CAPTION_FADE:.3f}:alpha=1,"
                     f"fade=t=out:st={s1 - CAPTION_FADE:.3f}:d={CAPTION_FADE:.3f}:alpha=1[c{j}]")
        graph.append(f"[{last}][c{j}]overlay=0:0:enable='between(t,{s0:.3f},{s1:.3f})'[o{j}]")
        last = f"o{j}"
    args += ["-i", mix]
    script = os.path.join(work, "edit_graph.txt")
    with open(script, "w") as f:
        f.write(";\n".join(graph))
    ffmpeg(*args, "-filter_complex_script", script, "-map", f"[{last}]", "-map", f"{k + len(captions)}:a",
           "-frames:v", str(total), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out)
    return out
