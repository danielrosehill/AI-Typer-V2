---
name: release
description: Post-update release procedure for Multimodal Voice Typer — bump version, build a new .deb, install it locally, then cut a GitHub release with the .deb attached and auto-generated notes. Triggers on "release", "ship it", "cut a release", "new release", "post-update", "build and release".
---

# Release — Multimodal Voice Typer

End-to-end post-update procedure for this repo. Use after finishing a round of fixes or features.

## Repo-specific facts (don't re-derive)

- **Package name**: `ai-typer-v2` (the apt package name; repo is `Multimodal-Voice-Typer`)
- **Version source of truth**: `pyproject.toml` → `version = "X.Y.Z"`. Also update `app/src/config.py` → `APP_VERSION = "X.Y.Z"` (they must match).
- **Build command**: `./build.sh --deb` — emits `dist/ai-typer-v2_<version>_all.deb`
- **Dev install**: `./build.sh --dev` (faster; copies files into `/opt/ai-typer-v2/` directly — use during iteration, not for the release artifact)
- **Release artifact**: the `.deb` from `./build.sh --deb`, not `--dev`

## Steps

### 1. Commit any outstanding changes

- `git status` — if clean, skip to step 2
- Stage and commit all changes with a clear message summarizing what shipped
- `git push`

### 2. Bump the version

- Default: **patch** bump (e.g. `0.3.1` → `0.3.2`)
- `$ARGUMENTS` override: `minor`, `major`, or an explicit `X.Y.Z`
- Update both files in the **same commit**:
  - `pyproject.toml`: `version = "X.Y.Z"`
  - `app/src/config.py`: `APP_VERSION = "X.Y.Z"`
- Commit: `chore: bump version to X.Y.Z`
- Push

### 3. Build the .deb

```bash
./build.sh --deb
```

- Confirm `dist/ai-typer-v2_<new-version>_all.deb` exists
- If the build fails, stop and report — do not proceed to install or release

### 4. Install locally

```bash
sudo dpkg -i dist/ai-typer-v2_<version>_all.deb
sudo apt-get install -f -y
```

Verify:

```bash
dpkg -l | grep ai-typer-v2
```

Installed version must match the new version. If a previous run of the app is open, tell the user to restart it to pick up the new build.

### 5. Tag and create the GitHub release

```bash
git tag vX.Y.Z
git push origin vX.Y.Z

gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --generate-notes \
  --notes "$(cat <<'EOF'
## Highlights

<one or two bullet points describing the headline changes in this release —
pull from the commits since the last tag; keep it short>

## Install

Download the `.deb` below, then:

```bash
sudo dpkg -i ai-typer-v2_X.Y.Z_all.deb
sudo apt-get install -f -y
```

EOF
)" \
  dist/ai-typer-v2_<version>_all.deb
```

- `--generate-notes` auto-lists commits since the last tag; the custom `--notes`
  block prepends a short human-readable summary above that list. Keep the
  summary to 1–3 bullets — the auto-generated commit list carries the detail.
- Substitute `X.Y.Z` / `<version>` for the actual version.

### 6. Report back

Tell the user:

- New version number
- Local installation status (did `dpkg -l` confirm the new version?)
- GitHub release URL (`gh release view vX.Y.Z --json url -q .url`)
- Whether the running app needs to be restarted

## Notes

- **Do not** use `./build.sh --dev` for the release artifact — it's for iteration only. The `.deb` attached to the GitHub release must come from `--deb`.
- If `$ARGUMENTS` contains `--no-install`, skip step 4.
- If `$ARGUMENTS` contains `--draft`, pass `--draft` to `gh release create`.
- If the version in `pyproject.toml` and `app/src/config.py` are already out of sync, fix them both to the same value before bumping.
