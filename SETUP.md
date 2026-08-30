# How the card is built

`README.md` on this repo renders on my GitHub profile, and all it contains is a
`<picture>` pointing at two SVGs. Those SVGs are regenerated every morning by
GitHub Actions.

Originally [Andrew6rant/Andrew6rant](https://github.com/Andrew6rant/Andrew6rant),
rebuilt so that everything personal lives in one file and both themes are
generated rather than hand-edited.

## Layout

| File                   | Does                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| `config.py`            | Every personal fact, the colour themes, and the geometry. **The only file you edit day to day.** |
| `today.py`             | Talks to the GitHub GraphQL API, maintains the line-of-code cache.                               |
| `render.py`            | Turns config + stats into `dark_mode.svg` and `light_mode.svg`.                                  |
| `scripts/gen_ascii.py` | Regenerates the ASCII portrait and wordmark. Not run in CI.                                      |
| `art/*.txt`            | The committed ASCII art.                                                                         |
| `cache/<sha256>.txt`   | Per-repository commit and LOC totals, keyed by username.                                         |

## Running it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r cache/requirements.txt

ACCESS_TOKEN=$(gh auth token) python today.py
```

Or copy `.env.example` to `.env` and put a token in it — `today.py` reads `.env`
automatically. `.env` is gitignored.

The **first** run is slow: it walks every commit in every repository you can
see, which for ~70 repos takes several minutes and a few hundred API calls.
After that the cache means only repositories whose commit count changed get
re-walked, and a run takes seconds.

## The token

CI falls back to the built-in `github.token`, which is enough for public data.
For private repositories to count, add an `ACCESS_TOKEN` repository secret
holding a fine-grained PAT with **All repositories** access:

- Account permissions: `read:Followers`, `read:Starring`, `read:Watching`
- Repository permissions: `read:Commit statuses`, `read:Contents`,
  `read:Metadata`, `read:Issues`, `read:Pull Requests`

## Changing what the card says

Everything is in `config.py`. Rows are `(label, value)` pairs; a label with a
`.` in it renders neofetch-style (`Stack.Web`). Add or remove rows freely — the
dot leaders are computed, and the canvas grows to fit, so nothing needs
realigning by hand.

`Languages.Programming` and `Top Languages` are marked `LIVE`: they are totalled
from the bytes GitHub reports across your non-fork repositories at build time,
so they stay honest without being maintained. `LANGUAGE_IGNORE` in `config.py`
drops markup and config languages that would otherwise dominate.

Both language rows size themselves to the space left on their line and drop the
tail that will not fit, so a long language name can never push text past the
edge of the card.

### How a repo qualifies

Two knobs decide which repos feed those rows, and they exist because GitHub
reports a repository's language bytes **in full**, with no notion of whose
bytes they are.

- `LANGUAGE_AFFILIATIONS` includes organisation and collaborator repos. Owner-
  only missed every line of Vue, since all of it lives in org repos.
- `LANGUAGE_MIN_COMMITS` then drops repos you barely touched. At a threshold of
  1, a teammate's Laravel backend you sent two PRs to reported as 12% Blade and
  PHP. At 3 it drops out and the real work stays.

There is a wrinkle worth knowing about. The commit counts in the cache come
from `recursive_loc()`, which only ever walks the **default branch** — so a
repo where your work sits on feature branches that were never merged reports
zero. `stardelite/BurseApp` is exactly that case: 57 commits on one branch,
none on its default. `branch_commits()` catches it by re-checking every branch
with an author filter, but only for repos that fall below the threshold, so it
costs one extra query per borderline repo rather than one per repo.

The same limitation still applies to the headline **Commits** and **Lines of
Code** figures, which remain default-branch only — unmerged branch work is not
counted there.

## The contribution sparkline

Under the portrait, one bar per week for the last year, from the same data as
the green squares on your profile. It is drawn on a **square-root** scale:
contribution weeks are heavily skewed, and on a linear scale one sprint week
flattens every other week onto the bottom bar.

Tune it with `SPARK_*` in `config.py` — `SPARK_FONT_SIZE` is the bar height and
`SPARK_WIDTH` the total width the bars are squeezed into, which is set to match
the portrait above so the two line up.

## The Music block

Top artists, top track and top genres, under the sparkline. It is **top items
over a rolling window, not "now playing"** — and that is deliberate. This card
is regenerated once a day, so a now-playing row could only ever report whatever
happened to be on at 05:30 UTC. Top items change slowly enough that a daily
rebuild tells the truth.

The whole block is optional. With no Spotify secrets set it is skipped, the
build succeeds, and the card renders without it.

### Setting it up

1. Create an app at <https://developer.spotify.com/dashboard>. Add exactly this
   redirect URI:

   ```text
   http://127.0.0.1:8888/callback
   ```

   A new app starts in *development mode*, which is all this needs — it allows
   up to 25 listed users and you are the only one. No quota extension needed.

2. Mint a refresh token. This opens your browser, catches the redirect, and
   prints the three values:

   ```bash
   ./.venv/bin/python scripts/spotify_auth.py \
     --client-id XXX --client-secret YYY
   ```

3. Store all three as repository secrets (*Settings → Secrets and variables →
   Actions*), and in `.env` for local runs:

   ```text
   SPOTIFY_CLIENT_ID
   SPOTIFY_CLIENT_SECRET
   SPOTIFY_REFRESH_TOKEN
   ```

The refresh token does not expire. It is only invalidated if you revoke the
app's access or change your Spotify password — if the block ever vanishes, that
is the first thing to check, and re-running `spotify_auth.py` fixes it.

Only the `user-top-read` scope is requested; the script asks for no playback or
playlist access it does not need.

Tune the window with `MUSIC_TIME_RANGE` in `config.py`: `short_term` (~4 weeks,
the default), `medium_term` (~6 months) or `long_term` (~1 year). Update
`MUSIC_TIME_LABEL` to match, since it is only the heading text.

## Geometry

You should not need to touch it, but if you do: `PANEL_COLS` is the character
budget every panel row is justified to, and it is deliberately conservative.
Consolas is 0.55em wide; readers without it fall back to Menlo, DejaVu or
Liberation Mono at ~0.60em, so 58 columns is sized for the widest realistic
fallback. Raising it risks clipping on machines that are not Windows.

The canvas height is computed, never fixed — `MIN_HEIGHT` is only a floor. Add
rows and the wordmark band moves down rather than colliding with them.

## Regenerating the art

Needs Pillow, which CI does not install — the art is committed.

```bash
pip install -r scripts/requirements.txt

# portrait, from your avatar or any image
python scripts/gen_ascii.py portrait --user codabytez
python scripts/gen_ascii.py portrait photo.jpg --gamma 0.85

# the wordmark under it
python scripts/gen_ascii.py wordmark CODABYTEZ --width 44
```

The wordmark is drawn with U+2588 FULL BLOCK rather than `#`, which at the size
the card renders it leaves visible gaps between cells. Pass `--fill '#'` to go
back to plain ASCII. `--width` is the column count the letters are centred in;
keep it at the natural span (4 columns per letter plus a gap) since the card
centres the block itself.

The portrait detects the flat backdrop behind the subject and drops it, so the
background does not fill the frame with noise. Useful knobs:

- `--gamma` below 1 brightens the midtones, above 1 darkens them
- `--tolerance` how far a pixel may stray from the backdrop and still count as
  background; raise it for busy photos, lower it if part of the subject vanishes
- `--keep-background` renders the backdrop anyway
- `--cols` / `--rows` change the grid; keep the ratio near 52:30 or the portrait
  stretches, since `config.ART_LEADING` assumes it

Best results come from a head-and-shoulders shot filling the frame, against a
plain or blurred background.

## The workflow

`.github/workflows/build.yaml` runs at 05:30 UTC daily, on push, and on demand
via **Actions → Build profile card → Run workflow**. That manual trigger has a
`force_cache` checkbox which throws away the LOC cache and rebuilds it — needed
if you rewrite history or the numbers ever look wrong.

It commits only when the SVGs actually changed, and the commit message carries
`[skip ci]` so it cannot trigger itself.
