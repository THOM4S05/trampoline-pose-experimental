# Flightroom shared viewer

This is the standalone, read-only edition of the experimental site. It uses
preloaded skeleton-overlay videos and saved skill results. Playback, speed,
frame stepping, skill/landing/shape/twist jumps, routine context, downloads and
the torso orientation dial run in the visitor's browser. There is no login,
upload form, processing service, model download, or connection to the local PC.

## Prepare a collection

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/prepare-shared-viewer.py --list
.\.venv\Scripts\python.exe scripts/prepare-shared-viewer.py --job VIDEO_ID --job ANOTHER_ID --output artifacts/shared-public
```

Use `--all` instead of `--job` to prepare all completed experimental analyses
for local review. Each output must be a new directory. Nothing in the local
inbox is changed, and only explicitly selected jobs are included. Original
source videos, access keys, job metadata and raw joints are excluded. The
skeleton is already drawn into each exported overlay video. Export preparation
derives a compact dial trace from saved joint coordinates and adds the same
difficulty fields shown by the experimental portal; no inference runs.

## Preview

```powershell
.\.venv\Scripts\python.exe -m http.server 8770 --bind 127.0.0.1 --directory artifacts/shared-public
```

Open http://127.0.0.1:8770. A web server is needed for JSON requests; do not
double-click index.html. This server is for local review only.

For the prepared collection of all completed videos, run
`powershell -NoProfile -File scripts/start-shared-viewer.ps1` from the project root.

## Publish for free with GitHub Pages

1. Review the collection and get permission to publish the selected footage.
   GitHub Pages on GitHub Free is public; every video, label, image and JSON
   file you publish can be viewed or downloaded by anyone.
2. Create a **separate public repository**, for example `flightroom-demo`.
   Only use the contents of the generated output directory, never this whole
   development repository or the experimental `.portal` directory.
3. Commit and push the generated output folder's contents to that repository.
   For initial setup, from INSIDE the generated folder:

   ```powershell
   git init -b main
   git add .
   git commit -m "Publish preloaded Flightroom viewer"
   git remote add origin https://github.com/YOUR_USERNAME/flightroom-demo.git
   git push -u origin main
   ```

4. In the repository, open **Settings > Pages**. Select **Deploy from a branch**,
   **main**, **/(root)**, then Save. GitHub shows the published address, normally
   `https://YOUR_USERNAME.github.io/flightroom-demo/`.
5. Verify playback and skill controls at that address, including on a phone.
   The site then runs on GitHub independently of your PC. GitHub's service
   availability and quotas apply; this is not a guaranteed uptime service.

The exporter reports `github_ready`, total size, and files too large for Git.
Keep each file below 100 MiB and the published collection below 1 GB. Do not
commit oversized videos; prepare smaller copies outside the viewer first.
For a browser-only GitHub upload, each file must also fit GitHub's lower
browser-upload limit; Git is preferable for these video collections.

For updates, prepare a new collection and replace the old published files,
including removing clips no longer selected. Do not merge exports and leave
old unlisted footage accessible. Removing a file from the latest website does
not remove it from Git history or copies people already downloaded.

GitHub documentation:
- https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
- https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
