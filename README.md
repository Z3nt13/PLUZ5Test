# PLUZ5-Cust

Your own PS5 payload registry + manifest generator. **Ships with no payloads** --
you choose the repos, GitHub Actions does the rest. Works as a custom
repository in [pldmgr](https://github.com/itsPLK/ps5-payload-manager).

```
 builder.html ─► registry json ─► upload to configs/ ─► Actions: fetch → build → validate → commit
                                                          │
                                  pldmgr custom repo URL ◄┘  (raw manifest link)
```

## Upload from your PC (recommended -- the web uploader skips hidden folders)
1. Create an **empty** repo on GitHub (no README), tick **Template repository** in Settings.
2. Unzip this folder anywhere (show hidden files so `.github` and `.env` are there).
3. Open `.env`, paste your classic token (`repo` + `workflow`) after `GH_TOKEN=`.
4. Double-click **`PLUZ-AllStar.bat`** (Arch/Linux: `./pluz-allstar.sh`). It connects the folder to your repo,
   fetches, builds, validates, commits and pushes. Run it again any time; it never needs typing.
5. Settings → Pages → Deploy from branch `main` `/ (root)`, then open `web/builder.html` on your Pages site.

Problems? `PLUZ-AllStar.bat debug` writes a full log (token hidden) to `logs\`. Stuck GitHub logins? `PLUZ-GHclean.bat`.
`.env` is gitignored, so your token is never uploaded.

## Set up (without a PC)
1. **Use this template** → create your own repo.
2. **Settings → Pages**: Deploy from branch `main`, folder `/ (root)`.
3. Open `https://<you>.github.io/<repo>/web/builder.html`, add the repos you want
   (or open `examples/example-full.json` to start from a full list), save `payload_registry.json`.
4. Upload it to `configs/` (replace the empty one). Actions runs by itself; or Actions tab → *Run workflow*.
5. In pldmgr add: `https://raw.githubusercontent.com/<you>/<repo>/main/manifests/PLUZ-ps5-Source.json`
   (`PLUZ-ps5-Hosted.json` only exists in hosted mode.)

## Modes (`mode` in `configs/settings.json`, or `PLUZ_MODE` in `.env`)
| | source (default) | hosted |
|---|---|---|
| Repo holds | only json (`manifests/resolved.json` remembers each upstream asset) | the binaries in `payloads/` |
| pldmgr downloads from | the upstream release | your repo (raw link) |
| Old builds | no, latest only | up to 3 per payload, `keep old builds forever` honoured |
| Zip-only releases | skipped (need a direct .elf/.bin) | extracted |
| Repo size / licence worries | none | grows; you redistribute the files |

## Layout
```
.github/workflows/update.yml   daily + on-push + manual
configs/payload_registry.json  YOUR sources (the one file you edit)
configs/categories.json, settings.json
core/                          engine (stdlib Python only)
payloads/                      only used in hosted mode
manifests/                     generated (Source.json, split/, resolved.json)
web/builder.html  catalog.html   build/edit your list, browse, PS5 links
examples/example-full.json     47-entry starter list
PLUZ-AllStar.bat / pluz-allstar.sh   full local run (+ debug flag)
PLUZ-GHclean.bat / pluz-ghclean.sh   clean repo / saved git logins
pluz.py                        python pluz.py <check|fetch|update|validate|cleanup|dedupe>
```
Paths and the GitHub token live only in `.env` (copy `.env.example`). Not needed for the Actions flow.

Hardware tags: `P5` regular/slim, `P5P` Pro, `P5U` both. Version comes from the file name
`{payload}[-{variant}]_v{version}.{elf|bin}`; `fw_min`/`fw_max` are typed by hand, unknown stays blank.
You are responsible for the licences of what you host.
