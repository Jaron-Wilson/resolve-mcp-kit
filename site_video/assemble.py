"""Timing, the soundtrack, and the plain ffmpeg edit (for anyone without DaVinci Resolve).

Every segment (intro card, each scene, outro card) is a clip of an exact number of frames, and its narration sits a
fixed lead-in after the clip starts, so one mixed WAV covers the whole video in sync.
"""

import os
from typing import Dict, List, Optional

from .record import LEAD, TAIL
from .util import FPS, RATE, ffmpeg, frames, silence

VOICE_AT = {"intro": 0.7, "scene": LEAD, "outro": 0.7}


def durations(plan: Dict, voice_secs: List[float]) -> List[float]:
    """Seconds per segment, rounded to whole frames: long enough for the plan and for the narration."""
    n = len(plan["scenes"])
    out = [max(4.0, voice_secs[0] + VOICE_AT["intro"] + 0.8)]
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


def edit_ffmpeg(work: str, clips: List[str], mix: str, out: str) -> str:
    """Join the clips (all the same format, so no re-encode) and add the soundtrack."""
    lst = os.path.join(work, "clips.txt")
    with open(lst, "w") as f:
        f.write("".join(f"file '{c}'\n" for c in clips))
    ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-i", mix, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out)
    return out
