"""Design system + paths + timing for the daily video engine.

Clean-minimal style: white canvas, one bold accent (#635BFF),
big Inter headlines, IBM Plex Mono chips. Everything deterministic —
same episode always renders pixel-identical (no AI-slop randomness).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
CONTENT_DIR = ROOT / "content"
OUTPUTS = ROOT / "outputs"

# ---------------------------------------------------------------- canvas ----
W, H = 1080, 1920           # 9:16 for Reels / Pinterest video pins
FPS = 30
MARGIN = 72                 # side margin
CONTENT_W = W - 2 * MARGIN  # 936px text column
SAFE_TOP = 220              # keep clear of IG Reels top UI
SAFE_BOTTOM = 340           # keep clear of IG Reels caption/UI overlay

# ----------------------------------------------------------------- color ----
BG = (255, 255, 255)            # canvas
INK = (11, 11, 18)              # primary text  #0B0B12
MUTED = (107, 111, 118)         # secondary text #6B6F76
ACCENT = (99, 91, 255)          # #635BFF
ACCENT_TINT = (237, 235, 255)   # pill background #EDEBFF
CARD = (241, 242, 244)          # code chip background #F1F2F4
CARD_LINE = (228, 231, 236)     # chip border #E4E7EC
WHITE = (255, 255, 255)

# --------------------------------------------------------------- timing ----
XF = 0.35          # crossfade between scenes (s)
ZOOM = 0.035       # per-scene Ken Burns zoom (1.00 -> 1.035)
SLIDE = 26         # entrance slide-up distance (px) over 0.45s
LEAD = {"hook": 0.55, "tip": 0.28, "cta": 0.30}   # silence before narration
TAIL = {"hook": 0.30, "tip": 0.22, "cta": 0.70}   # silence after narration

# ----------------------------------------------------------------- audio ----
MUSIC_LEVEL = 0.17          # music bed level under the voiceover
TTS_RATE = "+10%"           # speaking rate
DEFAULT_VOICE = "en-US-AndrewNeural"

# ------------------------------------------------------------------ font ----
FONT_FILES = {
    "display_xb": FONTS / "InterDisplay-ExtraBold.ttf",  # hook headline
    "display_b": FONTS / "InterDisplay-Bold.ttf",        # CTA / handle
    "semibold": FONTS / "Inter-SemiBold.ttf",            # tip titles
    "medium": FONTS / "Inter-Medium.ttf",                # body copy
    "regular": FONTS / "Inter-Regular.ttf",              # watermark
    "mono_m": FONTS / "IBMPlexMono-Medium.ttf",          # code chips
    "mono_sb": FONTS / "IBMPlexMono-SemiBold.ttf",       # pills / labels
}

# ---------------------------------------------------------------- topics ----
TOPICS = {
    "web-design": {
        "content_file": "web_design.json",
        "pill": "DAILY WEB DESIGN",
    },
    "github-freelancing": {
        "content_file": "github_freelancing.json",
        "pill": "GITHUB x FREELANCING",
    },
}
