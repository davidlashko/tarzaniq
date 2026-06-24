# TarzanIQ 🦍📷

Street photo intelligence for camera-rental crews. Point it at a day's photo
folder and it figures out — from the photos alone — how many people each
photographer approached, how many said yes to a posed shoot, when, where, and
who. No cloud, no accounts: everything runs and stays on this Mac.

---

## Install (one time, ~5 minutes)

1. Put this `TarzanIQ` folder anywhere (Downloads is fine).
2. Open **Terminal**, type `bash ` (with the space), drag `install.sh` into
   the window, press **Enter**.
3. Wait for the ape. The installer creates the Python environment, downloads
   the four face models (~83 MB, checksum-verified), builds the
   **TarzanIQ.app** droplet and the Finder right-click action.

After install you can delete the downloaded folder — the app lives in
`~/Library/Application Support/TarzanIQ`.

## The daily flow

1. Copy the day's photos off the camera into a folder named:

   ```
   YY.MM.DD.Place.Name        →   26.06.07.CityPark.Marko
   ```

   The **date comes from the folder name** (cameras have the time right but
   often the date wrong). Place and name must match what you've used before —
   if TarzanIQ sees a new one it will ask whether it's really new or a typo.

2. Feed the folder to TarzanIQ, any of these ways:
   - **Right-click the folder** in Finder → Quick Actions → *Analyze with
     TarzanIQ*
   - **Drop the folder** onto **TarzanIQ.app**
   - Open the dashboard and click **+ Add day folder**

3. Watch the live view if you like (space = pause, ◀ ▶ = step through
   photos, Esc = back to live). A 2 000-photo day takes roughly **8–12
   minutes** on an M-series MacBook Air. You can queue several folders;
   they run one after another. The Mac won't nap mid-job.

4. At the end TarzanIQ asks for the day's **money** (one cash + one card
   number for the whole day — skip if you don't track it) and whether to
   **add the day to the dataset**. On yes: bananas fall, an Excel file with
   the same name as the folder appears in
   `~/Documents/TarzanIQ Data/exports`, and every chart updates.

## What the numbers mean

- **Cold shoot** — a new face, in focus, candid. Seven rapid frames of the
  same person still count as **one** cold shoot. Two people in the frame =
  two cold marks.
- **Warm shoot** — the same person showing up again at least 5 s after their
  candid (and within 10 min — later than that counts as a fresh re-approach).
  That's a sale of a posed shoot.
- **Conversion** = warm ÷ cold. **This is the headline score.** Cash totals
  can't be matched to shoots — and pockets leak — but a posed person in the
  photos is proof. Bananas don't lie.
- **Hunting** — average time between one mark and the next.
- **Pitch** — gap between someone's candid and their posed shoot starting.
- **Breaks** — gaps of 20+ min with no shooting; subtracted from "/hr" stats.
- **Suspected deletions** — jumps in the photo file numbering. Sony cameras
  roll 9999 → 0001; TarzanIQ knows.

All thresholds live in **Settings**, in plain language. Changing them
doesn't rewrite history until you press **Recompute** (no photos needed —
the numbers are re-derived from stored data, and the Excel files refresh).

## First run — 10-minute calibration

Faces, light and lenses differ. After your first processed day:

1. Open the day, skim the live frames you paused on (or re-run the folder)
   and check the overlays: green boxes should sit on *subjects*, not on
   passers-by in the background.
2. Too many background faces counted? Raise **Minimum face size** a notch.
   Sharp subjects being skipped? Lower the **Sharpness gate**.
3. One person being split into two marks → raise **Same-person strictness**
   value slightly; two people merging into one → lower it.
4. Glance at the gender split on a day you remember — if it looks off,
   trust the trend lines more than single days. Age buckets are coarse by
   nature (the model thinks in ranges like 25–32), good for patterns, not
   for ID.

## Where things live

```
~/Documents/TarzanIQ Data/
  tarzaniq.db      ← the dataset (source of truth)
  exports/         ← one styled Excel per day, named like the folder
  models/          ← the four downloaded face models
  backups/         ← automatic weekly DB copies (last 8 kept)
  logs/
```

- **Privacy:** photos are never copied and faces are never stored. Face
  fingerprints live only in RAM while a folder is processing; what's saved
  is numbers (times, counts, age/gender guesses). Person identities reset
  every day — "S3" on Tuesday has no link to "S3" on Wednesday.
- **Backups for free:** every Excel export carries the full day's data
  inside it. Lost the database? Settings → *Rebuild from Excel exports*.
- Reinstalling or updating the app never touches the data folder.

## If something's off

- **Right-click action missing** — relaunch Finder (⌥-right-click its Dock
  icon → Relaunch) or log out/in. The droplet app always works meanwhile.
- **"Folder name doesn't match"** — the name must be
  `YY.MM.DD.Place.Name`. Dots between, no spaces around them. Extra dots
  inside the place are fine (`26.06.07.City.Park.Marko` → place "City Park").
- **Dashboard won't open** — something else may be using port 43117. Check
  `~/Documents/TarzanIQ Data/logs/server.log`.
- **A model download failed** — rerun `install.sh`; finished models are
  skipped, broken ones are re-fetched and checksum-verified.
- **Two people merged / one person split** — see calibration above, then
  Recompute the day.

## Honest fine print

- Age and gender are *model guesses* — solid for patterns across hundreds of
  approaches, not for any single person.
- Identity matching is good at street distance with clear faces; sunglasses,
  masks and extreme angles can split a person into two marks. The numbers
  are consistent day-to-day, which is what comparisons need.
- The bundled models are open research models (OpenCV Zoo / ONNX Model Zoo).
  If TarzanIQ ever becomes more than an internal tool, give their licenses a
  read.

*v1.0.0 "Silverback" — runs at http://127.0.0.1:43117, binds to this Mac
only.*
