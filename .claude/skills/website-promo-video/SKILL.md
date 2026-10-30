---
name: website-promo-video
description: Make a narrated promo or walkthrough video of a website from its link, edited in DaVinci Resolve (or ffmpeg). Use when asked to "make a video of this site", "go through this website and make a video", or to queue several site videos.
license: See the LICENSE file of resolve-mcp-kit
compatibility: opencode, Claude Code, any MCP client. Needs a site-video queue (python -m site_video serve) and, for the Resolve edit, the resolve MCP server next to an open DaVinci Resolve.
metadata:
  server: resolve-mcp-kit
---

# Website promo videos

A site-video queue turns a link into a finished MP4: it reads the site, writes a script, records the real site in a
browser (smooth scrolling, a visible cursor, lower-third captions), adds a voiceover, and edits it. In DaVinci
Resolve the edit is a new timeline in the "Site videos" project, with a marker per scene, so a person can polish it
afterwards; without Resolve it is joined with ffmpeg.

## Tools

From the `resolve` MCP server (prefixed in your client, e.g. `resolve_make_site_video`):

- `make_site_video(url, length, notes, voice, editor, name)`: queue one. Returns a job id at once.
- `site_video_status(job_id)`: where it is. Done jobs carry `video` (a path on the queue's machine) and `download`.
- `list_site_videos(limit)`: the newest jobs.

No MCP? The same queue has a command line and an HTTP API:
`python -m site_video add URL --length 5min --notes "..." --voice odysseus --wait`, or `POST /api/jobs`.

## Turning a request into a job

People ask in their own words. Map them like this:

| They say | Argument |
|---|---|
| "5 min", "a 90 second video", "about two minutes" | `length`: `5min`, `90s`, `2min` |
| no length, "auto", "whatever fits" | `length`: `auto` (usually 1 to 2 minutes) |
| "make sure you show X", "end on Y", "for an audience of Z", "upbeat" | `notes`: their words, kept whole |
| nothing about content, "auto" | `notes`: `auto` |
| "with ElevenLabs voice ...", "no voice", "use my voice" | `voice` (see below); otherwise leave it empty for the default |
| "use gemma4 / the 27b / GPT for the script" | `model`: the matching id from the queue's models; otherwise leave it empty |
| "two videos at once", a list of links | one `make_site_video` call per link; the queue runs 2 at a time |

Voices: `none`, `openai[:voice]` (OpenAI or a Kokoro-FastAPI server, e.g. `openai:af_heart`), `elevenlabs:<voice id>`,
`odysseus`. If the voice they named is not configured on the queue, the job fails with a clear reason: tell them.

## Ground rules

- Only make videos of sites the person owns or has every right to show. The recorder never logs in, buys,
  submits forms or deletes anything, and the script it writes is told the same.
- A video takes a few minutes (a 5 minute one, 10 to 20). Do not poll in a tight loop: check
  `site_video_status` every 30 to 60 seconds, or tell the person the job id and that it is running.
- Report the result plainly: the length, where the file is (`video`) and the `download` link. If it failed, give
  the `error`; `retry` keeps the stages that finished, so a second try is quicker.
- Edits run one at a time, since one Resolve renders one thing. "waiting" means it is ready and in line for the
  editor, not stuck.
- Resolve edits happen in the "Site videos" project; the person's open project is saved first and opened again
  afterwards. If they are working in Resolve, mention that a video edit will briefly switch projects, or use
  `editor: ffmpeg`.
