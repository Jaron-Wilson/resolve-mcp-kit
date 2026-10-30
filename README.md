# resolve-mcp-kit

Two tools in one folder.

1. **A Resolve MCP server.** It lets an AI agent (Claude Code, Claude Desktop, opencode, any MCP client) see and drive
   DaVinci Resolve on your computer: read projects, import clips, build timelines, add titles, render.
2. **site-video.** You give it a website link. It explores the site, has a language model write a script, records the
   real site in a browser, adds captions and an optional voiceover, and edits a promo video. It works with or without
   Resolve. Without Resolve, ffmpeg joins the clips.

You can use either one alone. Follow the sections in order for a first video. Skip to [With Resolve](#with-resolve-the-mcp-server)
for the MCP server.

## What you need

| Part | Windows | macOS | Linux |
|---|---|---|---|
| site-video, ffmpeg editor (no Resolve) | works | should work, not run by the author | works (run on Ubuntu 24.04, Python 3.12) |
| site-video, Resolve editor | built and used here (Resolve Studio 21.1) | untested | untested |
| Resolve MCP server | built and used here | untested | untested |
| Sign in as me (a window on the queue's computer) | Chrome or Edge | Chrome or Edge, untested | Chrome, Chromium or Edge, untested |
| Browser extension sign-in | Chrome or Edge | Chrome or Edge | Chrome or Edge |

- **Python 3.10 or newer.** 3.12 is a safe choice. The Resolve scripting module also has to match the Python that
  Resolve supports.
- **Disk space.** About 1 GB for the install (the packages, plus Chromium and its helpers, which Playwright downloads
  once). Each video job keeps its recorded clips, voice files and the final MP4. Plan on a few hundred MB per minute
  of video, and delete jobs you no longer need.
- **DaVinci Resolve Studio** (paid) for anything that touches Resolve. Blackmagic's free edition does not allow
  external scripting in most versions, so expect "Could not attach to Resolve" there. Resolve must run on the same
  computer as the server, with a project open.
- **A language model** that writes the script. This is the one thing site-video cannot do without. A free local one
  (Ollama) works, no API key needed. See [Model setup](#model-setup).
- **Optional:** a voice (text to speech) for narration, a vision model, speech to text, Chrome or Edge for
  sign-in. Without a voice the video has captions and no narration.

## Install

Pick your system. Run the commands in the folder you cloned.

**Windows** (cmd.exe or PowerShell, Python from python.org with "Add to PATH" ticked):

```
git clone https://github.com/Jaron-Wilson/resolve-mcp-kit.git
cd resolve-mcp-kit
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-video.txt
.venv\Scripts\python.exe -m playwright install chromium
```

In the commands below, `python` means the venv's Python. Either activate it once per window
(`.venv\Scripts\activate` in cmd.exe, `.venv\Scripts\Activate.ps1` in PowerShell) or type
`.venv\Scripts\python.exe` instead of `python`.

**macOS or Linux:**

```
git clone https://github.com/Jaron-Wilson/resolve-mcp-kit.git
cd resolve-mcp-kit
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-video.txt
python -m playwright install chromium
```

On Debian or Ubuntu, `python3 -m venv` may need `sudo apt install python3-venv` first. On a bare Linux server,
Chromium may need system libraries: `sudo .venv/bin/python -m playwright install-deps chromium`.

**The start scripts do the same install for you.** `start-resolve-mcp.cmd` (Windows) and `./start-resolve-mcp.sh`
(macOS and Linux) create `.venv`, install both requirements files, download Chromium, then start the MCP server. They do
this once. Set `RESOLVE_MCP_SKIP_VIDEO=1` first to skip the video packages and the Chromium download if you only
want the Resolve MCP server. Set `RESOLVE_MCP_REINSTALL=1` once after you update this folder.

ffmpeg needs no install: the `imageio-ffmpeg` package ships a copy. Set `FFMPEG` to the path of your own ffmpeg to use that
instead.

## Model setup

site-video needs one chat model to write the script. It is any server with an OpenAI-style `/chat/completions` API.
Everything is set with environment variables, in the same window where you start site-video.

| Variable | Default | What it is |
|---|---|---|
| `SITE_VIDEO_LLM_URL` | `http://127.0.0.1:11434/v1` | Base URL of the API, ending in `/v1`. The default is a local Ollama. |
| `SITE_VIDEO_LLM_MODEL` | `qwen3:8b` | The model id the server lists. |
| `SITE_VIDEO_LLM_KEY` | empty | API key, sent as a bearer token. Leave it empty for local servers. |

Set a variable like this:

```
bash, zsh:    export SITE_VIDEO_LLM_MODEL=qwen3:8b
cmd.exe:      set SITE_VIDEO_LLM_MODEL=qwen3:8b
PowerShell:   $env:SITE_VIDEO_LLM_MODEL = "qwen3:8b"
```

### Free and local: Ollama (no API key)

1. Install Ollama from https://ollama.com and start it. It listens on `127.0.0.1:11434`.
2. Pull the default model (a download of about 5 GB): `ollama pull qwen3:8b`
3. Check it: `curl http://127.0.0.1:11434/v1/models` should list `qwen3:8b`.

With Ollama running you need no settings at all. A bigger model writes better scripts. Pick one with
`SITE_VIDEO_LLM_MODEL`, or per video with `--model`. Thinking models work: the reasoning is cut out of the answer.

### Any other OpenAI-compatible service

```
SITE_VIDEO_LLM_URL=https://api.openai.com/v1      SITE_VIDEO_LLM_KEY=sk-...   SITE_VIDEO_LLM_MODEL=<a chat model id from your account>
SITE_VIDEO_LLM_URL=http://127.0.0.1:1234/v1       (LM Studio; set the model to the one you loaded)
SITE_VIDEO_LLM_URL=https://openrouter.ai/api/v1   SITE_VIDEO_LLM_KEY=sk-or-...  SITE_VIDEO_LLM_MODEL=<an id from their list>
```

vLLM, llama.cpp's server and others work the same way: give their `/v1` URL.

The queue page lists the models the endpoint reports (`GET /models`). If your server does not list them, type the id.

### Voice (optional)

Choose the voice per video with `--voice` (or the page's Voice menu). `SITE_VIDEO_DEFAULT_VOICE` sets the default.

| Voice | Needs | Notes |
|---|---|---|
| `none` | nothing | No narration. This is the default and needs no key. |
| `openai[:voice]` | an API key in `SITE_VIDEO_TTS_KEY` (or `OPENAI_API_KEY`) | Any `/audio/speech` API. `SITE_VIDEO_TTS_URL` (default `https://api.openai.com/v1`), `SITE_VIDEO_TTS_MODEL` (default `tts-1`), voice default `alloy`. |
| `openai[:voice]` with a local server | the server's URL | For example a Kokoro-FastAPI server: `SITE_VIDEO_TTS_URL=http://127.0.0.1:8880/v1`, `SITE_VIDEO_TTS_MODEL=kokoro`, `--voice openai:af_heart`. No key needed. Not run by the author. |
| `elevenlabs:<voice id>` | `ELEVENLABS_API_KEY` | `SITE_VIDEO_ELEVENLABS_MODEL` (default `eleven_multilingual_v2`). |
| `odysseus` | `SITE_VIDEO_ODYSSEUS_URL`, `SITE_VIDEO_ODYSSEUS_TOKEN` | Only if you run an Odysseus server. Skip it otherwise. |

The queue page offers only the voices that are configured. `SITE_VIDEO_OPENAI_VOICE` and `SITE_VIDEO_ELEVENLABS_VOICE`
set the voice name or id the page fills in.

### Vision and speech to text (optional)

These matter only for your own videos and for the automatic check of the finished scenes.

| Variable | Default | What it does |
|---|---|---|
| `SITE_VIDEO_VISION_MODEL` | empty | A vision model on the same `SITE_VIDEO_LLM_URL` endpoint, for example `qwen2.5vl:7b`. Describes frames of your videos, and turns on the check that each scene shows what its caption says. |
| `SITE_VIDEO_REVIEW` | `1` | Set to `0` to turn that check off. It only runs when a vision model is set. |
| `SITE_VIDEO_STT` | empty | `openai` for speech to text from your videos. Then `SITE_VIDEO_STT_URL` (default `https://api.openai.com/v1`), `SITE_VIDEO_STT_KEY` (or `OPENAI_API_KEY`), `SITE_VIDEO_STT_MODEL` (default `whisper-1`). A local faster-whisper server works. `odysseus` is the other option. |

## Quick start: your first video, no Resolve

You need the install above and a running model. Everything below works on Windows, macOS and Linux.

1. Pick a site you are allowed to record. Your own site is the best choice. Do not record sites you have no right to show.
2. Run one command:

   ```
   python -m site_video make https://example.com --length 30s --editor ffmpeg --out my-first-video
   ```

   It explores the site, writes the script, records, and edits. It prints progress lines such as `[ 10%] writing the script`.
   A 30 second video takes a few minutes. The model is the slow part.

3. When it ends it prints a JSON summary. The video is at `my-first-video/deliverables/<title>-<id>.mp4`. Open it with any player.
   The folder also has `plan.json` (the script), `log.txt` and `crawl.json`.

Without `--out`, the job goes to `~/site-videos/jobs/<time>-cli/` (`SITE_VIDEO_HOME` moves it).

Want narration? Add `--voice openai:alloy` after setting up a voice. Want a longer video, or a say in what it shows? Use
`--length 2min --notes "show pricing, end on sign-up"`.

The same thing from a web page is in the next section. Your own videos, changing a finished video and the other options
are in [More ways to use site-video](#more-ways-to-use-site-video).

## The queue and its web page

The queue runs several videos at once and gives you a page to use it.

```
python -m site_video serve
```

It prints `site-video on http://127.0.0.1:8940`. Open **http://127.0.0.1:8940/** in a browser. Paste a link, pick a
length, press **Make the video**. You can watch a live picture of what the browser is doing, then play or download the result.

From a terminal, in a second window:

```
python -m site_video add https://example.com --length 30s --editor ffmpeg --wait
python -m site_video list
python -m site_video get <id> -o video.mp4
```

Options of `serve`: `--host` (default `127.0.0.1`), `--port` (default `8940`), `--parallel` (videos prepared at once,
default `2`), `--home` (where jobs and uploads live, default `~/site-videos`).

### Binding safely

- The default is `127.0.0.1`: only this computer can reach it. Keep it that way if you can.
- The queue can make your computer open any web address you give it, upload files to it, and (if you use sign-in) hold
  logins. Treat access to it like access to your account.
- Before you bind to another address (`--host 0.0.0.0` or a LAN or VPN address), set a token **before you start it**:

  ```
  export SITE_VIDEO_TOKEN=a-long-random-string        # cmd.exe: set SITE_VIDEO_TOKEN=...
  python -m site_video serve --host 100.x.y.z
  ```

  Every request then needs `Authorization: Bearer <token>`. In a browser, open `http://100.x.y.z:8940/?token=<token>`
  once. It sets a cookie. The command line tools read `SITE_VIDEO_TOKEN` from your environment.
- The token travels in clear text over plain HTTP. Use a VPN you trust, or put an HTTPS proxy in front. Never forward
  the port on your router.
- Without a token, anyone who can reach the port can use the queue.

## With Resolve: the MCP server

This part needs DaVinci Resolve Studio on the same computer. The author built and used it on Windows only.

**1. Allow scripting in Resolve.** Open Resolve and a project. Go to Preferences > System > General and set **External
scripting using** to **Local**. Restart Resolve if it asks. Keep the project open: the API attaches to the open Resolve.

**2. Start the server.**

Windows: double-click `start-resolve-mcp.cmd`. macOS or Linux: `chmod +x start-resolve-mcp.sh` once, then `./start-resolve-mcp.sh`.

It prints `resolve-mcp on http://127.0.0.1:8930/sse (sse, auth=none, write=on)`. Leave the window open.
Resolve's API only works in your logged-in desktop session, so do not run it as a Windows service.

**3. Connect a client.** Two styles. The **network** style connects by URL to the running server. The **stdio** style makes the client start
the server itself.

*Claude Code* (network):

```
claude mcp add resolve --transport sse http://127.0.0.1:8930/sse
```

With a token (see below) add `--header "Authorization: Bearer YOUR_TOKEN"`. Or use stdio, with your real path:

```
claude mcp add resolve -e RESOLVE_MCP_TRANSPORT=stdio -e RESOLVE_MCP_ALLOW_WRITE=1 -- /path/to/resolve-mcp-kit/.venv/bin/python /path/to/resolve-mcp-kit/resolve_mcp_server.py
```

On Windows use `C:\path\to\resolve-mcp-kit\.venv\Scripts\python.exe` and `C:\path\to\resolve-mcp-kit\resolve_mcp_server.py`.

*Claude Desktop* (stdio): open Settings > Developer > Edit Config. That opens `claude_desktop_config.json`. Merge this in, fix the two
paths, save, and restart Claude Desktop. This is `examples/claude_desktop_config.json`.

```json
{
  "mcpServers": {
    "resolve": {
      "command": "C:\\path\\to\\resolve-mcp-kit\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\resolve-mcp-kit\\resolve_mcp_server.py"],
      "env": { "RESOLVE_MCP_TRANSPORT": "stdio", "RESOLVE_MCP_ALLOW_WRITE": "1" }
    }
  }
}
```

On macOS use `"/path/to/resolve-mcp-kit/.venv/bin/python"` and `"/path/to/resolve-mcp-kit/resolve_mcp_server.py"`.
With stdio you do not need the start script window, but the venv must already exist (run the install above, or run the start script once).

*opencode:* merge the `mcp` block from `examples/opencode.local.json` (stdio, edit the two paths) or
`examples/opencode.remote.json` (URL; it reads the token from `RESOLVE_MCP_TOKEN` in the environment, delete its `headers` block if you set none).
Then run `opencode mcp list`.

*Other clients:* point them at `http://127.0.0.1:8930/sse`, or start with `RESOLVE_MCP_TRANSPORT=streamable-http` and use `http://127.0.0.1:8930/mcp`.

**4. First command.** In your client, ask: "Call `resolve_status`." You should see `connected: true`, the Resolve version and your project.
If you see `connected: false`, the `reason` says what to fix. See [Troubleshooting](#troubleshooting). Then try
"List my projects" and "What is on my timeline?".

**Skills.** `skills/davinci-resolve-editing` and `skills/website-promo-video` teach an agent the editing and video workflows.
Copy a folder to `~/.claude/skills/` (Claude Code) or `~/.config/opencode/skills/` (opencode; on Windows
`%USERPROFILE%\.config\opencode\skills\`). A copy is also in `.claude/skills/`, so opening Claude Code in this folder picks them up.

### What the MCP server can do

Always on (read-only, plus changing the visible page):

| Tool | Purpose |
|---|---|
| `resolve_status` | Is Resolve reachable; product, version, page, project, timeline |
| `list_projects` | Projects in the current database folder |
| `list_timelines`, `timeline_info` | Timelines and their frame range, tracks, fps |
| `list_media_pool` | Clips in a bin: name, duration, fps, resolution |
| `set_page` | Switch to media, cut, edit, fusion, color, fairlight, deliver |
| `project_settings` | Read project settings such as frame rate and resolution |

Editing tools, only when `RESOLVE_MCP_ALLOW_WRITE=1` (the start scripts set it; nothing here deletes anything):

| Tool | Purpose |
|---|---|
| `import_media` | Import files into the media pool, optionally into a bin |
| `create_timeline` | New empty timeline, made current |
| `append_clips` | Append clips in order, optionally trimmed (cuts) |
| `add_title` | Insert a Text+ title and set its text |
| `add_marker` | Timeline marker |
| `save_project` | Save |
| `render_formats_and_codecs`, `start_render`, `render_status` | Queue, start and watch a render |
| `make_site_video`, `site_video_status`, `list_site_videos` | Use a site-video queue (`SITE_VIDEO_SERVER`, default `http://127.0.0.1:8940`) |

### MCP server settings

| Variable | Default | Meaning |
|---|---|---|
| `RESOLVE_MCP_TRANSPORT` | `sse` | `stdio`, `sse`, or `streamable-http` |
| `RESOLVE_MCP_HOST` | `127.0.0.1` | Bind address for sse and http |
| `RESOLVE_MCP_PORT` | `8930` | Port for sse and http |
| `RESOLVE_MCP_TOKEN` | unset | If set, requests need `Authorization: Bearer <token>` |
| `RESOLVE_MCP_ALLOW_WRITE` | `0` (the start scripts set `1`) | Register the editing and render tools |
| `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB` | per system, below | Where Resolve's scripting module lives |

`sse` serves `/sse`. `streamable-http` serves `/mcp`.

The server finds Resolve's scripting module here. Set the two variables if your install is elsewhere.

| System | `RESOLVE_SCRIPT_API` | `RESOLVE_SCRIPT_LIB` |
|---|---|---|
| Windows | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` | `C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll` |
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting` | `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so` |
| Linux | `/opt/resolve/Developer/Scripting` | `/opt/resolve/libs/Fusion/fusionscript.so` |

The Windows paths were used by the author. The macOS and Linux paths come from Blackmagic's documentation and are untried.

**Security.** This server can open, change and render your projects and write files wherever Resolve can. Keep it on
`127.0.0.1`. If the client is on another machine, bind to a LAN or VPN address only, set `RESOLVE_MCP_TOKEN` to a long
random string, and never expose the port to the internet. The token is sent in clear text over plain HTTP, so it stops
casual access, not someone watching your network.

### Making the video in Resolve

With Resolve open, run the queue on the same computer and use `--editor resolve` (or leave it on `auto`, which uses
Resolve when it answers and ffmpeg when not). Each video becomes its own project in a "Site videos" project folder:
track V1 "Picture" with a dissolve on every cut, V2 "Captions", A1 the soundtrack, then a render. You can polish it by hand.

- `SITE_VIDEO_START_RESOLVE` = Resolve's program file: if set, the queue opens Resolve when it is closed and closes it again
  afterward (`SITE_VIDEO_START_RESOLVE_ARGS`, default `-nogui`). Run the queue in your desktop session.
- `SITE_VIDEO_RESOLVE_FOLDER` = the project folder's name (default `Site videos`).
- Resolve 21 opens on its Project Manager screen. While it is up, scripting cannot open or create projects. Open any project first.

## Signing in to your own site

For a site that needs a login, record it signed in. You have two ways. Both save the site's login on the computer that
runs the queue.

**Saved sign-ins are as sensitive as passwords.** Anyone who can read the saved file can act as you on that site.
They are plain files, not encrypted. Keep the folder private, sign in only to sites you own or may record, use a test
account where you can, and delete a sign-in when you are done (`python -m site_video signin https://your.site --forget`).

Saved sign-ins live in `SITE_VIDEO_SESSIONS` (default `~/.site-video/sessions`): one JSON file per site, plus a `profile`
folder that holds the sign-in browser's own profile. Delete the whole folder to forget everything.

### Option 1: sign in with a browser window (Playwright)

Press **Sign in as me** on the page, call `POST /api/signin`, or run:

```
python -m site_video signin https://your.site
```

Your installed Chrome or Edge opens on the queue's computer, with a fresh profile of its own. Sign in by hand. Google
sign-in works, because it is an ordinary browser. Close the window. site-video then reads that site's cookies and
storage and saves them. Your password never passes through site-video. If no Chrome or Edge is found, it uses
Playwright's Chromium, where Google sign-in does not work. Set `SITE_VIDEO_BROWSER` to a browser's program file to pick one.

The window opens on the screen of the computer running the queue. If you are using the queue from another computer, use option 2.

### Option 2: the browser extension (your everyday browser)

The extension sends the sign-in your normal browser already has. Nothing closes and no other profile is used.

**What it can read, plainly.** When you press **Send my sign-in** on a site, it reads, for that site only:

- all of the site's cookies, including HttpOnly cookies, which page scripts cannot normally see;
- the page's `localStorage`;
- the page's IndexedDB records that are plain JSON (where Firebase-style "Sign in with Google" keeps its login).

It sends them to the queue address in its Settings, as `POST <queue>/api/signin/import`, and to nowhere else. It
does nothing until you press the button, and only for the tab that is open. It asks the browser for permission to
read any site (`<all_urls>`), cookies, scripting and storage, because it cannot know in advance which site you will press it on.
The queue token, if you set one, is kept in the extension's browser storage.

Install it:

1. Start the queue (`python -m site_video serve`). Download the extension from the page's "Get the sign-in extension"
   link, or from `http://127.0.0.1:8940/api/signin/extension.zip`. If the queue has a token, open the page with `?token=` first.
2. Unzip it. In Chrome or Edge open `chrome://extensions` (or `edge://extensions`), turn on **Developer mode**, press **Load unpacked**,
   and pick the unzipped `site-video-signin` folder.
3. Open your site in a tab, signed in. Press the extension, then **Send my sign-in**. It shows how many cookies and stored items were saved.

**Where it sends.** The download writes the address of the queue it came from into the extension (`config.js`), so it
points at that queue with nothing hardcoded. If that address is not right, change it under **Settings** in the popup.
If you load the folder `site_video/browser_extension` directly, it starts at `http://127.0.0.1:8940`.

**Plain HTTP warning.** If the queue address is `http://` and not this computer, the popup shows a warning and asks you to
press the button a second time before it sends. Your cookies would cross the network readable by anyone on the path. Use
`https://`, a VPN you trust, or a queue on the same computer.

## What the recorder will and will not do

There are two modes. The first is the default.

**Default mode: look, never change.**

- The recorder blocks every request that is not a plain page load. Only GET, HEAD and OPTIONS go out. A form submit or any
  other write is aborted. Trackers and analytics are blocked too.
- It does not log in by itself. It uses a saved sign-in only if you made one for that site.
- It moves around the way a viewer would: it scrolls, points at things, opens links and tabs, and types into search
  boxes. The script is told not to click anything that logs in, buys, deletes or submits a form, and buttons labeled
  like delete, remove, buy, pay or sign out are never clicked.
- The limit: a site that changes data on a plain page load (a GET) is not protected by this. Only record sites you may show.

**Opt-in mode: your own site, changes allowed.** Turn it on with the page's "This is my site" box, `--my-site` on
`make` and `add`, or `"changes": true` in the API. Then:

- Every request except DELETE goes out, so the video can press buttons that save, create or convert things, as your notes ask.
- Your notes become the script's workflow: "paste a list, press Evaluate, open the result".
- Buttons labeled like delete, remove, erase, buy, purchase, pay, subscribe, cancel account or sign out are still never clicked. That is a
  check on the visible label. It is not a guarantee.
- **Use a test account.** This mode really creates and changes things on the site. Pair it with a saved sign-in for the test account, not your real one.

## More ways to use site-video

### What happens in a video

1. **Explores the site.** Every same-site page it can reach by links, up to 60 pages in about 4 minutes
   (`SITE_VIDEO_EXPLORE_PAGES`, `SITE_VIDEO_EXPLORE_SECONDS`). Sign-in, cart and legal pages are left out. Each page is
   scored for real content, its search fields are tried with an example from the site's own items, and with a vision
   model set the best views are described.
2. **Reads the brand:** background, text and main colors, heading font and logo.
3. **Writes a script** with your model: a title card, a "the problem" card, 6 to 10 short scenes that each show one
   feature working, captions, narration, and a closing card with the site's address. It fits the length you ask for and your notes.
4. **Records the real site** in Chromium at 1920x1080, 30 fps, with a soft cursor, eased scrolls and real typing. The waiting
   is cut out and each scene is sped up (to 2.4x at most) to fit.
5. **Draws the cards and captions** in the site's own font and colors, and **adds the voiceover**.
6. **Edits it** in Resolve or with ffmpeg.
7. **Checks the video against the script** (needs `SITE_VIDEO_VISION_MODEL`): each scene is scored 1 to 5 for showing what
   its caption says. A scene that clearly failed is rewritten and recorded again, once. Verdicts are in `review.json`.

**Notes are a brief.** Write a wish ("show pricing") or paste a whole outline with scenes, text to paste and
narration. The script follows its order and types or pastes the text you give. Pages named in the notes are always explored.

### One video in a terminal

```
python -m site_video make https://example.com --length 2min --notes "show pricing, end on sign-up" --voice openai:alloy
```

- `--length`: `5min`, `90s`, `1:30` or `auto`. Requested lengths are targets: a scene is never shorter than its
  narration, and the cards add a few seconds.
- `--notes`: plain words or `auto`.
- `--editor`: `auto` (Resolve if it is open, else ffmpeg), `resolve` or `ffmpeg`.
- `--model`: the model for this video (default `SITE_VIDEO_LLM_MODEL`).
- `--music file.mp3`: music under the voice, quieter while it speaks.
- `--cursor`: `dot` (default), `arrow`, `hand`, `ring`, `auto` or `none`. See `/cursors` on the queue page to compare.
- `--deliver`: what to hand back (below).
- `--my-site`: the opt-in mode above.

### Your own videos

A job can use a website, your own videos, or both.

| You have | You give | What happens |
|---|---|---|
| A website | the link | The site is recorded |
| Videos, no website | the videos, each with a note | The script picks moments from your videos, with narration over them or their own sound |
| Both | both, and a length | Your videos go in where they fit, website scenes fill the rest |

```
python -m site_video make --video demo.mp4 --note-for "the app demo" --video talk.mov --length 2min
python -m site_video make https://example.com --video demo.mp4 --video promo.mp4 --length 5min
```

Before writing the script it watches each video: a frame every few seconds described by the vision model, and what is
said, by time, from speech to text. Without them it knows only your notes and each video's length, so describe the
videos well. Your videos are cut, never sped up or slowed. Each one is used at least once.

### Changing a finished video

On the page, press **Change** on a job. Describe the change in words ("in scene 3, point at the Pro plan instead") and
press **Apply to the script**, or edit the script yourself. Then **Redo the video**: only the scenes that changed are
made again. From a terminal: `python -m site_video change <id> "point at the Pro plan in scene 3" [--dry-run]`.
The old script is kept as `plan.<n>.json`.

### Deliverables

`--deliver`, the page's Deliverables row, or `deliverables` in the API choose what you get back:

| Name | What |
|---|---|
| `video` | The rendered MP4 (always) |
| `script` | `script.md` (scenes, captions, actions, narration) and `plan.json` |
| `voiceover` | One WAV per narration line and `soundtrack.wav` |
| `clips` | The recorded scenes and cards, 1920x1080 30 fps |
| `timeline` | The Resolve timeline as `.drt`, `.fcpxml` and `.edl` (Resolve edits only) |
| `resolve_project` | The video's own Resolve project as `.drp` (Resolve edits only) |
| `package` | One zip with all of the above and a README on importing |

### From an agent

With the MCP server running and a queue at `SITE_VIDEO_SERVER`, an agent can call `make_site_video`, `site_video_status` and
`list_site_videos`. The `website-promo-video` skill teaches it to turn "make a 5 minute video of this site, show X" into a job.

### Optional: as an Odysseus mod

`odysseus-mod.json` and `site_video/odysseus_mod.py` let an Odysseus server run site-video as a tab and chat tools. You
do not need this for anything above.

### All site-video settings

| Variable | Default | What |
|---|---|---|
| `SITE_VIDEO_LLM_URL`, `_LLM_MODEL`, `_LLM_KEY` | local Ollama, `qwen3:8b`, empty | The script model (see Model setup) |
| `SITE_VIDEO_REPAIR_MODEL` | the job's script model | The model that works out a step again when a button is not where the script says (own-site mode) |
| `SITE_VIDEO_DEFAULT_VOICE` | `none` on the command line | The voice when a job names none |
| `SITE_VIDEO_TTS_URL`, `_TTS_KEY`, `_TTS_MODEL` | OpenAI, empty, `tts-1` | An OpenAI-compatible voice |
| `SITE_VIDEO_OPENAI_VOICE`, `SITE_VIDEO_ELEVENLABS_VOICE` | `alloy`, empty | The voice name the page fills in |
| `ELEVENLABS_API_KEY`, `SITE_VIDEO_ELEVENLABS_MODEL` | empty, `eleven_multilingual_v2` | ElevenLabs |
| `SITE_VIDEO_VISION_MODEL`, `SITE_VIDEO_REVIEW` | empty, `1` | Frame descriptions and the scene check |
| `SITE_VIDEO_STT`, `_STT_URL`, `_STT_KEY`, `_STT_MODEL` | empty, OpenAI, empty, `whisper-1` | Speech to text for your videos |
| `SITE_VIDEO_EXPLORE_PAGES`, `SITE_VIDEO_EXPLORE_SECONDS` | `60`, `240` | How far the explorer goes |
| `SITE_VIDEO_HOME` | `~/site-videos` | Jobs and uploads |
| `SITE_VIDEO_TOKEN` | unset | If set, the queue's API and page need it |
| `SITE_VIDEO_SERVER` | `http://127.0.0.1:8940` | The queue the command line tools and the MCP server talk to |
| `SITE_VIDEO_MAX_UPLOAD_MB` | `4096` | Largest upload the queue accepts |
| `SITE_VIDEO_MEDIA_DIRS` | empty | Folders (`;` on Windows, `:` elsewhere) whose videos API jobs may use without uploading |
| `SITE_VIDEO_SESSIONS`, `SITE_VIDEO_BROWSER` | `~/.site-video/sessions`, auto | Saved sign-ins; the Chrome or Edge used to sign in |
| `SITE_VIDEO_RESOLVE_FOLDER`, `SITE_VIDEO_START_RESOLVE`, `SITE_VIDEO_START_RESOLVE_ARGS` | `Site videos`, empty, `-nogui` | The Resolve edit |
| `FFMPEG` | the bundled copy | Your own ffmpeg |

The queue's HTTP API is listed at the top of `site_video/server.py`.

### Limits

- The Resolve edit runs on the computer with Resolve and switches it to the "Site videos" project for the edit, then opens
  your project again. A Resolve the queue opened is closed afterward; one you opened is left open.
- Sites that need a login (and you did not sign in), block headless browsers or show a full-screen pop-up the recorder
  cannot dismiss will not record well.
- A 30 second request usually comes out at 35 to 40 seconds, because of the cards.

## Troubleshooting

| You see | What it means and what to do |
|---|---|
| `Could not attach to Resolve` | Resolve is not running, or scripting is off, or you have the free edition. Open Resolve, set Preferences > System > General > External scripting using to Local. Free Resolve often cannot do this at all. |
| `Resolve's scripting module is not importable` | The server cannot find `DaVinciResolveScript`. Check Resolve is installed. Set `RESOLVE_SCRIPT_API` to its `Developer/Scripting` folder. |
| `No project is open in Resolve` | Open a project. |
| `Resolve would not open or create the project folder` | Resolve is on its Project Manager screen. Open any project, then try again. |
| `DaVinci Resolve is not running here` | You asked for `--editor resolve`. Open Resolve, set `SITE_VIDEO_START_RESOLVE`, or use `--editor ffmpeg`. |
| `No site-video queue at http://...` | An MCP tool could not reach the queue. Start it (`python -m site_video serve`) or set `SITE_VIDEO_SERVER`. |
| `Executable doesn't exist ... playwright install` | Chromium is missing. Run `python -m playwright install chromium` with the venv's Python (the same one that runs the queue). |
| `Host system is missing dependencies` (Linux) | `sudo .venv/bin/python -m playwright install-deps chromium` |
| `Connection refused` or `urlopen error` while writing the script | The model server is not running or the URL is wrong. Check `SITE_VIDEO_LLM_URL` with `curl <url>/models`. |
| `HTTP Error 404` while writing the script | The model name is not on the server. For Ollama run `ollama pull <model>`, or fix `SITE_VIDEO_LLM_MODEL`. |
| `HTTP Error 401` | The API needs a key. Set `SITE_VIDEO_LLM_KEY` (or the voice or speech key). |
| `used all N tokens thinking and gave no answer` | A thinking model ran out of room. Pick a smaller or non-thinking model. |
| `the model did not write a usable plan` | The model could not produce the JSON script in three tries. Use a bigger model. The log shows each attempt. |
| `could not open <url>` | The explorer could not load the site: wrong address, no network, or the site blocks headless browsers. |
| `ffmpeg failed: ...` | ffmpeg rejected a step. The message ends with its output. Update `imageio-ffmpeg` or set `FFMPEG` to a full build with libx264. |
| `token required` (401) | The queue has `SITE_VIDEO_TOKEN`. Open the page with `?token=...`, or set `SITE_VIDEO_TOKEN` for the command line. |
| `a sign-in window for <site> is already open` | Close the earlier sign-in window first. |
| `nothing from <site> came with it` | The extension found no cookies. Open the site in that tab, signed in, and press it again. |
| `Address already in use` | Another program uses the port. Pass `--port`, or set `RESOLVE_MCP_PORT`. |
| PowerShell will not activate the venv | Run `.venv\Scripts\python.exe` instead of `python`, or allow scripts for your user with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |

A job's log is `log.txt` in its folder, and a failed stage's output is `stage.out`. A failed job can be retried from its last finished stage.

## What is tested, and what is not

- **Tested by the suite:** `python -m pytest tests` runs about 80 tests with a fake Resolve and fake models. They check
  the MCP server's tools and arguments, the script checker, the queue, the HTTP API, length and voice parsing, the browser
  extension's address handling, and that no tailnet address or personal path is hardcoded.
- **Run end to end on Linux (Ubuntu 24.04, Python 3.12):** the install above, the test suite, the queue and its page, and a video made through
  the ffmpeg editor of a small local page, with a stand-in for the language model.
- **Developed on Windows with Resolve Studio 21.1:** the Resolve edit and render. They were not run again while this guide was written.
- **Not tested:** macOS anywhere; Resolve on Linux; free Resolve; the MCP editing tools (`add_title`, `append_clips`, codec keys
  for `start_render`) against a real Resolve, only against a fake; the browser extension and the sign-in window in a real browser while this guide was written; ElevenLabs, Kokoro and speech to text servers; the Odysseus mod outside its own tests.

## License

MIT, see `LICENSE`. DaVinci Resolve is a trademark of Blackmagic Design. This project is not affiliated with it.
