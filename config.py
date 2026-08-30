"""
Everything personal about this profile card lives here.

Edit this file and nothing else when you want to change what the card says.
`today.py` fetches the live numbers, `render.py` draws the SVGs, and neither
of them contains a hard-coded fact about you.

Rows marked LIVE are filled in from the GitHub API at build time - the value
written here is only a placeholder for local dry runs.
"""

import os

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

# GitHub login. Overridable with the USER_NAME env var so the workflow can run
# against a different account without a code change.
USER_NAME = os.environ.get('USER_NAME', 'codabytez')

# The `user@host` prompt at the top of the panel.
PROMPT = 'lisan_al_gaib@codabytez'

# What the "Uptime" row counts from.
#   'account'    - your GitHub account's creation date, fetched at build time
#   'YYYY-MM-DD' - a fixed date (e.g. your birthday), rendered with a cake emoji
#                  on the anniversary
UPTIME_FROM = 'account'
UPTIME_LABEL = 'Uptime'

# ---------------------------------------------------------------------------
# Panel content
#
# Each entry is (label, value). A label containing '.' is rendered with the
# dot as a dim separator, matching neofetch's `Languages.Programming` style.
# ---------------------------------------------------------------------------

SYSTEM = [
    ('OS',     'macOS Tahoe, iOS, Android'),
    ('Host',   'Product Engineer, Unbuilt Studio'),
    ('Kernel', 'Abuja, Nigeria'),
    ('IDE',    'VS Code, Xcode, Android Studio'),
    ('Shell',  'zsh, Git, GitHub Actions'),
]

LANGUAGES = [
    ('Languages.Programming', 'LIVE'),   # top languages by bytes across your repos
    ('Languages.Real',        'English, French'),
]

STACK = [
    ('Stack.Web',     'Next.js, React, Vue, Nuxt, Tailwind'),
    ('Stack.Mobile',  'React Native, Expo, EAS, Capacitor'),
    ('Stack.Backend', 'Node.js, NestJS, Supabase, PostgreSQL'),
    ('Stack.Tooling', 'CLIs, VS Code extensions, CI'),
]

# No GitHub row on purpose: this card renders on github.com/codabytez, so a
# row pointing at github.com/codabytez tells the reader where they already are.
CONTACT = [
    ('Email',     'hello@unbuilt.studio'),
    ('Portfolio', 'unbuilt.studio'),
    ('X',         '@codabytez'),
    ('LinkedIn',  'linkedin.com/in/codabytez'),
]

# ---------------------------------------------------------------------------
# Which repositories count toward the stats
# ---------------------------------------------------------------------------

# Repos counted for lines-of-code and the "Contributed" figure.
CONTRIB_AFFILIATIONS = ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER']
# Repos counted for the "Repos" and "Stars" figures.
OWNED_AFFILIATIONS = ['OWNER']

# Repos whose languages are counted. Organisation and collaborator repos are
# included, otherwise work you did on a team is invisible - the Vue is all in
# org repos, so OWNER-only reported none of it.
LANGUAGE_AFFILIATIONS = CONTRIB_AFFILIATIONS

# ...but GitHub reports a repo's language bytes in full, with no idea whose
# bytes they are, so counting every org repo credits you with your teammates'
# languages. A repo only counts once you have this many commits in it. At 1,
# a backend you sent two PRs to reported as 12% Blade + PHP; at 3, it drops out
# and Vue - 71 commits in useburse/website - stays. Raise it to be stricter.
LANGUAGE_MIN_COMMITS = 3

# Languages ignored in the top-languages breakdown - markup, config and
# generated files otherwise drown out what you actually write.
LANGUAGE_IGNORE = {'HTML', 'CSS', 'SCSS', 'Dockerfile', 'Makefile', 'Procfile'}
# How many languages to show in the breakdown row.
LANGUAGE_COUNT = 4

# ---------------------------------------------------------------------------
# WakaTime
#
# Hours actually spent coding, from WakaTime's public stats endpoint - no API
# key, because the account publishes its stats. Set WAKATIME_USER to '' to drop
# the row. Only the range the account makes public will answer; this one
# publishes all_time, and the others return 400.
# ---------------------------------------------------------------------------
WAKATIME_USER = 'codabytez'
WAKATIME_RANGE = 'all_time'
WAKATIME_LABEL = 'Coding time'

# Lines at the top of the cache file reserved for human-readable comments.
CACHE_COMMENT_SIZE = 7

# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------

# The canvas grows to fit its content; MIN_HEIGHT is only the floor, so adding
# a row below does not require touching any geometry.
WIDTH, MIN_HEIGHT = 985, 530

# The left column: ASCII portrait, then the wordmark beneath it.
#
# Each theme names its own portrait (see THEMES below); this is the fallback.
# The two differ by tonal polarity, not content: dark mode paints light glyphs
# on a dark ground so a dense glyph reads BRIGHT, while light mode is dark ink
# on a light ground so density reads DARK. Sharing one file made the light card
# a photographic negative. Regenerate the pair with:
#   python scripts/gen_ascii.py portrait --user codabytez --gamma 0.9
#   python scripts/gen_ascii.py portrait --user codabytez --gamma 0.9 --invert \
#       --out art/avatar-light.txt
ART_FILE = 'art/avatar.txt'
WORDMARK_FILE = 'art/wordmark.txt'
TAGLINE = 'Music, Code and You.'

# Panel geometry, in characters and pixels respectively.
#
# PANEL_COLS is the budget every row is justified to. Consolas is 0.55em wide,
# but readers without it fall back to Menlo/DejaVu/Liberation at ~0.60em, so
# the width is set for the widest realistic fallback: 58 * 16px * 0.603 = 560px,
# which lands ~35px clear of the right edge. Raising it risks clipping.
PANEL_COLS = 58
PANEL_X = 390
PANEL_Y = 30
PANEL_LEADING = 20

ART_X, ART_Y = 15, 28
ART_FONT_SIZE = 11
ART_LEADING = 11.5       # tight enough that a square image stays square

# Weekly contribution sparkline, drawn under the portrait to fill the space the
# taller stats panel would otherwise leave empty. 52 bars at 12px is 376px -
# the same width as the portrait above it, so the two line up.
SPARK_WEEKS = 52
SPARK_FONT_SIZE = 30     # bar height
SPARK_WIDTH = 345        # squeezed to this, matching the portrait's width
SPARK_LABEL = 'Contribution activity'
SPARK_GAP = 34           # below the portrait
SPARK_CAPTION_SIZE = 11

# Spotify block, drawn under the sparkline in the space the taller stats panel
# leaves over. Silently skipped unless SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
# and SPOTIFY_REFRESH_TOKEN are all set - see SETUP.md, and
# `python scripts/spotify_auth.py` to mint the refresh token.
#
# Deliberately top artists rather than "now playing": the card is rebuilt once
# a day, so a now-playing row would only ever report what was on at 05:30 UTC.
MUSIC_LABEL = '- Music'
#   short_term  ~ last 4 weeks     medium_term ~ last 6 months
#   long_term   ~ last year
MUSIC_TIME_RANGE = 'short_term'
MUSIC_TIME_LABEL = 'last 4 weeks'
MUSIC_COLS = 49          # the left column is narrower than the stats panel
# How many lines 'On repeat' may use. Track titles are long and the column is
# only 35 usable columns, so one line held about two of them. There is exactly
# one spare row under the block before the card grows, so 2 is free.
MUSIC_TRACK_LINES = 2
MUSIC_FONT_SIZE = 12
MUSIC_LEADING = 19
MUSIC_GAP = 30           # below the sparkline caption

# The wordmark is a full-width band beneath both columns, centred with
# text-anchor so it stays centred whichever monospace font the reader has.
# Everything below is measured from the bottom of the taller column, so the
# band follows the panel down as rows are added to config.
WORDMARK_GAP = 34        # space between the columns and the divider rule
WORDMARK_FONT_SIZE = 30
# Slightly under the font size so the full-block glyphs butt together into
# solid strokes instead of stacking as separated bars.
WORDMARK_LEADING = 29
TAGLINE_GAP = 38
TAGLINE_FONT_SIZE = 17
BOTTOM_MARGIN = 30

# ---------------------------------------------------------------------------
# Themes - one entry per generated SVG
# ---------------------------------------------------------------------------

THEMES = {
    'dark_mode.svg': {
        'art':      'art/avatar.txt',
        'bg':       '#161b22',
        'fg':       '#c9d1d9',
        'key':      '#ffa657',
        'value':    '#a5d6ff',
        'add':      '#3fb950',
        'del':      '#f85149',
        'dim':      '#616e7f',   # dot leaders
        'muted':    '#8b949e',   # captions and the tagline
        'accent':   '#ffa657',
    },
    'light_mode.svg': {
        'art':      'art/avatar-light.txt',
        'bg':       '#f6f8fa',
        'fg':       '#24292f',
        'key':      '#953800',
        'value':    '#0a3069',
        'add':      '#1a7f37',
        'del':      '#cf222e',
        'dim':      '#c2cfde',   # dot leaders
        'muted':    '#57606a',   # captions and the tagline
        'accent':   '#953800',
    },
}
