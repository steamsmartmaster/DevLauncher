# Version Isolation Refactoring Plan

## Root Cause Analysis

### Issue 1: Modpack imports don't enable version isolation
**File**: `launcher_core/modpack_importer.py`
- `_import_curseforge()` (line 301-302): Creates `versions/VERSION_NAME/mods/` but never calls `enable_version_isolation()`
- `_import_modrinth()` (line 429-432): Same problem
- `_import_multimc()` (line 567-568): Same problem
- **Result**: `devlauncher.cfg` is never written with `isolation: true`, so `is_version_isolated()` returns `False`

### Issue 2: `get_mods_path()` always returns global path
**File**: `launcher_core/versions.py` (line 322-326)
- Checks `is_version_isolated()` which reads `devlauncher.cfg`
- Since importer never writes it, always returns `.minecraft/mods/`

### Issue 3: `loadModsFromLauncher()` passes empty string
**File**: `ui/index.html` (line 3019-3023)
- `pythonInterface.loadMods('')` → Python line 1486: empty string is falsy → falls back to global path
- This is correct for the global sidebar page, but needs to be fixed for version-specific pages

## Fixes

### Fix 1: Enable isolation after modpack import (Critical)
**File**: `launcher_core/modpack_importer.py`
- After creating `mods_dir` in `_import_curseforge`, `_import_modrinth`, and `_import_multimc`, call `enable_version_isolation(version_name)` to write `devlauncher.cfg` with `isolation: true`

### Fix 2: Make `get_mods_path()` smarter (Fallback)
**File**: `launcher_core/versions.py`
- If `is_version_isolated()` is False, check if `versions/VERSION_NAME/mods/` exists and has content → prefer it over global path
- This is a defensive fix for modpacks imported by older launcher versions

### Fix 3: Auto-detect modpack versions for isolation
**File**: `launcher_core/versions.py`
- When loading version settings, detect if the version is a modpack (has `inheritsFrom` + loader libraries) → auto-set isolation
- Similar to HMCL's `beingModpackVersions` pattern
