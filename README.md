# Auto Edit

Turn a raw talking video into a ready-to-post vertical reel on your Mac: silences cut, hook on screen, captions timed
to your words, and optional sound effects.

Free. No account or API key. Your video stays on your computer, nothing gets posted, and your original file isn't
changed.

## Install

Open **Terminal** (press Cmd+Space, type Terminal, press Enter), paste this line, and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/paolo-segura/auto-edit/main/install.sh | bash
```

It takes 5 to 15 minutes and may ask for your Mac password (the characters don't show as you type). You'll need about
5 GB free. It installs Homebrew, ffmpeg, Node, Python and whisper-cpp if they're missing.

Or, if you use Claude Code, paste this prompt into it:

```text
Install Auto Edit for me from https://github.com/paolo-segura/auto-edit by running its install command from the README.
If it needs my Mac password, stop and tell me to run that one command in Terminal myself. When it finishes, run
`autoedit doctor` and tell me how to edit my first video.
```

## Use

Double-click **Auto Edit** on your Desktop. Drag your video into the window, then answer a few questions: style, hook, sound
effects, and music. The finished reel lands next to your original, ending in `-edited.mp4`.

The first time, macOS may block it. Right-click the file, choose **Open**, then **Open** again. Your first edit also
downloads a speech model of about 500 MB.

A 90-second video took about 2 minutes on an M4 Pro. Older Macs will be slower.

## Command line

```bash
autoedit video.mov                        # cuts, hook, captions
autoedit video.mov --sfx                  # add sound effects
autoedit video.mov --behind "fear,lazy"   # big words behind you when you say them
autoedit video.mov --popup "plan=My plan" # pop-up card behind you (short text or an image file)
autoedit video.mov --music song.mp3       # your own music (--music bed for the built-in beat)
autoedit video.mov --hook "Your hook"     # your own hook
autoedit video.mov --fix "wrong=right"    # correct a misheard word
autoedit transcript video.mov             # see what you said, with timestamps
autoedit video.mov --cut 12.3-14.1        # remove a bad take, using those timestamps
autoedit doctor                           # check your setup
```

`autoedit --help` lists the rest. See [RULES.md](RULES.md) for the editing style.

## Make it yours

The defaults are only a starting point.

- **Hook:** type your own when the app asks, or use `--hook "Your hook"`.
- **Design:** create `~/.auto-edit/custom.css` to change the hook, captions and graphics. Updates never touch it. For
  example, `.hook { background:#ffe14d; }` or `.cap { font-size:60px; }`. The classes are `.hook`, `.cap`, `.big` and `.card`.
- **Claude's editing style:** edit `~/.claude/skills/auto-edit/SKILL.md`. Reinstalling keeps your version.
- **Anything else:** fork this repo and edit `autoedit.py`. To install your fork, set `AUTO_EDIT_REPO` to its URL before
  running your copy of `install.sh`.

Run the install command again to update. If you edited the files in `~/.auto-edit` directly, the update stops rather than
overwrite them, so keep your changes in `custom.css` or a fork.

## With Claude Code (optional)

If you have Claude Code installed before you run the installer, you can say "edit this video" and Claude will read your
transcript, remove retakes, write a stronger hook and fix captions. Claude Code needs a paid Claude plan. Auto Edit
doesn't.

## Limits

- Mac only, for now.
- Made for one person talking. It stops if it finds no speech.
- Landscape videos get a centre crop (`--crop-x` shifts it). Vertical footage looks best.
- Rendering needs an internet connection, because one animation library loads online.

## Stuck?

Run `autoedit doctor`. It names what's missing and how to fix it.

This is a free gift, provided as is, so I can't promise support.

## Credits

Built by [Paolo Segura](https://github.com/paolo-segura). Editing style informed by the free editing rules from Mino Lee ([@minolee.mp4](https://www.instagram.com/minolee.mp4/)), who isn't involved with this project.
Built on [HyperFrames](https://github.com/heygen-com/hyperframes) (Apache-2.0), [FFmpeg](https://ffmpeg.org),
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) (MIT), [Silero VAD](https://github.com/snakers4/silero-vad) (MIT, in `models/`) and GSAP (free under its own license). Sound effects are public domain, listed in [sounds/CREDITS.md](sounds/CREDITS.md). Captions use
[TikTok Sans](https://github.com/tiktok/TikTokSans) (SIL OFL, see `fonts/OFL.txt`). Auto Edit's own code is MIT.
