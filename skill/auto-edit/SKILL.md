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
4. Ask once: sound effects, yes or no? Music: their own file, the built-in beat, or none?
5. Run `autoedit "VIDEO" --hook "..." --cut A-B [--sfx] [--music FILE|bed]`, and add `--fix "wrong=right"` for
   misheard names or words you spotted. If speech recognition mangled a language, add `--lang`.
6. Check the result: extract a few frames with ffmpeg and look at them. Confirm that the hook is on frame 0, text doesn't
   cover the face, and retakes are gone. Say what you checked.
7. Tell them where the file is and that they should watch it before posting. Never post it.

If a command fails, run `autoedit doctor` and fix what it names. Never change or delete the original video.
