# Security Audit — GitHub Backup Archive (Phase 5)

Generated: 2026-11-05
Archive root: `/backup/github`
Scope: archive copies only. Source projects under `/ai/` were treated as **read-only**.
No source file was modified, renamed, or had its permissions changed. No project re-copy was performed. No `git init` / GitHub push / sudo / install / service restart was executed.

## 1. Archive Overview

| Item | Value |
|------|-------|
| Total files on disk (incl. manifest) | 2583 |
| Files in SHA256 manifest | 2581 |
| Total archive size | ~60 MB (du -sh) |
| `projects/ai_dxos` files | 460 |
| `projects/dxos_pilot` files | 30 |
| `projects/Memory-Gateway` files (incl. vendor) | 2075 |
| `projects/Memory-Gateway` files (excl. vendor) | 220 |
| `vendor/` (3rd-party, mem0-main + wukong) files | 1855 |
| `external-dependencies/` files (docker + systemd) | 16 |

## 2. Scan Scope

Scanned for: API keys / tokens (`sk-`, `ghp_`/`github_pat_`, `AKIA`, Slack `xox*`, JWT `eyJ...`), private-key blocks (`BEGIN ... PRIVATE KEY`), database credentials, `.env`/dotenv files, hardcoded passwords, and known prior-risk patterns (和风天气/qweather key).

- **Primary (deep) scan:** all non-vendor files in `/backup/github` (hand-written project code, configs, scripts, docs, docker/systemd, frontend).
- **Informational scan:** `vendor/` (3rd-party `mem0-main`, `wukong`) — hit count only, no values.
- **Excluded from deep scan:** nothing by directory; vendor reported separately because it is upstream 3rd-party content, not project data.
- Bounded scope: no system-wide recursive scan; only `/backup/github` was read.

## 3. Findings (risk only — no secret values recorded)

### 3.1 LIVE hardcoded secrets found and REMEDIATED in archive copies

| # | Archive file | Source file | Risk type | Disposition |
|---|--------------|-------------|-----------|-------------|
| 1 | `projects/Memory-Gateway/claude_bridge.py` | `/ai/Memory-Gateway/claude_bridge.py` | 2 hardcoded `sk-` API keys (`LITELLM_KEY`, `CLIENT_KEY`) | Sanitized → placeholders |
| 2 | `projects/ai_dxos/configs/litellm_config.yaml` | `/ai/ai_dxos/configs/litellm_config.yaml` | 8 `api_key: sk-...` entries (one `sk-xxx` dummy) | Sanitized → `sk-REPLACE_WITH_LITELLM_KEY_M00_FROM_VAULT` |
| 3 | `projects/ai_dxos/scripts/sync_openwebui_models.py` | `/ai/ai_dxos/scripts/sync_openwebui_models.py` | Hardcoded OpenWebUI login **email + numeric password** in a curl payload | Sanitized → env placeholders |
| 4 | `projects/Memory-Gateway/search_modules/weather_adapter.py` | `/ai/Memory-Gateway/search_modules/weather_adapter.py` | Hardcoded 和风天气 (qweather) API key as `os.getenv` default + private `devapi.qweather.com` host | Sanitized → default replaced; host made env-configurable |
| 5 | `projects/dxos_pilot/frontend/index.html` | `/ai/dxos_pilot/frontend/index.html` | 1 `sk-` LLM-gateway key repeated across 7 client config snippets (lines 1968–1975) | Sanitized → `REPLACE_WITH_PILOT_LLM_GATEWAY_KEY` |
| 6 | `projects/Memory-Gateway/fastapi_gateway.py` | `/ai/Memory-Gateway/fastapi_gateway.py` | 10 hardcoded credentials in the memory-gateway service code | Sanitized → placeholders (10 replacements; copy shrank 139544→139402 B) |
| 7 | `projects/Memory-Gateway/window_budget.py` | `/ai/Memory-Gateway/window_budget.py` | (verified at copy; see §8 — no live key found) | No change needed |

> NOTE (item 4): this matches the previously-logged EXTRACT_B risk (qweather key `4981d9...` + private host). It is now removed from the archive copy.
> NOTE (item 6): `fastapi_gateway.py` was root:600 and unreadable to the working user; it was copied and sanitized by the user (root). I confirmed its size (139402 B) and its manifest hash entry, but **could not re-read the content myself** — the 10-remediation count is as reported by the user and cross-checked against the size delta.

### 3.2 Benign / no-action findings

- `projects/ai_dxos/scripts/safe_switch.sh` line 27: `Authorization: Bearer ***` — **valueless placeholder** (no key value present). Left unchanged.
- `Memory-Gateway/litellm_config.yaml` and all `docker-compose.*.yml`: use env vars (`${PILOT_KEY_M00}`, `${MEM0_ADMIN_KEY}`, `sk-dummy`, etc.). No live secrets. Left unchanged.
- `vendor/mem0-main/integrations/*/tests/*` (2 files): contain **test fixtures** with obviously-fake values (`ghp_abcd...`, `sk-abcd...`, `BEGIN PRIVATE KEY` in unit-test strings). 3rd-party upstream test data, not real credentials. **Not** sanitized (vendor = upstream; not project data).
- No `ghp_`/`AKIA`/Slack/JWT/private-key **real** values found anywhere in non-vendor files.

### 3.3 Residual-secret re-scan after sanitization (non-vendor)

Re-scan across all non-vendor files for `sk-` (len≥16), qweather key, OpenWebUI email, numeric password, `ghp_`/`AKIA`/Slack/JWT/private-key blocks:

- **Result: 0 real secrets remaining.** The only `sk-` detector hit is the valueless `Bearer ***` placeholder in `safe_switch.sh` (see 3.2).

## 4. Sanitized Files (list)

Six archive copies were modified (placeholders substituted for secrets). The first five were verified to be byte-identical copies of their `/ai` source **before** editing. The sixth (`fastapi_gateway.py`) was sanitized by the user (root) after copy; content not re-read by the working user.

| Archive file | Replacements |
|--------------|-------------|
| `projects/Memory-Gateway/claude_bridge.py` | 2 |
| `projects/ai_dxos/configs/litellm_config.yaml` | 8 |
| `projects/ai_dxos/scripts/sync_openwebui_models.py` | 2 (email + password) |
| `projects/Memory-Gateway/search_modules/weather_adapter.py` | 1 (key) + host→env |
| `projects/dxos_pilot/frontend/index.html` | 8 (one key, 7 occurrences) |
| `projects/Memory-Gateway/fastapi_gateway.py` | 10 (user-sanitized) |

The first five now contain `REPLACE_WITH_*` / `REPLACE_FROM_*` placeholders and pass the residual-secret re-scan (CLEAN). The sixth's sanitized state is as reported by the user (content unreadable to the working user).

## 5. Exclusions Verification (content not suitable for Git)

| Excluded category | Count in archive | Status |
|-------------------|------------------|--------|
| `.git/` directories | 0 | OK — none present |
| `node_modules/` | 0 | OK — none present |
| Virtualenvs (`venv`/`.venv`/`env`) / `site-packages` / `__pycache__` / `*.pyc` | 0 | OK — none present |
| Model weights (`.safetensors`/`.gguf`/`.ckpt`/`.pt`/`.pth`) | 0 | OK — none present |
| Databases (`.db`/`.sqlite`/`.sqlite3`) | 0 | OK — none present |
| `.env` / dotenv files | 0 | OK — none present (configs use env-var *references*, no `.env` file committed) |
| `.bak.*` historical backup files | 0 | OK — none present in archive |
| Files > 100 MB | 0 | OK — none (largest cluster is text) |
| Logs / core dumps | 0 (non-vendor) | OK — none present |

> Source-side note (read-only observation, NOT in archive): `/ai/ai_dxos/docker/docker-compose.yml.bak` exists in the **source** but was correctly NOT copied into the archive. No action required in the archive.

## 6. Anomalous File (documented, NOT deleted/renamed)

| Field | Value |
|-------|-------|
| Archive path | `projects/ai_dxos/docker/{m[litellm_params][model]})\n` |
| **Actual name** | The filename ends with a **trailing newline** (`...{model]})` + `\n`), plus literal `{ } [ ]` braces. This is why naive `cp`/`find`/`sha256sum -c` mishandled it. |
| Size | 147 bytes |
| Mode | `0o100775` (100755) |
| SHA256 (archive) | `8d4655be837b62526fc3f02656eaa1b228c7eb7096b55fdf7102980976563cdf` |
| Source counterpart | `/ai/ai_dxos/docker/{m[litellm_params][model]})\n` — **exists, identical 147 bytes, identical SHA256** |
| Content type | A Python **`SyntaxError` traceback** (ANSI-colored), e.g. `File "<string>", line 7 / print(f / SyntaxError: '(' was never closed` |

**Conclusion:** This is junk left in the *source* directory by an earlier unquoted shell/Python script that wrote an error trace to a file whose name came from an unexpanded shell variable. The archive is a **faithful copy** of the source (identical bytes + hash). Per instructions it was **not** deleted or renamed; it is recorded here. The matching source file is flagged to the owner for optional cleanup on the source side (out of scope — source is read-only here).

Because the filename contains a trailing newline, `sha256sum -c` cannot parse that one line; it is verified separately (see §7).

## 7. SHA256 Verification

- Manifest: `/backup/github/manifests/SHA256SUMS.txt` — **2581 entries** (sha256sum-compatible format; special chars escaped; manifest excludes itself).
- The 2581 entries cover every on-disk file **except** `docs/security_audit.md` (a live document, intentionally not self-hashed) and the manifest itself.

### Verified as the working (`paxen`) user

`sha256sum -c manifests/SHA256SUMS.txt` run as `paxen`:

| Result | Count | Notes |
|--------|-------|-------|
| 成功 (PASS) | **2578** | All ordinary files the working user can read |
| 权限不够 (permission denied) | 2 | `fastapi_gateway.py`, `window_budget.py` — root:600, unreadable to paxen |
| 无法解析/格式警告 (parse warning) | 1 | the trailing-newline-named file from §6 (`sha256sum` cannot parse that path) |

So **2578 files are directly verified by `sha256sum -c`** as the working user. The 3 remaining are handled below:

- **Trailing-newline file (§6):** verified separately via direct Python hash — actual SHA256 `8d4655be837b62526fc3f02656eaa1b228c7eb7096b55fdf7102980976563cdf` **matches** the manifest entry. ✅
- **`fastapi_gateway.py` + `window_budget.py`:** unreadable to paxen (root:600). Their manifest hashes are recorded (`459eda43…` / `d386773f…`), sizes confirmed (139402 B / 4750 B). **Full hash verification of these two must be run as root** (see §8). Not independently re-verified by the working user.

### Verified as root (user-confirmed)

Running `sha256sum -c manifests/SHA256SUMS.txt` as **root** (which can read the two root:600 files) is expected to yield **2580 PASS + 1 parse-warning** (the newline-named file). The user reported: OK 2580, FAILED 0, Missing 0, Malformed 1. The one "Malformed" is the §6 newline-named file's unparseable line — it is present on disk and hash-confirmed, so it is **not** a missing or corrupted file.

**Honest status:** 2579 of 2581 manifest entries are verified by the working user (2578 by `sha256sum -c` + 1 by direct Python hash). The final 2 (`fastapi_gateway.py`, `window_budget.py`) are verified by the user as root, not by the working user.

### Source-integrity spot check (the 5 working-user-sanitized files)

Each sanitized archive copy **differs** from its (unchanged) `/ai` source, exactly as expected — confirming the source was not touched and the archive copy is the one that was cleaned.

| Archive file | Archive SHA256 (cleaned) | Source SHA256 (unchanged) |
|--------------|--------------------------|---------------------------|
| `claude_bridge.py` | `345b8e74...` | `d87ef69a...` |
| `ai_dxos/configs/litellm_config.yaml` | `105155e2...` | `af950075...` |
| `sync_openwebui_models.py` | `0088f919...` | `04817fb5...` |
| `weather_adapter.py` | `ae0deff3...` | `3e81e288...` |
| `dxos_pilot/frontend/index.html` | `407f5c46...` | `e3c7c02c...` |

Full SHA256 values are in `manifests/SHA256SUMS.txt`.

## 8. Two Previously-Blocked Files — COPIED, SANITIZED, IN MANIFEST

The two files skipped in earlier phases (root:600, unreadable to the working user) have now been:

1. **Copied** into the archive by the user (root).
2. **`fastapi_gateway.py` sanitized** by the user (root): 10 hardcoded credentials removed; the archive copy shrank from 139544 B to **139402 B**.
3. **`window_budget.py`**: no live key found; left as-is.
4. **Added to `manifests/SHA256SUMS.txt`** (2 entries).

| Archive path | Size now | Mode | Owner | Manifest SHA256 |
|--------------|----------|------|-------|-----------------|
| `projects/Memory-Gateway/fastapi_gateway.py` | 139402 B | `0600` | `root:root` | `459eda43a4be53519d55c4100b38eddaa80c6f3de3837f30458736c586981164` |
| `projects/Memory-Gateway/window_budget.py` | 4750 B | `0600` | `root:root` | `d386773f9bc5a625fe87a281245fd851ebd2612efc33604f3ef461393e34ceb8` |

**Verification limitation (stated honestly):** both files are `0600 root:root`, so the working (`paxen`) user **cannot read them** and therefore could not (a) independently scan their content for secrets, (b) independently compute their SHA256, or (c) re-confirm the 10-remediation count. I verified their **size, mode, ownership, presence, and manifest entry**. The content-level scan + hash confirmation were done by the user as root. To close this gap from the working-user side, one of:

```
# Option A — let the working user read them (keeps root owner, adds group/other read):
chmod 644 /backup/github/projects/Memory-Gateway/fastapi_gateway.py \
          /backup/github/projects/Memory-Gateway/window_budget.py
# then the working user can re-run the secret grep + sha256sum and record it here.

# Option B — as root, confirm the hashes match the manifest:
sha256sum /backup/github/projects/Memory-Gateway/fastapi_gateway.py \
          /backup/github/projects/Memory-Gateway/window_budget.py
```

## 9. Outstanding / Not Done

- **Working-user verification of `fastapi_gateway.py` + `window_budget.py`** content + hash: pending, blocked by `root:600` (see §8 for the two one-line options). This is the sole remaining local gap; everything else is complete and verified.
- `verified_backup_v6.0.sh` **was not executed** (excluded from runtime by instruction). It is present in the archive as a copied file; its content was not run.
- No `git init`, no GitHub login/push, no install, no service/system config changes. **The archive has NOT been pushed to GitHub.**
- Vendor test fixtures (§3.2) intentionally left as upstream (not project data).
