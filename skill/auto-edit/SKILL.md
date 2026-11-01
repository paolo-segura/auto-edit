---
name: auto-edit
description: Edit a raw talking video into a vertical reel with the local `autoedit` tool (cuts, hook, captions, optional sound effects). Use when the user says "edit this video", "auto edit", or "make this a reel" and gives a video file.
---

# Auto Edit

Follow `~/.auto-edit/RULES.md`. Your job is what the tool can't judge: retakes, the hook, and caption mistakes.

1. Run `autoedit transcript "VIDEO"` and read it.
2. Find retakes and fumbles. Keep the last good take. Note each bad part as `--cut START-END`, in seconds. Times are
   approximate, so check word boundaries against the transcript.
3. Write one hook: the most surprising true thing the speaker actually says, 12 words or fewer. Don't invent claims, numbers
   or results.
4. Ask once: clean style, or graphics behind them? Sound effects, yes or no? Music: their own file, the built-in beat, or
   none? For behind-you, pick 2 to 5 words they actually say and pass `--behind "a,b"`, with optional
   `--popup "word=short text or image file"`. Don't invent content.
5. Run `autoedit "VIDEO" --hook "..." --cut A-B [--behind WORDS] [--sfx] [--music FILE|bed]`, and add `--fix "wrong=right"` for
   misheard names or words you spotted. If speech recognition mangled a language, add `--lang`.
6. Check the result: extract a few frames with ffmpeg and look at them. Confirm that the hook is on frame 0, text doesn't
   cover the face, and retakes are gone. Say what you checked.
7. Tell them where the file is and that they should watch it before posting. Never post it.

If a command fails, run `autoedit doctor` and fix what it names. Never change or delete the original video.

## Changing the look

To change the hook, captions or graphics, write CSS to `~/.auto-edit/custom.css`. It loads after the defaults and updates
never touch it. The classes are `.hook`, `.cap`, `.big` and `.card`. Keep text clear of the app's buttons (top y0-288,
bottom y1536+, and x900+ from y960 down). To change how you work, edit this skill file; reinstalling won't overwrite it.
