# resolve-mcp-kit

A small, standalone MCP (Model Context Protocol) server that lets an AI agent
see and drive DaVinci Resolve on your own computer. It works with any MCP
client: opencode, Claude Code, Claude Desktop, and others. Beyond the Python packages in requirements.txt it needs
nothing else.

It also ships an opencode skill (and a Claude Code copy) that teaches the agent
how to build a timeline from clips, make cuts, add titles, and render.

## What it can do

Always available (read-only, plus changing the visible page):

| Tool | Purpose |
|---|---|
| `resolve_status` | Is Resolve reachable; product, version, page, project, timeline |
| `list_projects` | Projects in the current database folder |
| `list_timelines`, `timeline_info` | Timelines and their frame range, tracks, fps |
| `list_media_pool` | Clips in a bin: name, duration, fps, resolution |
| `set_page` | Switch to media, cut, edit, fusion, color, fairlight, deliver |
| `project_settings` | Read project settings such as frame rate and resolution |

Editing tools, only when `RESOLVE_MCP_ALLOW_WRITE=1` (nothing here deletes
anything):

| Tool | Purpose |
|---|---|
| `import_media` | Import files into the media pool, optionally into a bin |
| `create_timeline` | New empty timeline, made current |
| `append_clips` | Append clips in order, optionally trimmed (cuts) |
| `add_title` | Insert a Text+ title and set its text |
| `add_marker` | Timeline marker |
| `save_project` | Save |
| `render_formats_and_codecs`, `start_render`, `render_status` | Queue, start and watch a render |

Provenance: the read-only tools are the ones from the author's original
server. The editing tools are new in this kit and have only been tested against
a fake Resolve object (see Testing).

## Requirements

- DaVinci Resolve with external scripting. Historically the paid **Studio**
  edition is required; Blackmagic has restricted scripting in the free edition
  in many versions. Check your version, and expect "Could not attach" in the free
  one.
- In Resolve: Preferences > System > General > **External scripting using: Local**.
- Resolve must be **running with a project open** in its window. The scripting
  API only attaches to a Resolve on the same computer, so this server runs on
  the same machine as Resolve.
- Python 3.10 or newer (the scripting module needs a Python that matches what
  Resolve supports; 3.10 to 3.12 are the safe choices).
- `pip install -r requirements.txt` (the start scripts do this for you).
  Note `mcp` is pinned below version 2 on purpose: this code uses the 1.x
  `FastMCP` API.

## Where Resolve's scripting module lives

The server finds it automatically from these defaults. Override with
environment variables if your install is elsewhere.

| OS | `RESOLVE_SCRIPT_API` | `RESOLVE_SCRIPT_LIB` |
|---|---|---|
| Windows | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` | `C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll` |
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting` | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so` |
| Linux | `/opt/resolve/Developer/Scripting` | `/opt/resolve/libs/Fusion/fusionscript.so` |

Windows and Linux paths are as documented by Blackmagic and as used by the
original author on Windows. The macOS and Linux defaults come from Blackmagic's
README and have not been tried by the author.

## Quick start

Windows:

1. Open DaVinci Resolve and a project.
2. Double-click `start-resolve-mcp.cmd` (first run creates `.venv` and installs
   dependencies). It listens on `http://127.0.0.1:8930/sse`.

macOS / Linux: `./start-resolve-mcp.sh` (needs `chmod +x` once).

Check it: with the server running, ask your client to call `resolve_status`. If
you see `connected: false`, the `reason` field says what to fix.

## Configuration

All by environment variable (edit the top of the start script, or set them
yourself).

| Variable | Default | Meaning |
|---|---|---|
| `RESOLVE_MCP_TRANSPORT` | `sse` | `stdio`, `sse`, or `streamable-http` |
| `RESOLVE_MCP_HOST` | `127.0.0.1` | Bind address for sse/http |
| `RESOLVE_MCP_PORT` | `8930` | Port for sse/http |
| `RESOLVE_MCP_TOKEN` | unset | If set, requests need `Authorization: Bearer <token>` |
| `RESOLVE_MCP_ALLOW_WRITE` | `0` (the start scripts set `1`) | Register editing and render tools |
| `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB` | per OS | Resolve scripting paths |

Endpoints: `sse` serves `/sse`; `streamable-http` serves `/mcp`.

### Security warning

This server can open, change and render your projects and write files wherever
Resolve can. Keep it on `127.0.0.1` whenever you can. If the client is on
another machine, bind to a LAN or VPN address only (for example a Tailscale
address), set `RESOLVE_MCP_TOKEN` to a long random string, and never expose
the port to the internet or forward it on your router. The token is sent in
cleartext over plain HTTP, so it protects against casual access, not against
someone who can watch your network; use a VPN for anything beyond your own LAN.

## Connecting a client

Two styles. **stdio**: the client launches the server itself (simplest; the
client must run on the Resolve machine). **Network** (sse/streamable-http):
you start the server with the start script and the client connects by URL,
which also works from another machine.

### opencode

Config goes in `~/.config/opencode/opencode.json` (global) or `opencode.json` in
a project folder. Merge the `mcp` block from one of the examples:

- `examples/opencode.local.json` - opencode launches the server over stdio.
  Edit the two paths to your install of this folder.
- `examples/opencode.remote.json` - connect to the running server by URL. If you
  set `RESOLVE_MCP_TOKEN`, export the same value as an environment variable
  before starting opencode; the example reads it with `{env:RESOLVE_MCP_TOKEN}`.
  If you did not set a token, delete the `headers` block. For another
  machine, change the URL to its address.

Then run `opencode mcp list` to confirm `resolve` connects.

Install the skill (the folder name must match the skill name, per opencode):

- Global: copy `skills/davinci-resolve-editing` to
  `~/.config/opencode/skills/davinci-resolve-editing`
  (Windows: `%USERPROFILE%\.config\opencode\skills\davinci-resolve-editing`).
- Per project: copy it to `<project>/.opencode/skills/davinci-resolve-editing`.

opencode also reads `.claude/skills/` and `.agents/skills/`. Start a new
opencode session and ask it to "edit video in Resolve"; the skill is loaded on
demand.

### Claude Code

```
claude mcp add resolve --transport sse http://127.0.0.1:8930/sse
```

With a token, add `--header "Authorization: Bearer YOUR_TOKEN"`. Or use stdio:

```
claude mcp add resolve -e RESOLVE_MCP_TRANSPORT=stdio -e RESOLVE_MCP_ALLOW_WRITE=1 -- C:\path\to\resolve-mcp-kit\.venv\Scripts\python.exe C:\path\to\resolve-mcp-kit\resolve_mcp_server.py
```

Skill: copy `skills/davinci-resolve-editing` to `~/.claude/skills/` (global) or
`<project>/.claude/skills/`. A copy is already at
`.claude/skills/davinci-resolve-editing` in this folder, so opening Claude Code
here picks it up.

### Claude Desktop

Merge `examples/claude_desktop_config.json` into your Claude Desktop config
(Settings > Developer > Edit Config), fix the paths, and restart the app. It
uses stdio.

### Other clients

Point any MCP client at `http://HOST:8930/sse` (SSE), or use
`RESOLVE_MCP_TRANSPORT=streamable-http` and `http://HOST:8930/mcp`.

## Running at login (optional, Windows)

Resolve's API only works in your logged-in desktop session, so start the server
with a Task Scheduler task "At log on of <you>" running
`start-resolve-mcp.cmd`, not as a service.

## Website promo videos (`site_video`)

Give it a link and it makes a narrated promo video of the site:

1. **Reads the site**: the start page and the same-site pages it links to (headings, buttons, text).
2. **Writes a script** with any OpenAI-compatible model: scenes, captions, narration and what to scroll to or point
   at, fitted to the length you ask for and to your notes ("show pricing, end on sign-up"), or chosen for you.
3. **Records the real site** in Chromium at 1080p/30: smooth scrolling, a visible cursor that glides to things,
   lower-third captions, plus intro and outro title cards.
4. **Adds a voiceover**, with the voice chosen per video.
5. **Edits it in DaVinci Resolve**: a new timeline in a "Site videos" project (one bin per video, a marker per
   scene, so you can polish it by hand), then a render. Without Resolve, it joins the clips with ffmpeg instead.

It never logs in, buys, submits forms or deletes anything on the site. Only make videos of sites you may show.

### Install

```
pip install -r requirements-video.txt
python -m playwright install chromium
```

ffmpeg comes with `imageio-ffmpeg`; set `FFMPEG` to use your own.

### Settings (environment variables)

| Variable | What |
|---|---|
| `SITE_VIDEO_LLM_URL`, `SITE_VIDEO_LLM_MODEL`, `SITE_VIDEO_LLM_KEY` | The model that writes the script: any OpenAI-compatible `/v1` (default: a local Ollama with `qwen3:8b`). Bigger models write better scripts. |
| `SITE_VIDEO_TTS_URL`, `SITE_VIDEO_TTS_KEY`, `SITE_VIDEO_TTS_MODEL` | Voice `openai[:voice]`: OpenAI (default URL) or any compatible `/audio/speech`, e.g. a Kokoro-FastAPI server (`SITE_VIDEO_TTS_MODEL=kokoro`). |
| `ELEVENLABS_API_KEY` | Voice `elevenlabs:<voice id>`. |
| `SITE_VIDEO_ODYSSEUS_URL`, `SITE_VIDEO_ODYSSEUS_TOKEN` | Voice `odysseus`: an Odysseus server's own voice. |
| `SITE_VIDEO_DEFAULT_VOICE` | The voice when a job does not name one. |
| `SITE_VIDEO_HOME` | Where jobs and videos go (default `~/site-videos`). |
| `SITE_VIDEO_TOKEN` | If set, the queue's HTTP API and page need it. |
| `SITE_VIDEO_RESOLVE_PROJECT` | The Resolve project for edits (default `Site videos`). |

### One video, in a terminal

```
python -m site_video make https://example.com --length 2min --notes "show pricing, end on sign-up" --voice openai:alloy
```

`--length` takes `5min`, `90s`, `1:30` or `auto`; `--notes` takes plain words or `auto`; `--editor` takes
`auto` (Resolve if it is open, else ffmpeg), `resolve` or `ffmpeg`; `--music file.mp3` plays music under the voice,
quieter while it speaks.

### A queue (several videos, 2 at a time)

```
python -m site_video serve --port 8940 --parallel 2
```

Open `http://127.0.0.1:8940/` for a page with a form and the queue (watch, download, cancel, try again), or use it
from a terminal or another program:

```
python -m site_video add https://example.com --length 5min --notes "..." --wait
python -m site_video list
python -m site_video get <id> -o video.mp4
```

Up to `--parallel` videos are read, scripted, voiced and recorded at once; edits take turns, since one Resolve
renders one thing at a time. Each stage runs in its own process and keeps its output, so a cancelled, failed or
restarted job continues from its last finished stage. The HTTP API is documented at the top of
`site_video/server.py`.

### From an agent

With `RESOLVE_MCP_ALLOW_WRITE=1` (or `SITE_VIDEO_SERVER` set), the MCP server also offers `make_site_video`,
`site_video_status` and `list_site_videos`, which use the queue at `SITE_VIDEO_SERVER` (default
`http://127.0.0.1:8940`). The `website-promo-video` skill (in `skills/`, and `.claude/skills/`) teaches an agent to
turn "go through this site and make a 5 minute video, make sure you show X" into a job.

### Limits

- The Resolve edit runs on the computer with Resolve and switches it to the "Site videos" project for the edit,
  opening your project again afterwards. It has been run on Resolve Studio on Windows; macOS and Linux are untested.
- Requested lengths are targets: a scene is never shorter than its narration, and the title cards add a few
  seconds, so a 30 second request usually comes out at 35 to 40.
- Sites that need a login, block headless browsers or show a full-screen pop-up the recorder cannot dismiss will not
  record well.

## Testing

```
pip install -r requirements.txt -r requirements-video.txt pytest
python -m pytest tests
```

The tests replace Resolve's scripting module with a fake. They prove the server
starts, lists its tools, the read/write split works, and that the edit and
render tools call the API with the expected arguments. They cannot prove that a
real Resolve accepts those calls. Things to expect to need a real-install
shakedown: title text setting (`add_title`), `append_clips` trimming, and codec
keys for `start_render`.

## License

MIT, see `LICENSE`. DaVinci Resolve is a trademark of Blackmagic Design; this project is not affiliated with it.
