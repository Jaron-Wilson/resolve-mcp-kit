---
name: davinci-resolve-editing
description: Edit video in DaVinci Resolve through the resolve MCP server. Use when asked to import footage, build a timeline from clips, make cuts, add titles or markers, or render/export a cut from Resolve.
license: See the LICENSE file of resolve-mcp-kit
compatibility: opencode, Claude Code. Requires the resolve MCP server from resolve-mcp-kit running next to an open DaVinci Resolve.
metadata:
  server: resolve-mcp-kit
---

# DaVinci Resolve editing

You drive a real, open DaVinci Resolve through the `resolve` MCP server. In
opencode the tools appear prefixed with the server name (for example
`resolve_list_timelines`); in Claude Code as `mcp__resolve__list_timelines`.
Use whichever form your client shows.

## Ground rules

- Resolve must be open with a project loaded in its window. If `resolve_status`
  says `connected: false`, tell the user why (the reason text is specific) and
  stop. Do not retry in a loop.
- Paths passed to `import_media` and `start_render` are paths on the machine
  running Resolve, not on yours. Use absolute paths.
- Editing tools only exist when the server runs with `RESOLVE_MCP_ALLOW_WRITE=1`.
  If `import_media` and friends are missing, say so and ask the user to enable it.
- Nothing here deletes clips, timelines, or files. Even so, never overwrite a
  render: give each one a new name (add a timestamp or a version).
- Work in a NEW timeline rather than editing the user's existing one, unless
  they asked you to change that timeline.
- Frame numbers: `start_frame`/`end_frame` on a clip are source-clip frames at
  the clip's own frame rate (end inclusive). Convert seconds with
  `frame = round(seconds * fps)`; get `fps` from `list_media_pool`.

## Workflow: orient first (read only)

1. `resolve_status` - connected? which project, page, timeline.
2. `list_timelines`, `timeline_info` - what exists.
3. `project_settings` - frame rate and resolution. Timelines inherit these, so
   mismatched clip frame rates will be conformed. Tell the user if the project
   rate differs from the footage.
4. `list_media_pool` (optionally a `folder`) - names, durations, fps.

## Workflow: build a timeline from clips

1. `import_media` with the file paths and a `folder` name such as the project
   or shoot name. Check `imported` has as many entries as `requested`; if not,
   report the missing files.
2. `list_media_pool` with that folder to learn the exact clip names and fps.
3. `create_timeline` with a descriptive, unique name (it becomes current).
4. `append_clips` with the clips in order. One call with the whole ordered list
   is better than many small ones, because order is preserved.
5. `set_page` to `edit` so the user can see the result, then `save_project`.
6. Summarize: timeline name, clip count, total duration.

## Workflow: cuts

A cut is a trimmed clip. In `append_clips` give each entry
`start_frame` and `end_frame` in source frames:

```
{"clips": [
  {"name": "interview.mov", "start_frame": 240, "end_frame": 960},
  {"name": "broll_01.mov",  "start_frame": 0,   "end_frame": 119},
  {"name": "interview.mov", "start_frame": 1200, "end_frame": 1800}
]}
```

The same source can appear several times with different ranges. To change a
cut, build a new timeline (`... v2`) rather than trying to edit in place.
`add_marker` at a timeline frame is a good way to flag spots for the user to
review (for example `color: "Red"` for problems, `"Green"` for approved).

## Workflow: titles

1. Position matters: `add_title` inserts at the playhead, which this server does
   not move. For a title at the start, add it before appending clips, or tell
   the user to drag it into place after.
2. `add_title` with `text` and the default `Text+` generator. If the result has
   `text_set: false`, the title was inserted but the user must type the text.
3. Verify with `timeline_info` and tell the user what to check on the Edit page.

## Workflow: render

1. `render_formats_and_codecs` for `mp4` to see codec keys. Prefer an H.264 key
   for sharing; names differ by machine (some are GPU encoders, e.g. with
   NVIDIA in the key). If a render fails with a codec error, try another key.
2. `start_render` with `target_dir` (an existing folder), a unique `name`
   (no extension), the `format`, `codec`, and optionally `width`/`height`.
   Only one render can run at a time; a refusal usually means one is active.
3. Poll `render_status` with the returned `job_id` every 15 to 30 seconds. Look
   at `status.JobStatus` and `status.CompletionPercentage`. Report progress
   to the user sparingly, not on every poll.
4. When `JobStatus` is `Complete`, give the user the full output path
   (`target_dir` plus `name` plus extension). If it is `Failed`, report
   `status.Error` verbatim.

## Things that commonly go wrong

- A null page in `resolve_status` means Resolve is on the Project Manager
  screen. Project queries work but `set_page` does not; ask the user to open a
  project in the Resolve window.
- `create_timeline` fails if the name already exists. Pick a new name.
- `append_clips` names must match the media pool names exactly, including the
  extension. The call fails without appending anything if one name is wrong.
- Long operations can exceed the client's tool timeout. For renders, always
  start and then poll; never wait inside one call.
