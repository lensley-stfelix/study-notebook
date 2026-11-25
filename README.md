# Study.com transcript exporter

## NEW: TESU offline study notebook

### Lesson ordering and deletion update

New imports are sorted by original file path using natural numeric order (for example `001`, `002`, `010`, or `Chapter 2/Lesson 1` before `Chapter 10/Lesson 1`), then saved in that sequence rather than alphabetical title order. Import one course at a time. If you already imported a course in the previous version, click **Restore course order from files** and select its original text/Markdown files. This reorders unique matching lesson titles without creating duplicates or replacing annotations and media. If files lack numbering, titles changed, or titles are duplicated, use **Move up** and **Move down** to set the exact course sequence. Manual ordering is saved across restarts.

To remove a test lesson, select it and click **Delete selected lesson**, then confirm. It is moved with its attachments to `.trash` under your notebook-data folder. Use **Restore deleted lesson** to recover it; restored lessons appear at the end of the list. Source exports and original media are unaffected.

To upgrade without losing notes, close the app and replace the old `study_notebook.py` in your existing installation folder with the new one. Keep `notebook-data` (or your existing custom `--root` folder) unchanged. Back it up first.

The original exporter remains unchanged. The companion desktop notebook lets you manually paste lesson text, import existing `.md`/`.txt` exports, and add media you already have permission to use. It does not download videos or transfer anything online.

In PowerShell, open the extracted folder and run:

```powershell
python -m pip install -r requirements.txt
python study_notebook.py
```

1. Select **New lesson**, or **Import text / Markdown** to bring in existing exporter lesson files (you can select multiple files).
2. Paste your lesson text into the editor. Place the cursor wherever an image belongs, copy the image or screenshot, and click **Paste image** (or Ctrl+V when an image is on the clipboard).
3. Click **Attach image / video** to select images or a downloaded video from your computer. The notebook copies the files into that lesson's media folder; your originals stay untouched.
4. Click **Open lesson preview** to see the offline HTML lesson with embedded images and playable video controls. MP4 (H.264/AAC) and WebM are recommended; other formats depend on your browser's codecs. The editor displays attachment markers rather than live images. Copy an image separately if a text-and-image clipboard paste only inserts text.
5. Press **Save** (Ctrl+S). Changes also save when switching lessons, opening a preview, or closing normally. Refresh an already-open browser preview after editing.

The notebook defaults to `notebook-data/` next to the script. Each lesson folder has `lesson.json`, `lesson.md`, `lesson.html`, and `media/`. Back up the whole data folder to preserve both notes and attachments. To keep your notebook somewhere else, run `python study_notebook.py --root "C:\Users\YourName\Documents\TESU-Notes"`. Use the same root every time. Keep your original `study-exports` folder and any previous notebook data during upgrades. Imported Markdown is preserved as text; the companion generates a simple readable HTML preview with the attached media.

To share notes with TESU Space, upload or paste `lesson.md` and add selected image/video files separately. Relative media links only work when the media folder is present next to the exported lesson file. Local videos are not automatically uploaded or synced.

## Original text exporter

Exports accessible lesson text for Computer Science 302: Systems Analysis & Design to local Markdown and HTML. The course run follows the order of lesson links in the expanded outline. It reads the visible transcript and looks for an identifiable end before accepting the lesson. The exporter blocks browser media requests and never saves video files.

## Windows setup

Open PowerShell in the directory containing these three files. Use Python 3.10 or later.

```powershell
python -m pip install -r requirements.txt
python export_study.py --channel msedge --sample
```

The script opens a dedicated Edge window. Sign in there manually if needed. Once the lesson is visible, return to PowerShell and press Enter. If the initial page times out, try opening the lesson URL manually in that same window before pressing Enter. The profile lives in `.study-browser` and keeps the sign-in session locally for later runs. Keep this folder private. You can use `--channel chrome` for installed Chrome, or run `python -m playwright install chromium` and omit `--channel`.

## Export the course

```powershell
python export_study.py --channel msedge --course "https://study.com/academy/course/computer-science-302-system-analysis-design.html?resume=true"
```

In the new window, open the signed-in course outline and expand every chapter. Use **Expand all** if available. Once the lesson links are visible, press Enter in PowerShell. The public syllabus listed 108 lessons at verification time. The script reports a different link count as a coverage gap. You can pass `--expected-count` if the current course shows a different count. Even a matching count is only a count check, so review `outline.tsv` to confirm membership and ordering.

If the outline shows a partial list or the site uses a layout the exporter cannot discover, create `lesson-urls.txt` containing one Study.com lesson URL per line in study order. For chapter labels and titles, use three tab-separated fields in each row in the order chapter, title, URL. You can edit the generated `outline.tsv` or use an outline containing only missing lessons for a retry.

```powershell
python export_study.py --channel msedge --urls lesson-urls.txt
```

If a lesson is explicitly labeled as text-only, the script exports its bounded text section under that label. If the site omits the label, open the lesson and confirm it is text-only, then pass `--text-only "LESSON_URL"` along with the usual source argument. Unrecognized content boundaries still result in a missing entry.

## Read the results

Each run creates a new folder under `study-exports`. Use `--out` to change the parent directory.

- `course.html` opens offline, with a linked table of contents and browser Find support.
- `course.md` contains the same exported lesson text in course order.
- `lessons/` contains one Markdown file per accepted lesson with its source URL.
- `manifest.json` lists exported, missing, and pending lessons with reasons and coverage notes.
- `outline.tsv` records the discovered or supplied lesson list.

The process exits with code 2 for incomplete runs. The parser checks visible content, access messages and section boundaries. Site layout changes can cause false misses, and an accepted section is not an independent guarantee of completeness. Review the sample and manifest before relying on a full export.
