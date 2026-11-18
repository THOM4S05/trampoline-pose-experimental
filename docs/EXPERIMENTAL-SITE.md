# Experimental version

Private Tailscale address: <https://desktop-qfvrcme.tail48ad3d.ts.net:8443>

This runs the twist-enabled local copy in `experiments/twist-width-copy`, using
its existing `.portal` inbox, access key, videos and results. Pages are labelled
Experimental. Its session cookie is separate from the main portal's cookie.

Start after a PC restart:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-experimental.ps1
```

The private Tailscale route persists across reboots:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --bg --https=8443 http://127.0.0.1:8766
```

The existing HTTPS port 443 route continues to target port 8765. Experimental
uses HTTPS port 8443 and local port 8766. The Python launcher must remain running.
The experimental access key is at
`experiments/twist-width-copy/.portal/access-key.txt`.
