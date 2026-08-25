# Database Storage Cleanup — 2026-08-25

**Problem:** rtr-deeplink-db exceeded 90% storage (Render alert)

**Root cause:** `meeting_page_thumbnails` storing up to 12 frames per page × ~1200 pages = 14,400+ JPEGs

**Solution:** Lower MAX_FRAMES_PER_PAGE to 3, delete old thumbnails, vacuum

---

## Steps to Execute

### 1. Verify the Problem (optional)

Run the diagnostic script first to see the actual breakdown:

```bash
# From Render dashboard:
# 1. Click Archive service
# 2. Click "Shell"

cd /app
python scripts/analyze_db_storage.py
```

This shows table sizes, thumbnail count, and potential savings.

---

### 2. Deploy Code Change (MAX_FRAMES_PER_PAGE = 3)

The code change is already committed — this lowers the cap for *future* extractions:

```bash
# Locally, verify it's in place:
grep "MAX_FRAMES_PER_PAGE = " archive/utils/video_thumbnail.py
# Should show: MAX_FRAMES_PER_PAGE = 3

# Then commit and push to main (if not already done)
git add archive/utils/video_thumbnail.py
git commit -m "Lower MAX_FRAMES_PER_PAGE to 3 (WO-60)"
git push origin main
```

**This step:** Prevents *new* thumbnails beyond 3 per page. Already-stored frames stay until cleanup.

---

### 3. Run Cleanup Script (Delete Old Thumbnails)

**First: dry run** to see what would be deleted:

```bash
# From Render shell (Archive service)
cd /app
python scripts/cleanup_old_thumbnails.py --keep 3 --dry-run
```

This shows:
- How many pages have excess thumbnails
- How much storage would be reclaimed
- **Does not delete anything**

**Then: actually delete** (once you've verified the numbers):

```bash
cd /app
python scripts/cleanup_old_thumbnails.py --keep 3
```

This keeps only the 3 most recent frames per page and deletes the rest.

**Expected result:** Reclaim 300-500 MB (depending on how many pages have excess frames)

---

### 4. VACUUM the Database

After deleting rows, tell Postgres to reclaim disk space:

```bash
# From Render shell (Archive service)
cd /app
psql << 'EOF'
VACUUM FULL ANALYZE;
EOF
```

Or via Python:

```bash
python -c "
import asyncio
from archive.db.engine import get_async_engine
from sqlalchemy import text

async def vacuum():
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.execute(text('VACUUM FULL ANALYZE'))
        print('✓ VACUUM FULL ANALYZE complete')

asyncio.run(vacuum())
"
```

**Expected result:** Shrinks database file size to match actual data

---

### 5. (Optional) Deploy a Render Update

Once cleanup is done, trigger a Render deploy so the new `MAX_FRAMES_PER_PAGE = 3` takes effect:

```bash
# Locally:
git log --oneline | head -1  # verify the change is on main
```

Then go to Render dashboard → Archive service → Manual Deploy

(Normally deploys are manual per CLAUDE.md WO-59, so just request one)

---

## Verification

After cleanup, check storage:

```bash
# From Render shell
python scripts/analyze_db_storage.py
```

You should see:
- Total database size reduced ~300-500 MB
- meeting_page_thumbnails count down to ~1200-3600 rows (1-3 per page)
- No table exceeding 90% usage

---

## What Happens to Users

✓ **Minimal impact:**
- Default thumbnail (no `?t=` parameter) — unchanged
- Shared links with `?t=` timestamp — fall back to default frame if their specific offset was deleted
- Social media cards — use the default, unchanged
- No data loss for Archive, just pruned old frames

---

## Rollback (if needed)

The only destructive step is the cleanup script. To rollback:

1. Stop and do not run the cleanup script
2. Revert `MAX_FRAMES_PER_PAGE` to 12
3. Run a database restore from a snapshot if you need the deleted thumbnails back

The database snapshots are kept by Render for 7 days.

---

## Timeline

- **Now:** Deploy code (MAX_FRAMES_PER_PAGE = 3)
- **After deploy:** Run cleanup script (30 seconds to a few minutes depending on database size)
- **After cleanup:** VACUUM (5-10 minutes, no downtime)
- **Result:** Database storage drops to ~60-70% of limit
