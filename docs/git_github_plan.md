# Git & GitHub Backup Plan (Phase B) — PREP ONLY, NOTHING EXECUTED

Generated: 2026-11-05
Scope: `/backup/github` only. This document records the B1 (git env), B2 (security pre-check)
findings and the B3 proposal. **No `git init` / `git add` / `git commit` / `git push` /
`git remote` / GitHub repo creation / credential setup / install / config change has been run.**

---

## B1 — Git Environment (read-only)

| Check | Result |
|-------|--------|
| git installed | yes — `git version 2.34.1` at `/usr/bin/git` |
| `.git` in `/backup/github` | **none** (no repository yet) |
| existing Git history | none |
| `user.name` (repo/local) | **empty** |
| `user.email` (repo/local) | **empty** |
| `user.name` (global) | **empty** |
| `user.email` (global) | **empty** |
| system gitconfig `/etc/gitconfig` | does not exist |
| global `~/.gitconfig` | does not exist |
| other notable config (safe.directory, autocrlf, filters, lfs) | none |
| remote | none (not a repo) |
| worktree status | "not a git repository" |

**Consequence:** before any commit, a committer identity is required. Recommend a repo-local
identity (avoids touching global config, per constraints):
```
git -C /backup/github config user.name  "zuxiangjushi"
git -C /backup/github config user.email "<backup-owner-email>"
```
(Values to be supplied by the user; I will not set them without instruction.)

## B2 — Security Pre-check (read-only, `/backup/github`)

### Real secrets
- **Non-vendor, readable files: 0 real secrets.** Re-detectors (sk-/ghp/AKIA/xox/JWT/private-key/qweather/OpenWebUI-email/hardcoded-password) all clean.
- Placeholder/benign (NOT secrets): `safe_switch.sh` `Bearer ***` (valueless); env-var
  references in `*.yaml`/`docker-compose`; `REPLACE_WITH_*` placeholders from Phase A.
- Test fixtures (vendor, fake values, NOT real): 2 files in
  `vendor/mem0-main/integrations/*/tests/` (`ghp_abcd…`, `sk-abcd…`, `BEGIN PRIVATE KEY` in unit-test strings).
- `Strata/strata_control/update_keys.json` — contains only a **public** ed25519 key (no private
  key, no secret). Safe. No action.

### Unreadable files (honestly flagged — NOT scanned/verified by working user)
| Path | Why | Disposition |
|------|-----|-------------|
| `projects/Memory-Gateway/fastapi_gateway.py` | `0600 root:root` | Sanitized by user (root), 10 creds removed, in manifest. Working user cannot re-read content/hash. |
| `projects/Memory-Gateway/window_budget.py` | `0600 root:root` | No live key (user-verified), in manifest. Working user cannot re-read. |

No `chmod` was performed on these (per instruction). To let the working user verify, either
`chmod 644` them or `sha256sum` as root (both one-liners, user decision).

### Junk / anomaly files present in the archive (documented, NOT deleted)
| Path | Size | What it is | Git impact |
|------|------|-----------|------------|
| `projects/ai_dxos/docker/{m[litellm_params][model]})` + **trailing newline** | 147 B | Python `SyntaxError` traceback (junk) | **Filename has a trailing newline** — may break some Git clients / `sha256sum -c` (already handled via direct hash). Flag for user decision on handling. |
| `projects/Memory-Gateway/=` | 0 B | empty junk file (name is `=`) | harmless; Git stores empty file fine |
| `projects/Memory-Gateway/===` | 12 B | text `===ai-dxos-` (junk) | harmless |
| `projects/ai_dxos/Strata/serve/web/.../helper/***.py` (vendor) | 7.4 KB | filename with `*` (3rd-party) | `*` in filename is legal in Git but tooling-sensitive |

### Executable-bit files (Git `core.filemode`)
- **~2188 files carry the executable bit** (most are `.py`/`.yaml`/`.md` that were copied with
  `0775`). Git records the exec bit (`100755` mode) by default (`core.filemode=true`). This will
  mark many text files as "executable" in the repo — harmless for backup, but worth noting.
  If desired, set `git -C /backup/github config core.filemode false` before the first commit so
  exec-bit noise is ignored. **Recommendation: leave default (true) for fidelity**, since these
  are a backup; the exec bits are part of the source state.

### Large files / Git limits
- No file > 25 MB. Largest is 3.71 MB (`.../tensors.txt`, text).
- **92 binary files**, the largest `mem0-animation.mp4` (2.91 MB) and ~1.1 MB `activity.png`
  (all in vendor). All well under GitHub's 100 MB hard limit.
- **No Git LFS needed** for size reasons. (Optional: if the user later wants history to stay
  light, the mp4/fonts/png could be LFS — not required, and LFS is not installed; do not install.)

### Databases / logs / venv / models
- Confirmed **0** of: `.git/`, `node_modules/`, venv/`__pycache__`/`.pyc`, model weights
  (`.safetensors/.gguf/.ckpt/.pt/.pth`), databases (`.db/.sqlite`), `.env`, `.bak.*` (in archive),
  logs/core dumps. (Re-verified in Phase A; unchanged.)
- Note: `volumes/packs/deepseek-v4.1-flash-ist-das-2.25bpw/` contains small tokenizer/pack
  artifacts (`tensors.txt` 3.7 MB, `vocab.json` 2.7 MB, `engram.bin` 0.5 MB, `expert-profile.bin`
  61 KB) — these are **text/binary pack metadata, not model weights**; kept for completeness.
  The user may choose to exclude this `volumes/packs/` subtree if it is not wanted in Git.

### Sensitive-but-internal content (judgment call, flagged not auto-excluded)
- `external-dependencies/` (16 files): docker-compose + systemd units. Compose files use
  env-var references (no live keys), but systemd units + compose may reference **internal host
  names/IPs** (e.g. `192.168.10.132`). For a **private** repo this is acceptable; flag to user.
- `docs/` (G0 reports, onboarding, tech_debt) and `evals/runs/*.jsonl`: internal operational
  detail. Fine for private repo; flag to user.
- `verified_backup_v6.0.sh` (56 KB): a backup script, present as a copied file, **never executed**.
  Flag to user whether to keep it in the repo.

## B3 — Proposal (NOT executed)

## B3.1 Final Git Inclusion Table (decision-ready)

Basis: user-set principles (vendor keep, docs/manifests keep, 2 root:600 keep as-is,
special files keep in archive, all GitHub private) + read-only findings below.

| Path / category | In Git | Excluded | Reason |
|-----------------|--------|----------|--------|
| `projects/ai_dxos/**` (source, configs, docker, Strata, scripts) | ✅ | — | Project source; sanitized |
| `projects/dxos_pilot/**` | ✅ | — | Project source; sanitized |
| `projects/Memory-Gateway/**` (non-vendor, 220 files) | ✅ | — | Project source; sanitized |
| `projects/Memory-Gateway/vendor/**` (1855, mem0-main + wukong) | ✅ | — | Principle: keep vendor whole, no submodule |
| `external-dependencies/**` (16 docker+systemd) | ✅ | — | Deploy refs; env-var only (no live keys); internal IPs acceptable in private repo |
| `docs/**` (security_audit, final_backup_report, this plan, G0 reports) | ✅ | — | Principle: keep docs |
| `manifests/SHA256SUMS.txt` | ✅ | — | Principle: keep manifests; integrity anchor |
| `projects/ai_dxos/verified_backup_v6.0.sh` | ✅ | — | Principle: keep as archive; **must be marked NO-EXECUTE** (see note) |
| `projects/Memory-Gateway/fastapi_gateway.py` (root:600) | ✅ | — | Principle: keep, keep 0600, no chmod. Git tracks it by content; mode bit may normalize — content hash is authoritative |
| `projects/Memory-Gateway/window_budget.py` (root:600) | ✅ | — | Same as above |
| `volumes/packs/deepseek-.../tensors.txt` (3.7 MB text) | ✅ | — | Model-pack tensor manifest (referenced by Strata setup.py); small enough for Git |
| `volumes/packs/.../tokenizer/**` (vocab 2.7 MB, merges 1.5 MB, etc.) | ✅ | — | Tokenizer files referenced by source; needed for reproducibility |
| `volumes/packs/.../engram.bin` (506 KB) | ✅ | ⬜ | Model-pack n-gram store (referenced by setup.py/adopt.py). **Recommended: include** (small, source-referenced); user may override |
| `volumes/packs/.../expert-profile.bin` (60 KB) | ✅ | ⬜ | Expert-usage profile (referenced by setup.py/adopt.py/launch). **Recommended: include** |
| `evals/**.py`, `evals/datasets/**`, `evals/ab_runs/**` | ✅ | — | Eval code + datasets + small A/B results; no secrets |
| `evals/runs/*.jsonl|json` (23 files, 453 KB) | ✅ | ⬜ | Synthetic A/B eval output (persona/gold/answer); **no real secrets, no email, no IP, no real user data**. Recommended include; user may exclude if eval data deemed internal |
| `__pycache__/`, `*.pyc`, `.pytest_cache/` | — | ✅ | Regenerable build noise |
| venv / `.venv` / `env` / `node_modules` | — | ✅ | Not present; defensive |
| `.env`, `*.env`, `secrets/`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519` | — | ✅ | None present; defence in depth |
| `*.db`, `*.sqlite`, `*.sqlite3`, `*.log`, `*.core` | — | ✅ | None present; defence in depth |
| Model weights `*.safetensors *.gguf *.ckpt *.pt *.pth` | — | ✅ | None present; never commit weights |
| `*.bak`, `*.bak.*` | — | ✅ | None in archive; source has some but they were not copied |
| `.git/` | — | ✅ | Never |
| Special: `{m[litellm_params][model]})`+trailing-newline (147 B junk) | ✅ | ⬜ | Keep in archive (principle). Git **can** store it, but the trailing-newline filename is fragile for some clients/`sha256sum -c`. **Recommended: keep** (faithful); flag that tooling may warn. Do NOT rename/delete |
| Special: `projects/Memory-Gateway/=` (0 B) | ✅ | ⬜ | Empty junk file; Git stores fine. **Recommended: keep** (faithful) |
| Special: `projects/Memory-Gateway/===` (12 B) | ✅ | ⬜ | Text junk; Git stores fine. **Recommended: keep** (faithful) |
| vendor `helper/***.py` (name has `*`) | ✅ | ⬜ | 3rd-party; `*` is legal in Git. Keep |

Legend: ✅ = recommended include; ⬜ = include by default but user may override; "—" in the
Excluded column means nothing there is excluded.

**No source, dependency, or config file is accidentally excluded.** The only exclusions are
regenerable build noise and never-present secret/weight/DB patterns (defence in depth).

## B3.2 `.gitignore` — FINAL recommended content

Place at `/backup/github/.gitignore`. Does **not** exclude any project source, dependency,
config, or the pack/eval/vendor data. (Show only — not written.)

```gitignore
# ===== Regenerable build noise =====
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.ipynb_checkpoints/

# ===== Virtual environments / node =====
venv/
.venv/
env/
node_modules/
npm-debug.log*
yarn-error.log*

# ===== Secrets / local env (none present; defence in depth) =====
.env
.env.*
*.env
secrets/
*.pem
*.key
id_rsa
id_ed25519
*.p12
*.pfx

# ===== Databases / logs / runtime (none present) =====
*.db
*.sqlite
*.sqlite3
*.log
*.core
*.lck

# ===== Model weights & large binaries (none present) =====
*.safetensors
*.gguf
*.ckpt
*.pt
*.pth

# ===== Historical backup files (none in archive) =====
*.bak
*.bak.*

# ===== OS / editor =====
.DS_Store
Thumbs.db
*.swp
*.swo
*~
.idea/
.vscode/
```

> Deliberate omissions vs. the earlier draft (so nothing legitimate is dropped):
> - **No `*.bin` rule** — `engram.bin` / `expert-profile.bin` are source-referenced pack data and
>   are small; excluding them would remove legitimate content. (If the user later decides to drop
>   the whole `volumes/packs` subtree, add `projects/ai_dxos/volumes/packs/` explicitly.)
> - **No `*.jsonl` / `*.json` rule** — eval results and configs are JSON/JSONL and are kept.
> - The special junk files (`{m[...])\n`, `=`, `===`) are **not** matched by any rule, so they
>   stay in Git (faithful). To exclude the trailing-newline one specifically would require a
>   manual `git rm --cached` at commit time (not done here).

### B3.3 Git size / LFS
- No file approaches GitHub's 100 MB limit (max 3.71 MB). **No LFS required.** Do not install LFS.

### B3.4 Suggested first commit message
```
Initial backup archive of ai_dxos, dxos_pilot, Memory-Gateway

- Local, secret-sanitized archive (see docs/security_audit.md)
- SHA256 manifest: manifests/SHA256SUMS.txt (2581 entries)
- Excluded: model weights, databases, venvs, logs, .env
- 2 root-owned files (fastapi_gateway.py, window_budget.py) included, root-verified
- No .git history prior to this commit
```

### B3.5 GitHub private-repo connection plan (only after explicit authorization)

1. **Repo:** `ai-dxos-backup`, **Private** (never public).
2. **Auth:** prefer a **fine-grained or classic PAT** or SSH deploy key. The token/key must be
   supplied by the user out-of-band and **never** written into scripts, `.gitconfig`, the
   remote URL, or any committed file. Preferred remote form (token via credential helper /
   prompt, not embedded):
   - SSH: `git@github.com:zuxiangjushi/ai-dxos-backup.git`
   - HTTPS: `https://github.com/zuxiangjushi/ai-dxos-backup.git` (token entered at prompt or
     stored only in the OS keychain/credential-helper, not in the URL).
3. **Steps (each gated on user "go"):**
   - create the private repo (via GitHub UI or `gh repo create ai-dxos-backup --private`)
   - `git remote add origin <url>`
   - `git push -u origin main` (or `master`)
4. **Safeguards:** if the repo already exists, first inspect its branches/commits/files; do a
   **non-force** push; never `push --force` or rewrite history.

### B3.6 Post-push integrity verification plan
1. `git ls-remote origin` — confirm the remote ref exists and matches local HEAD SHA.
2. `git log --oneline -1 origin/main` equals local `git rev-parse HEAD`.
3. On a fresh clone in a temp dir: `sha256sum -c manifests/SHA256SUMS.txt` (as the user, or root
   for the 2 root:600 files) — expect the same PASS set as local.
4. Compare file count: `git ls-files | wc -l` vs. on-disk count.
5. Confirm the two root:600 files are present in the clone (their mode may normalize; content
   hash must match the manifest).
6. Confirm repo visibility is **Private** in GitHub UI/API.

## Open items (need user decision)
1. Provide committer `user.name` / `user.email` (or approve repo-local values).
2. Keep / submodule / ignore the `vendor/` tree (1855 files, 3rd-party).
3. Keep or ignore `volumes/packs/*.bin` and the whole `volumes/packs/` subtree.
4. Keep or ignore `evals/runs/*.jsonl` (internal eval data) and `docs/` (internal reports).
5. Keep `verified_backup_v6.0.sh` in the repo.
6. How to handle the 3 junk/anomaly files (trailing-newline name, `=`, `===`): keep as-is
   (faithful) or exclude — **do not delete/rename without instruction**.
7. Whether to `chmod 644` the 2 root:600 files so the working user can re-verify, or verify as root.
8. Approve creating the private repo + pushing.

## Execution status
```
git init: NOT executed
git add: NOT executed
git commit: NOT executed
git push: NOT executed
git remote add: NOT executed
GitHub repo: NOT created
GitHub remote: NOT connected
No install, no config change, no file/permission change performed.
```
