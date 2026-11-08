"""MoviePy assembly: PNG scenes + TTS voiceover + procedural music -> MP4.

Scene timing is audio-driven: every scene lasts exactly
LEAD + narration + TAIL seconds, so on-screen text and voice stay in sync.
"""

from __future__ import annotations

from pathlib import Path

from moviepy import (AudioFileClip, CompositeAudioClip, CompositeVideoClip,
                     ImageClip, afx, vfx)

from . import config as C
from . import frames, music, tts


def render_episode(episode: dict, brand_pill: str, out_dir: Path) -> dict:
    """Render one episode to out_dir/{slug}.mp4 + cover.jpg.

    episode: {n, hook{saying,text}, tips[3]{title,body,chip,saying}, cta{...}, voice, handle}
    Returns metadata {video, cover, duration, size}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(exist_ok=True)
    voice = episode.get("voice") or C.DEFAULT_VOICE
    handle = episode.get("handle") or "@yourhandle"
    slug = f"tip-{episode['n']:03d}"

    # ------------------------------------------------ 1. narration per scene
    segments = [("hook", episode["hook"])] + \
               [(f"tip{i+1}", t) for i, t in enumerate(episode["tips"])] + \
               [("cta", episode["cta"])]

    audio_paths, audio_durs = {}, {}
    for name, seg in segments:
        p = work / f"{name}.mp3"
        tts.synth(seg.get("saying") or seg["text"], p, voice)
        audio_paths[name] = p
        audio_durs[name] = tts.duration(p)

    # ------------------------------------------------ 2. still frames
    scene_imgs = {
        "hook": frames.hook_frame(episode, brand_pill, handle),
    }
    for i, tip in enumerate(episode["tips"]):
        scene_imgs[f"tip{i+1}"] = frames.tip_frame(i + 1, tip, episode, handle)
    scene_imgs["cta"] = frames.cta_frame(episode, brand_pill, handle)

    # cover = hook frame, labelled with the tip number
    cover_img = frames.hook_frame(episode, brand_pill, handle, cover=True)

    # ------------------------------------------------ 3. scene durations
    kinds = ["hook", "tip", "tip", "tip", "cta"]
    durs = []
    for name, kind in zip(audio_paths.keys(), kinds):
        durs.append(C.LEAD[kind] + audio_durs[name] + C.TAIL[kind])
    total = sum(durs) - C.XF * (len(durs) - 1)

    # ------------------------------------------------ 4. video composite
    # NOTE: CrossFadeIn must be applied BEFORE the time-dependent resize —
    # otherwise its mask does not follow the animated size and black edges
    # appear at the frame borders (verified against MoviePy 2.1/2.2).
    clips, t_cursor = [], 0.0
    starts = {}
    for (name, kind), dur in zip(zip(audio_paths.keys(), kinds), durs):
        starts[name] = t_cursor
        png = work / f"{name}.png"
        scene_imgs[name].save(png)
        clip = (
            ImageClip(str(png))
            .with_duration(dur)
            .with_start(t_cursor)
            .with_effects([vfx.CrossFadeIn(C.XF)])
            .resized(lambda t, d=dur: 1 + C.ZOOM * (t / max(d, 0.001)))
            .with_position(_ken_burns_pos(dur))
        )
        clips.append(clip)
        t_cursor += dur - C.XF

    fill_png = work / "fill.png"
    frames.progress_fill().save(fill_png)
    fill = (
        ImageClip(str(fill_png))
        .with_duration(total)
        .with_position(lambda t: (-C.W * (1 - t / total), 1690))
    )

    video = CompositeVideoClip(
        [*clips, fill], size=(C.W, C.H)
    ).with_duration(total)

    # ------------------------------------------------ 5. audio composite
    voices = []
    for name, kind in zip(audio_paths.keys(), kinds):
        voices.append(
            AudioFileClip(str(audio_paths[name]))
            .with_start(starts[name] + C.LEAD[kind])
        )
    bed_src = work / "bed.wav"
    music.make_bed(total + 0.5, bed_src, seed=episode["n"] * 977)
    bed = (
        AudioFileClip(str(bed_src))
        .with_duration(total)
        .with_effects([
            afx.MultiplyVolume(C.MUSIC_LEVEL),
            afx.AudioFadeIn(0.6),
            afx.AudioFadeOut(1.4),
        ])
    )
    video = video.with_audio(CompositeAudioClip([*voices, bed]))

    # ------------------------------------------------ 6. encode
    out_mp4 = out_dir / f"{slug}.mp4"
    video.write_videofile(
        str(out_mp4), fps=C.FPS, codec="libx264", audio_codec="aac",
        preset="fast", threads=0,
        ffmpeg_params=["-crf", "20", "-pix_fmt", "yuv420p"],
        logger=None,
    )
    cover = out_dir / f"{slug}-cover.jpg"
    cover_img.save(cover, quality=90)

    _cleanup(work, keep=audio_paths.values())
    return {
        "video": out_mp4, "cover": cover, "duration": round(total, 2),
        "size_mb": round(out_mp4.stat().st_size / 1e6, 1),
        "slug": slug,
    }


def _ken_burns_pos(dur: float):
    """Center-anchored zoom + 26px slide-up entrance during first 0.45s."""

    def pos(t: float):
        s = 1 + C.ZOOM * (t / max(dur, 0.001))
        cx = -(C.W * (s - 1)) / 2
        cy = -(C.H * (s - 1)) / 2 + C.SLIDE * max(0.0, 1 - t / 0.45)
        return (cx, cy)

    return pos


def _cleanup(work: Path, keep) -> None:
    """Delete intermediate PNG/WAV; keep mp3s (tiny, useful for debugging)."""
    for f in work.iterdir():
        if f.suffix in {".png", ".wav"}:
            f.unlink()
