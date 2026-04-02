# Code Review: LTX-2 Training Data Extractor

**Date:** 2026-04-02 (updated 2026-04-02)  
**Review Type:** Comprehensive Code Analysis  
**Scope:** CLI entry point, database operations, scene detection, captioning pipeline

---

## Architecture & Code Quality

### Strengths

1. **Well-structured CLI** (`ltx2_dataset_builder/cli.py:1-463`)
   - Clean argument parsing with sensible defaults
   - Comprehensive help text and usage examples
   - Support for both full pipeline and individual steps

2. **Modular design**
   - Each pipeline step has its own module (scenes, captions, buckets, candidates, faces, crops, render, manifest)
   - Separation of concerns is clear

3. **Incremental processing** (`scenes/detect.py:84-112`)
   - Scene detection flushes every ~10s chunk
   - Prevents data loss on interrupt

4. **Idempotent operations** (`cli.py:287-289`)
   - `skip_existing` config prevents reprocessing

### Issues Found

#### 1. SQL Injection Risk (`utils/io.py:439`)

```python
conn.execute(
    f"UPDATE candidates SET {', '.join(updates)} WHERE id = ?",
    params
)
```

Building SQL with f-string is risky even though values are parameterized. Column names should be whitelisted.

**Impact:** Low - column names come from internal code, not user input  
**Recommendation:** Whitelist allowed columns:

```python
ALLOWED_UPDATE_COLS = {"quality_score", "face_presence", "status"}
if col not in ALLOWED_UPDATE_COLS:
    raise ValueError(f"Invalid column: {col}")
```

#### 2. Missing `rating` Column Schema (`scenes/detect.py:182`)

The `add_scenes` call inserts a `rating` field but the schema was missing the ALTER statement.

**Impact:** Pipeline would fail on fresh database  
**Status:** ✅ Fixed - added `ALTER TABLE scenes ADD COLUMN rating INTEGER DEFAULT 2` in `utils/io.py:85-90`

#### 3. Error Swallowing in Bucket Writing (`utils/io.py:590-592`)

```python
except Exception as e:
    logger.error(f"Failed to add bucket: {e}")
    continue
```

Broad `Exception` catches can hide real programming errors like type errors or attribute errors.

**Impact:** Debugging becomes difficult - bugs get masked as "failed to add bucket"  
**Recommendation:** Catch specific exceptions:

```python
except sqlite3.Error as e:
    logger.error(f"Database error adding bucket: {e}")
except (KeyError, TypeError) as e:
    logger.error(f"Invalid bucket data: {e}")
    raise  # Re-raise programming errors
```

#### 4. No Timeout for Caption API Calls

VLM captioning in `captions/generate.py` has no timeout. The model can hang indefinitely if it doesn't respond.

**Impact:** Pipeline can stall silently  
**Recommendation:** Add timeout to API calls:

```python
response = client.chat.completions.create(
    ...
    timeout=300  # 5 minute timeout per scene
)
```

---

## Performance

| Area | Assessment | Notes |
|------|------------|-------|
| ThreadPoolExecutor | **Good** | Parallel blurhash/thumbnail generation (`scenes/detect.py:180-192`) |
| Server-side pagination | **Good** | Web review API uses 100 scenes/page |
| get_scenes_without_caption | **Concern** | Fetches all scenes at once - could be chunked for large datasets |
| Database connections | **Good** | Context manager properly closes connections |

---

## Security

1. **FFmpeg injection** (`captions/generate.py`): Verify no shell injection when passing file paths to FFmpeg - use `subprocess` with list args instead of `shell=True`

2. **No input validation** on frame offset values (`cli.py:386-413`) - negative values could cause frame calculation issues

3. **File path traversal** - no validation that output paths stay within expected directories

---

## Testing

**Tests added:**
- `tests/test_captions_generate.py` - 25 unit tests for VLM captioning module

**Coverage:**
- Prompt building (default, custom, tags)
- Time utilities (UTC formatting)
- Clip extraction (success/failure, FFmpeg args, timeout, edge cases)
- Input preparation (frame offset, tags, failure handling)
- Scene selection (filtering, prioritization, sentinel handling)
- Metadata retrofit (backfilling timestamps)

**Remaining gaps:**

1. **Unit tests** for scene parsing (`scenes/detect.py`)
2. **Integration tests** for individual pipeline steps
3. **Database tests** for schema initialization and migrations
4. **Tests** for buckets, candidates, faces, crops, render modules

## Documentation

| Area | Status |
|------|--------|
| CLI help text | ✅ Good |
| API docs | ⚠️ Missing for `Database` class methods |
| Algorithm docs | ⚠️ No inline docs for complex bucket detection algorithm |

---

## Recommendations Summary

| Priority | Action | Files | Status |
|----------|--------|-------|--------|
| High | Add column whitelist for dynamic SQL queries | `utils/io.py` | Pending |
| High | Add `rating` column to schema | `utils/io.py` | Pending |
| High | Add timeout to caption API calls | `captions/generate.py` | Pending |
| Medium | Narrow exception handling in bucket writing | `utils/io.py` | Pending |
| Medium | Add tests for critical pipeline paths | (new files) | Done |
| Low | Document bucket detection algorithm | `buckets/detect.py` | Pending |

**Completed:**
- Created 25 unit tests for VLM captioning module in `tests/test_captions_generate.py`

---

## Files Reviewed

- `ltx2_dataset_builder/cli.py` - Main entry point
- `ltx2_dataset_builder/utils/io.py` - Database operations
- `ltx2_dataset_builder/scenes/detect.py` - Scene detection
- `ltx2_dataset_builder/config.py` - Configuration
- Pipeline step modules (captions, buckets, candidates, faces, crops, render, manifest)
