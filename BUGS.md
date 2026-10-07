# Bug review — 2026-10-07

Code review of the whole project, including the uncommitted scheduler change (posts are now created on WordPress as `future` right when you schedule them). The 280 tests pass, so none of these is covered by a test.

Ordered by severity. Tick each box when fixed.

**Status:** all 30 bugs are fixed (ticked), along with P1–P4, P6–P8, I1, I2 and I4. P5 (database indexes) was skipped by choice, and I3 (offline wheelhouse) is optional. 307 tests pass.

---

## Critical: uncommitted scheduler change

- [x] **1. Deleting or cancelling an old schedule changes the live post.**
  `core/scheduler.py:281-367` (`cancel_scheduled_job`, `delete_scheduled_job`)
  Neither function checks the job's status. Deleting a *completed* schedule row in the Scheduler tab moves the live post to the WordPress trash. Cancelling one turns a published post back into a draft.
  **Fix:** only call WordPress when `job.status == "pending"`. For other jobs, only remove or update the DB row.

- [x] **2. Cancel and delete never reach WooCommerce products.**
  `core/scheduler.py:302`, `:351`
  The code picks the scope with `"product" in post_type.lower()`. The Create tab passes `"Sản phẩm WooCommerce"`, which doesn't contain "product", so the request goes to `/wp/v2/posts/{id}` and gets a 404. That 404 is only logged: the job is marked cancelled and the product still goes live.
  **Fix:** use `taxonomy_service.scope_for_post_type(job.post_type)`.

- [x] **3. A schedule set to "draft" now publishes publicly.**
  `core/scheduler.py:181`, `:212`
  `schedule_publish_job` ignores its `post_status` argument and always creates and stores `"future"`. The UI still says the post will be posted as a draft. In the fallback path, `ok_status` becomes `"draft"` because the status is `"future"`, so the history says draft for a post WordPress published.
  **Fix:** only create a `future` post when the user chose `publish`. For `draft`, keep the old behaviour of running the job at the scheduled time.

- [x] **4. Partial failures are reported as success.**
  `core/scheduler.py:56` (`has_future_posts = any(...)`), `services/schedules.py:82-93`
  If any one site has a `post_id`, the whole job becomes "completed". Sites that failed when you scheduled are never retried, and the UI shows success.
  **Fix:** look at each site's result. Mark the job `partially_completed` or `failed` as appropriate, retry failed sites in the fallback path, and show the per-site errors in the UI.

- [x] **5. Edits to a pending schedule never reach WordPress.**
  `services/schedules.py:186-301` (`_write_job_art`, `save_job_categories`, `save_job_tags`, `suggest_for_job`)
  These only rewrite `article_data_json`. The WordPress post already exists with the old categories and tags.
  **Fix:** when the job has a `post_id`, also update the post on WordPress.

- [x] **6. Cancel fails silently.**
  `core/scheduler.py` (`cancel_scheduled_job`)
  - If a site was renamed after scheduling, `all_configs.get(old_name)` returns `None` and the WordPress step is skipped.
  - If `update_item_status` fails, the error is only logged.

  In both cases the job is marked "cancelled" while WordPress still publishes the post.
  **Fix:** store the site ID instead of the name, and return an error to the UI if reverting the post on WordPress fails.

- [x] **7. History status goes stale or is missing.**
  - `init_scheduler`: overdue jobs that have a `post_id` are marked completed, but their history rows stay `"scheduled"`. `execute_scheduled_job` does update them.
  - The new `"scheduled"` status is missing from `ui/tab_history.py` (`_STATUS_FILTERS`, `_STATUS_LABELS`), `services/dashboard.py` (`BUCKET_OF`, where it counts as "saved") and `services/sync.py` (`SYNCABLE_STATUSES`).
  - Jobs are marked "published" without checking WordPress, and WordPress's built-in scheduler (WP-Cron) often misses times on low-traffic sites.

  **Fix:** share one helper between both paths. Optionally, GET the post to confirm `status == "publish"`.

- [x] **8. Schedules are skipped if the Mac is asleep at the scheduled time.**
  `core/scheduler.py:265`, `:382`
  `add_job` has no `misfire_grace_time`, so APScheduler's 1-second default applies and late runs are dropped. The job stays "pending" until the next restart.
  **Fix:** pass `misfire_grace_time=None` (or a large value) and `coalesce=True`.

- [x] *(minor)* The `pending` update sets `executed_at=now_vn()` at scheduling time, so the "executed at" column is misleading.
- [x] *(minor)* If `create_scheduled_post` fails after `publish_articles`, the posts already created on WordPress are left orphaned.

---

## High

- [x] **9. Sites overwrite each other's images.**
  `core/image_processor.py:345-349`
  The output is always `data/processed_images/{stem}_optimized.webp`. `publish_articles` processes the same images for up to 4 sites at once, each with its own watermark, so one site can upload another site's logo or a half-written file. Files like `a.jpg` and `a.png` also collide.
  **Fix:** make the output filename unique, for example with the site name plus a uuid, or use a temp dir per call.

- [x] **10. Retries can create duplicate posts.**
  `core/wp_client.py:366`, `:474` (`_should_retry_http`)
  The POST that creates a post or product is retried on timeouts and 5xx errors. If WordPress already created the item before the timeout, the retry creates a second one.
  **Fix:** don't retry creates on read timeouts. Alternatively, look up the item by slug or title before retrying.

- [x] **11. All preview images are broken.**
  `ui/preview.py:19`
  `<img src="/file=...">` returns 404 in Gradio 6, which needs the `/gradio_api/file=` prefix. Images in `data/post_images/` would still return 403, because `app.py` doesn't pass `allowed_paths` to `launch()`.
  **Fix:** use the `/gradio_api/file=` prefix and pass `allowed_paths=[DATA_DIR]`.

- [x] **12. Images can land in the wrong spots.**
  `core/wp_client.py:289`, `:574-578`
  Failed uploads are dropped from the list, so the remaining images shift up. If image 2 fails, `[IMAGE_PLACEHOLDER_2]` shows image 3. The featured image can shift too.
  **Fix:** keep a placeholder (such as `None`) in each failed slot and skip it when rendering.

- [x] **13. Clicking a history row can open a different post.**
  `ui/tab_history.py:568-577`
  The click handler re-fetches the data and uses `evt.index[0]`. If posts were added or removed since the table rendered, you may edit or publish the wrong one.
  **Fix:** read the ID from `evt.row_value`, as `ui/tab_scheduler.py:155` already does.

- [x] **14. A post's stored type isn't updated when it's published as a different type.**
  `services/posts.py:258-269` (`publish_saved_post`)
  `h.post_type` isn't updated. Later, `refresh_statuses`, trash, link and "update existing" hit the wrong endpoint and mark the post "missing".
  **Fix:** set `h.post_type = post_type` after a successful publish.

- [x] **15. Published posts store temporary image paths.**
  `services/publishing.py:74`, `:97` (`publish_and_record`)
  It skips `persist_images`, unlike `save_drafts` and `schedule_post`. Once Gradio's temp folder is cleaned, re-publishing from the Kho tab posts with no images.
  **Fix:** call `image_service.persist_images()` before recording the paths.

---

## Medium

- [x] **16. The bulk tab's website list gets wiped.** `ui/main_ui.py:439-448`
  A bare `gr.update()` is a dict in Gradio 6, so `choices` and `value` default to `[]`. A failed site validation or an empty delete selection clears the Hàng loạt (bulk) tab's website list.
- [x] **17. Per-site time pickers are fixed at startup.** `ui/main_ui.py:325`, `ui/tab_create.py:473-479`, `:287-288`
  A site added or renamed later has no picker and is silently left out of per-site scheduling.
- [x] **18. Per-site scheduling isn't all-or-nothing.** `services/schedules.py:330-336`
  If one site's time is invalid, the earlier sites' jobs are kept. Resubmitting creates duplicates.
  **Fix:** check all times before creating any job.
- [x] **19. The fast search path saves no time.** `core/searcher.py:139-182`
  The `with ThreadPoolExecutor` block waits for both searches on exit, so the short timeouts save nothing. DuckDuckGo results that arrive after about 2.5 seconds are thrown away, even when SerpAPI returned nothing.
  **Fix:** use `executor.shutdown(wait=False)`.
- [x] **20. AI output can be `None`.** `core/ai_writer.py:153`, `:182`
  `response.text` can be `None` (safety block or output cut off by the token limit), which raises `AttributeError` and isn't retried.
- [x] **21. Custom templates with braces crash.** `core/ai_writer.py:140`
  A template containing literal `{` or `}`, such as CSS, crashes in `.format()`.
  **Fix:** use `string.Template` or targeted `.replace()` calls.
- [x] **22. The saved-posts status filter runs after the row limit.** `services/posts.py:132-134`
  Status filtering happens in Python after `limit=200`, so older failed posts never show.
  **Fix:** filter in the SQL query.

## Low

- [x] **23. Watermark opacity 0 becomes 0.7.** `services/sites.py:143`, `services/images.py:28`
  `x or DEFAULT` replaces 0 with the default. Check `x is None` instead.
- [x] **24. `LOGOS_DIR` depends on the working directory.** `services/sites.py:23`
  `Path("data")/"logos"` is relative to the CWD. Use `DATA_DIR`.
- [x] **25. The `sites.json` import can lose a site.** `db/crud.py:227-238` (`migrate_from_json`)
  It counts failed inserts as done and renames `sites.json` to `.bak` anyway, so a failed site is silently lost.
- [x] **26. Stop on macOS/Linux leaves child processes running.** `launcher/core.py:193-194`
  `kill_process_tree` only calls `terminate()`, so the share tunnel (frpc) keeps running.
  **Fix:** use `start_new_session=True` and `os.killpg`.
- [x] **27. One failing step freezes the launcher window.** `launcher/gui.py:153-170`
  If a `done` callback raises in `_pump`, `after()` is never rescheduled.
  **Fix:** wrap the callback in try/finally.
- [x] **28. Closing the launcher during install leaves processes running.** `launcher/gui.py:332-338`
  `pip`/`venv` keep running, and the app may still start after the window is gone.
- [x] **29. The app and launcher can disagree on the port.** `app.py:91` vs `launcher/core.py:217`
  A `PORT` in the system environment overrides `.env` for the app but not for the launcher, so startup times out after 300 seconds.
- [x] **30. The Remote tab resets your site choice.** `ui/tab_remote.py:51-53`
  The selected site goes back to the first one every time the tab is opened.

---

## Found while fixing (all fixed)

- [x] On startup, `init_scheduler` reloaded at most 100 pending jobs (the default limit of `crud.get_scheduled_posts`), so a large batch schedule silently lost the rest after a restart.
- [x] A job left `running` when the app was closed mid-run stayed stuck; on startup it is now marked failed.
- [x] **Windows:** the launcher's `.env` reader didn't handle Notepad's UTF-8 BOM. A first-line `PORT` was read as `\ufeffPORT`, so the launcher polled the wrong port. ANSI-encoded `.env` files crashed it with `UnicodeDecodeError`.
- [x] `DEFAULT_PROCESSED_DIR` was relative to the working directory, and a `data/` folder was created in whatever directory the module was imported from. It now uses `DATA_DIR`.

## Notes on the fixes

- **Scheduling with "publish"** creates a `future` post on WordPress right away. When the time comes, the app checks the post, and if WordPress missed its schedule (WP-Cron only runs on page visits) it pushes the post to `publish`. Sites that failed at scheduling time are retried then, and their errors are shown in the Create tab.
- **Scheduling with "draft"** doesn't touch WordPress until the scheduled time (the old behaviour).
- **Cancel and delete** only touch WordPress for *pending* jobs. If WordPress can't be reached, the job stays pending and the UI shows the error, so you can retry.
- **Jobs now store `site_id`**, so cancel, retry and history keep working after a site is renamed.
- **Overdue jobs after a restart** have their WordPress posts confirmed, but sites with no post are marked as missed, not published late (same policy as before).
- **Still open:** `services/sync.py` doesn't sync rows with status `scheduled`. They are updated by the scheduler itself.

## Suggested order

1. Scheduler 1–4, 6 and 8. These can publish, unpublish or trash posts you didn't mean to.
2. Items 9 and 10 (wrong watermarks, duplicate posts).
3. Items 11–15.
4. Everything else.

Add tests for the scheduler fixes, starting with `tests/test_service_schedules.py`: cancel or delete of a completed job, the product scope, a draft schedule, and a partial failure.

---

## Performance (review 2026-10-07)

- [x] **P1. Search waits for the slowest provider, so the short timeouts do nothing.** `core/searcher.py:139-183`
  The `with ThreadPoolExecutor` block waits for both futures on exit, so each article generation waits up to about 8 s, even when SerpAPI answered in 0.3 s (same root cause as #19).
  **Fix:** create the executor without `with` and call `executor.shutdown(wait=False, cancel_futures=True)` in a `finally`, as `services/dashboard.py:check_sites` already does.
- [x] **P2. Gemini calls have no timeout.** `core/ai_writer.py:36-51`
  One stalled connection hangs the whole multi-site generation forever.
  **Fix:** use `types.HttpOptions(timeout=120_000)` (milliseconds) and cache one client per (key, base_url).
- [x] **P3. rembg reloads its model for every image.** `core/image_processor.py:96`
  `rembg.remove()` is called without `session=`, so each image loads about 170 MB of model, and up to 16 loads can run in parallel (4 sites × 4 images). That's a real risk of running out of memory on Windows PCs.
  **Fix:** keep one shared session behind a lock, and remove the background once per image instead of once per site.
- [x] **P4. The dashboard loads every history row, including `raw_html`.** `services/dashboard.py:103`
  Measured with 5,000 posts: 87 ms and about 150 MB pulled into Python; a column-only query takes 8 ms.
  **Fix:** use GROUP BY queries, or select only the columns needed.
- [ ] ~~**P5. Indexes are missing.**~~ *Skipped: the user decided against adding database indexes.* `db/models.py`
  Queries scan all rows and use a temp B-tree for sorting.
  **Fix:** add these in a migration: `post_history(created_at)`, `post_history(site_id, created_at)`, `post_history(site_id, product_name)`, `scheduled_posts(status, scheduled_time)`.
- [x] **P6. The history tab fetches the same list twice per event.** `ui/main_ui.py:251/298/350`, `ui/tab_history.py`
  `fetch_history_data` and `get_history_post_choices` each run `list_posts` (16 queries, 200 full rows, plus `Path.exists()` for every image).
  **Fix:** fetch once, filter by status in SQL (see #22), and `defer(raw_html)`.
- [x] **P7. Image resizing does more work than needed.** `core/image_processor.py:186`
  **Fix:** call `img.draft("RGB", (max_w, max_h))` before the resize (about 40% faster on 12 MP JPEGs), and cache the opened watermark image.
- [x] **P8 (small).** Import `google.genai` lazily (saves about 0.1 s of startup). Startup now takes about 1.8 s; most of that is Gradio and can't be avoided.

## Install speed (measured 2026-10-07, macOS, Python 3.12, empty cache)

| Method | Time | Size of `site-packages` |
|---|---|---|
| `pip install -r requirements.txt` (current) | 73 s | 362 MB |
| `uv pip install -r requirements.txt` | 34 s | 260 MB (no `.pyc` compiling at install) |

Windows is usually slower than this for pip, because Defender scans every file as it is written, so uv's advantage is larger there.

- [x] **I1. Use uv in `install.bat` and `launcher/core.py:install`, falling back to pip.**
  Bootstrap with `py -m pip install uv` (one ~15 MB wheel), then run `uv venv .venv` and `uv pip install -r requirements.txt --python .venv\Scripts\python.exe`. It's about 2× faster on a first install. On a reinstall or update with the cache warm, it takes seconds.
- [x] **I2. Remove `pip install --upgrade pip` from every install run.** It isn't needed with uv, and with pip it's only worth doing when the install fails.
- [ ] **I3. Optional offline wheelhouse for slow connections.** Ship `wheels\` (built once on Windows with `pip download -r requirements.txt -d wheels`) in the release zip, and install with `--no-index --find-links wheels`. That means no downloads at all, at the cost of a zip about 120 MB bigger.
- [x] **I4. Add `tzdata; sys_platform == "win32"` to `requirements.txt` explicitly.** APScheduler needs it for `Asia/Ho_Chi_Minh` on Windows, and today it only arrives indirectly through pandas. `requirements.lock`, which was generated on macOS, doesn't include it at all.
- Note: your local `.venv` (533 MB) contains leftovers that `requirements.txt` doesn't install: `google-generativeai`, `googleapiclient` and `grpc` (about 140 MB). End users don't get these. Rebuild your dev venv to match.

### Installer results after I1/I2/I4 (macOS; not yet tried on a real Windows PC)

- `install.bat`, `install.sh` and the launcher now share one code path, `tools/install_deps.py` → `launcher.core.install`. They install uv into `.venv`, run `uv pip install` with `UV_LINK_MODE=copy` (safe for OneDrive and other drives), Windows certificates (`UV_SYSTEM_CERTS`) and parallel `.pyc` compiling, and fall back to pip automatically if uv fails.
- A fresh install takes 8–16 s with uv's cache warm (34 s cold), versus 73 s with pip. The pip fallback was tested by forcing uv to fail.
- The first app start after any install, pip or uv, takes about 14 s while the OS scans the new binaries (Gatekeeper on macOS, Defender on Windows). Later starts take about 1.3 s.

### Extra fixes made alongside the minor bugs

- [x] Reference text and user notes had their braces doubled before `.format()` (`{` became `{{` in the prompt sent to Gemini). Fixed by the single-pass `fill_template`.
- [x] `sites.json` is now read as `utf-8-sig`, so a BOM added by Windows Notepad doesn't break it.
- [x] The watermark logo is opened with `with` and cached. The file is never kept open, so on Windows it can still be replaced or deleted while the app runs.
