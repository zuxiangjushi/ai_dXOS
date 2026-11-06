# Final Backup Report — GitHub Archive (Local)

Generated: 2026-11-05
Archive root: `/backup/github`
Companion document: `docs/security_audit.md` (full security detail)

**Status: LOCAL ARCHIVE COMPLETE. NOT yet a Git repository. NOT pushed to GitHub.**

---

## 1. Archive Goals & Directory Structure

Goal: produce a clean, Git-ready, secret-free archive of three project trees plus their
deployment artifacts, for eventual backup to a **private** GitHub repository.

```
/backup/github
├── docs/
│   ├── security_audit.md          # full security audit (findings, sanitization, hashes)
│   └── final_backup_report.md     # this file
├── manifests/
│   └── SHA256SUMS.txt             # 2581 entries (sha256sum-compatible)
├── scripts/                       # (empty — reserved)
├── external-dependencies/
│   ├── docker/                    # 3 docker-compose files (docker/systemd refs)
│   ├── systemd/                   # 13 systemd unit files
│   └── scripts/                   # (empty)
└── projects/
    ├── ai_dxos/                   # 460 files (source + configs + docker + Strata + volumes/packs)
    ├── dxos_pilot/                # 30 files (backend + frontend)
    └── Memory-Gateway/            # 2075 files (220 project + 1855 vendor/mem0-main,wukong)
```

Source projects (`/ai/Memory-Gateway`, `/ai/ai_dxos`, `/ai/dxos_pilot`) were treated as
**read-only** throughout. No source file was modified, renamed, or had its permissions changed.

## 2. File Counts & Statistic Basis

| Scope | Count | Basis |
|-------|-------|-------|
| Total files on disk (incl. `SHA256SUMS.txt`) | 2584 | `os.walk` file count (2583 + this report) |
| Files in `SHA256SUMS.txt` | 2581 | every on-disk file except the manifest and the two `docs/*.md` |
| `projects/ai_dxos` | 460 | recursive file count |
| `projects/dxos_pilot` | 30 | recursive file count |
| `projects/Memory-Gateway` (incl. vendor) | 2075 | recursive file count |
| `projects/Memory-Gateway` (excl. vendor) | 220 | project-owned code only |
| `vendor/` (mem0-main + wukong) | 1855 | 3rd-party upstream |
| `external-dependencies/` | 16 | docker (3) + systemd (13) |
| Archive size | ~60 MB | `du -sh` |
| Largest file | 3,713,468 B | `projects/ai_dxos/volumes/packs/.../tensors.txt` (text) |
| Files > 50 MB | 0 | none — suitable for Git |

> Basis note: counts are recursive regular-file counts. The `vendor/` tree (1855 files) is
> 3rd-party upstream content (mem0-main, wukong) kept for completeness; it may be excluded
> from Git via a `.gitignore` or submodule decision (see Phase B).

## 3. Sanitization Completed (archive copies only)

Six archive copies had live credentials replaced with placeholders. Sources were never touched.

| # | Archive file | Replacements | Notes |
|---|--------------|-------------|-------|
| 1 | `projects/Memory-Gateway/claude_bridge.py` | 2 | `LITELLM_KEY` + `CLIENT_KEY` (`sk-…`) |
| 2 | `projects/ai_dxos/configs/litellm_config.yaml` | 8 | `api_key: sk-…` entries → `sk-REPLACE_WITH_LITELLM_KEY_M00_FROM_VAULT` |
| 3 | `projects/ai_dxos/scripts/sync_openwebui_models.py` | 2 | hardcoded OpenWebUI email + password |
| 4 | `projects/Memory-Gateway/search_modules/weather_adapter.py` | 1 | 和风天气 key default removed; host → env-configurable |
| 5 | `projects/dxos_pilot/frontend/index.html` | 8 | one `sk-` LLM-gateway key across 7 config snippets |
| 6 | `projects/Memory-Gateway/fastapi_gateway.py` | 10 | user-sanitized (root); copy shrank 139544 → 139402 B |

Post-sanitization re-scan (non-vendor, readable files): **0 real secrets remaining.**
The only `sk-` detector hit is the valueless `Bearer ***` placeholder in
`projects/ai_dxos/scripts/safe_switch.sh` (no key value present — benign).

## 4. Exclusions (content not suitable for Git)

All verified **absent** from the archive (recursive scan):

| Category | Present? |
|----------|----------|
| `.git/` directories | 0 |
| `node_modules/` | 0 |
| virtualenvs (`venv`/`.venv`/`env`), `site-packages`, `__pycache__`, `*.pyc` | 0 |
| model weights (`.safetensors`/`.gguf`/`.ckpt`/`.pt`/`.pth`) | 0 |
| databases (`.db`/`.sqlite`/`.sqlite3`) | 0 |
| `.env` / dotenv files | 0 (configs use env-var *references*) |
| `.bak.*` historical backups | 0 in archive (source has `docker-compose.yml.bak`, correctly not copied) |
| logs / core dumps | 0 (non-vendor) |
| files > 100 MB | 0 |
| `/opt/ai-platform/models` | never accessed |

## 5. Two 补拷 Files (copied + sanitized + in manifest)

| Archive path | Size | Mode | Owner | Manifest SHA256 |
|--------------|------|------|-------|-----------------|
| `projects/Memory-Gateway/fastapi_gateway.py` | 139402 B | `0600` | root:root | `459eda43a4be53519d55c4100b38eddaa80c6f3de3837f30458736c586981164` |
| `projects/Memory-Gateway/window_budget.py` | 4750 B | `0600` | root:root | `d386773f9bc5a625fe87a281245fd851ebd2612efc33604f3ef461393e34ceb8` |

`fastapi_gateway.py` had 10 hardcoded credentials removed (user, root). `window_budget.py`
contained no live key. **Limitation:** both are `0600 root:root`, so the working (`paxen`)
user could verify size/mode/ownership/presence/manifest-entry but **not** re-read content or
recompute the hash. Content scan + hash confirmation were done by the user as root.
See `security_audit.md` §8 for the two one-line options to close the working-user gap
(`chmod 644` to let paxen verify, or `sha256sum` as root).

## 6. SHA256 Verification Results

- `manifests/SHA256SUMS.txt` holds **2581 entries** (sha256sum-compatible; special chars escaped).
- **As the working (`paxen`) user**, `sha256sum -c manifests/SHA256SUMS.txt`:
  - **2578 PASS** (all readable ordinary files)
  - 2 × 权限不够 (permission denied) — the two `root:600` 补拷 files
  - 1 × parse warning — the trailing-newline-named file (§7); `sha256sum` cannot parse that path
- **Trailing-newline file** verified separately via direct Python hash — actual SHA256
  `8d4655be837b62526fc3f02656eaa1b228c7eb7096b55fdf7102980976563cdf` **matches** manifest. ✅
- **As root** (user-confirmed): `sha256sum -c` → **2580 PASS, 0 FAILED, 0 Missing, 1 Malformed**
  (the one "Malformed" is the unparseable newline-named line, which is present + hash-confirmed).

**Net:** 2579 of 2581 manifest entries are verified by the working user; the final 2
(补拷 files) are verified by the user as root. No file is missing or corrupted.

## 7. Anomalous / Special File (documented, NOT deleted/renamed)

| Field | Value |
|-------|-------|
| Path | `projects/ai_dxos/docker/{m[litellm_params][model]})` + trailing newline in the name |
| Size | 147 bytes |
| Mode | `0755` |
| SHA256 | `8d4655be837b62526fc3f02656eaa1b228c7eb7096b55fdf7102980976563cdf` (verified) |
| Content | a Python `SyntaxError` traceback (ANSI-colored) — junk from an earlier unquoted script |
| Source counterpart | `/ai/ai_dxos/docker/` has the identical 147-byte file — archive is a faithful copy |
| Action | **None** — recorded only, per instruction (not deleted/renamed/moved) |

Impact: its trailing-newline name breaks `sha256sum -c` line parsing for that one entry; it is
verified by direct hash instead. In Git, the trailing newline in the filename may cause
tooling friction — flagged for a Phase B decision (it must NOT be renamed here).

## 8. Permission & Security Check

- **root-owned files in archive:** exactly the 2 补拷 files (`0600 root:root`). All other files are
  `paxen`-owned with normal modes (files `0644`, dirs `0755`).
- **No real secrets** in any readable non-vendor file (re-scanned post-sanitization).
- **Vendor** (`mem0-main` tests) contains 2 files with obviously-fake **test-fixture** values
  (`ghp_abcd…`, `sk-abcd…`, `BEGIN PRIVATE KEY` in unit-test strings) — 3rd-party upstream,
  not real credentials; left as-is.
- **No** `.env`, private keys, certs, DB dumps, or model weights present.
- **Not executed:** `verified_backup_v6.0.sh` (present as a copied file only; never run).

## 9. Unfinished Items (Local)

1. **Working-user verification of the 2 补拷 files** (content scan + hash) — blocked by `0600 root:root`.
   Close via `chmod 644` (lets paxen verify) or `sha256sum` as root. Single remaining local gap.
2. `verified_backup_v6.0.sh` remains an archived-but-never-run script (intended).

## 10. GitHub Push Status

**NOT pushed.** There is no `.git` directory under `/backup/github`, no Git repository, no remote,
and no commits. The archive is a plain directory tree ready for Phase B (Git + private GitHub).
No `git init`, no GitHub login, no push, no Release, no upload has been performed.
