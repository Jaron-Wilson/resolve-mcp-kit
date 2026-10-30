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

1. **Explores the site** (`explore.py`): every same-site page it can reach by links, up to 60 in about 4 minutes
   (`SITE_VIDEO_EXPLORE_PAGES`, `SITE_VIDEO_EXPLORE_SECONDS`), waiting for each to finish filling in; sign-in, cart
   and legal pages are left out and look-alike detail pages are sampled. Each page is scored for how much real content
   it shows, its search fields are tried with a real example taken from the site's own items, and with a vision model
   set the best views are described. The script model gets a map of every page and the best views in full.
2. **Reads the brand**: the site's background, text and main colors, its heading font and its logo, and whether its
   reading column is narrow (then pages are recorded at 1.5x so they fill the frame).
3. **Writes a script** with any OpenAI-compatible model, in the shape of a hand-made product promo: a title card, a
   "the problem" card, 6 to 10 short scenes that each show one feature working (typing a real example into the
   site's search, opening tabs, pointing at results, scrolling to the section that proves it), each with one or two
   full-sentence captions of facts on screen, and a closing card with the site's address. It fits the length you ask
   for and your notes ("show pricing, end on sign-up"), or chooses one.
4. **Records the real site** in Chromium at 1920x1080/30 with a soft dot cursor in the brand color, eased scrolls and
   cursor moves and real typing; the waiting is cut out and each scene sped up (to 2.4x) to fit. Nothing is sent but
   page loads.
5. **Draws the cards and captions** in the site's own font and colors (cards with a slow push-in, captions as pills
   with a check mark), and **adds a voiceover**, with the voice chosen per video.
6. **Edits it in DaVinci Resolve**, laid out like the hand-made promos: its own project in the "Site videos" folder,
   track V1 "Picture" with a dissolve centered on every cut, V2 "Captions" with each caption image fading in and out,
   A1 the soundtrack, so you can polish it by hand; then a render. Without Resolve, ffmpeg makes the same edit.

7. **Checks the video against the script** (`review.py`, needs `SITE_VIDEO_VISION_MODEL`): each scene's clip is
   sampled and scored 1 to 5 for showing what its caption and narration say; steps the recorder could not do count
   against it. A scene that clearly failed (a step that did not happen, a broken or wrong page) is rewritten by the
   script model from what was really recorded and made again, once. Verdicts are in `review.json` and the log.

It never logs in, buys, submits forms or deletes anything on the site. Only make videos of sites you may show.

**Notes are a brief.** Write a wish ("show pricing") or paste a whole outline with scenes, text to paste and
voiceover: the script follows its scenes and order, types or pastes the text it gives (long text is pasted, not typed
key by key) and uses its on-screen text and voiceover. Pages named in the notes are always explored.

**Your own site.** Two options, both off unless you choose them:
- *This is my site* (`changes` in the API, `--my-site` on the command line): the video may press buttons that save or
  create things, as the notes ask (evaluate, create, convert, finish). Deleting, removing, buying, paying and signing
  out are never clicked, whatever the notes say.
- *Sign in as me* (the page's button, `POST /api/signin`, or `site-video signin URL`): your installed Chrome or Edge
  opens at the site with a profile of its own; sign in by hand (Google sign-in works, as it is a normal browser) and
  close the window. The site's cookies are saved in `SITE_VIDEO_SESSIONS` (`~/.site-video/sessions`), one file per
  site, and every later video of that site is explored and recorded signed in. Your password never passes through
  site_video; `site-video signin URL --forget` deletes the saved sign-in.

### Your own videos

A job can use a website, your own videos, or both:

| You have | You give | What happens |
|---|---|---|
| A website | the link | The site is recorded, as above |
| Videos, no website | the videos, each with a note ("app demo, use the part where I add a card") | The script picks moments from your videos, with narration over them or their own sound |
| A website and a few videos | both, and a length | Your videos go in where they fit the story, and website scenes fill the rest of the length |

Before writing the script it watches each video: a frame every few seconds described by a vision model
(`SITE_VIDEO_VISION_MODEL`), and what is said, by time, from speech to text (`SITE_VIDEO_STT`). Without them it
knows only your notes and each video's length, so describe the videos well. A scene from your video plays either its
own sound (someone speaking) or the narration with its sound quietly under it. It gets the same captions
as the website scenes, and is fitted to 1920x1080 at 30 fps, with letterboxing if the shape differs. Every video you
give is used at least once.

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
| `SITE_VIDEO_START_RESOLVE` | Resolve's program file: if set, a Resolve edit opens Resolve when it is closed (run the queue in your desktop session). |
| `SITE_VIDEO_VISION_MODEL` | A vision model on the `SITE_VIDEO_LLM_URL` endpoint (e.g. `qwen2.5vl:7b`) that describes frames of your videos. |
| `SITE_VIDEO_STT` | Speech to text for your videos: `openai` (`SITE_VIDEO_STT_URL`, `SITE_VIDEO_STT_KEY`, `SITE_VIDEO_STT_MODEL`, any OpenAI-compatible `/audio/transcriptions`, e.g. a faster-whisper server) or `odysseus` (the `SITE_VIDEO_ODYSSEUS_URL` server). |
| `SITE_VIDEO_MAX_UPLOAD_MB` | The largest video the queue accepts as an upload (default 4096). |
| `SITE_VIDEO_MEDIA_DIRS` | Folders (separated by `;` on Windows, `:` elsewhere) whose videos API and agent jobs may use without uploading. Otherwise jobs sent over HTTP can only use uploads. |

### One video, in a terminal

```
python -m site_video make https://example.com --length 2min --notes "show pricing, end on sign-up" --voice openai:alloy
```

`--length` takes `5min`, `90s`, `1:30` or `auto`; `--notes` takes plain words or `auto`; `--editor` takes
`auto` (Resolve if it is open, else ffmpeg), `resolve` or `ffmpeg`; `--model` picks the model that writes the
script for this video (default `SITE_VIDEO_LLM_MODEL`; the page lists the endpoint's models); `--music file.mp3`
plays music under the voice, quieter while it speaks.

Your own videos: `--video file` (repeat it), each followed by `--note-for "what it is, what to use"`; the link is
then optional:

```
python -m site_video make --video demo.mp4 --note-for "the app demo" --video talk.mov --length 2min
python -m site_video make https://example.com --video demo.mp4 --video promo.mp4 --length 5min
```

### Changing a video

A finished (or failed) video can be changed and made again: on the page, press **Change** on the job.

- **Describe the change** in words ("in scene 3, point at the Pro plan instead", "make the intro shorter", "swap scenes 4
  and 5") and press **Apply to the script**: the script model makes the change and lists what differs, for you to check.
- **Or edit the script yourself**: the title and problem cards, the closing line, each scene's two captions,
  narration, page and steps (scroll to / type / hover / click / pause, with the page's headings, buttons and text
  fields to pick from), your videos' times and sound, the order, and the cursor. A changed caption only redraws its
  image; no scene is recorded again for it.
- **Redo the video**: only the scenes that changed are recorded, cut or voiced again, so a one-scene fix takes about a
  minute. The old script is kept as `plan.<n>.json`.

The same from a terminal, `python -m site_video change <id> "point at the Pro plan in scene 3" [--dry-run]`, from the
HTTP API (`GET /api/jobs/<id>/plan`, `POST .../suggest`, `POST .../revise`), and from agents (`edit_site_video`).

The cursor on website scenes is chosen per video (`--cursor`, the page's Cursor menu, or `cursor` in the API): `dot`
(default: a soft dot in the site's main color that shrinks on clicks, as in the hand-made promos), `arrow`, `hand`,
`ring` (the arrow with a highlight, and a ripple on clicks) or `none`.

### Deliverables

Each video can hand back more than the MP4 (`--deliver`, the page's Deliverables row, or `deliverables` in the API):

| Name | What |
|---|---|
| `video` | The rendered MP4 (always) |
| `script` | `script.md` (scenes with times, captions, on-screen actions and narration) and `plan.json` |
| `voiceover` | One WAV per narration line, and `soundtrack.wav` (the mixed audio of the whole video) |
| `clips` | The recorded scenes and title cards, 1920x1080 30 fps |
| `timeline` | The Resolve timeline as `.drt`, `.fcpxml` (Final Cut, Premiere) and `.edl` (Resolve edits only) |
| `resolve_project` | The video's own Resolve project as `.drp` (Resolve edits only) |
| `package` | One zip with all of the above and a README on importing and relinking |

In Resolve, each video is its own project in a "Site videos" project folder, so its `.drp` holds only that video.
If a project is already called "Site videos" (earlier versions kept every video in one such project), Resolve will
not make a folder with that name, so the folder is "Site videos projects" instead.

### A queue (several videos, 2 at a time)

```
python -m site_video serve --port 8940 --parallel 2
```

Open `http://127.0.0.1:8940/` for a page with a form and the queue (watch, download, cancel, try again, remove), or use it
from a terminal or another program:

```
python -m site_video add https://example.com --length 5min --notes "..." --wait
python -m site_video add --video demo.mp4 --note-for "the app demo" --length 1min      # uploads demo.mp4
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
  opening your project again afterwards. Developed against Resolve Studio 21.1 on Windows; macOS and Linux are
  untested.
- When the queue opens Resolve itself, it closes it again after the edit; a Resolve you opened is left open.
- Resolve 21 opens on its Project Manager screen, and while that screen is up, scripting cannot open or create
  projects. When the queue opens Resolve itself (`SITE_VIDEO_START_RESOLVE`) it uses `-nogui` (Studio), which has
  no such screen; if Resolve is already open on the Project Manager, open any project first.
- Requested lengths are targets: a scene is never shorter than its narration, and the title cards add a few
  seconds, so a 30 second request usually comes out at 35 to 40.
- Your videos are cut, never sped up or slowed: with no website, a video cannot run longer than the footage you
  give. With a website, a long length is filled with website scenes of at most 90 seconds each.
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
