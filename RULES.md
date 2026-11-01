# The editing rules

The house style behind Auto Edit. It draws on ideas from Mino Lee's free editing resource, written here in our own
words and tested on real reels. Mino Lee isn't involved with this project and hasn't endorsed it.

## What Auto Edit does for you

- **Hard cuts only.** No fades, blur or slow zooms. Pauses are removed.
- **Punch in on cuts.** Every other section sits 12% tighter, so a jump cut looks deliberate.
- **Hook on screen from the first frame.** It just appears, with no animation, and never covers your face.
- **Short captions.** Two or three words at a time, in one plain font, white with a soft shadow, centred mid-frame.
  Captions never end on a weak word like "the" or "ang".
- **Stay out of the app's way.** Text sits clear of the top bar, the bottom caption area and the right-side buttons.
- **Voice first.** Music sits at 25% under the hook, then 10%, and dips when you talk.
- **Sound effects are a seasoning.** A pop on the hook, soft whooshes at least 3 seconds apart. They're off by default.
- **Consistent loudness.** Every export lands around -15 LUFS, so reels match each other.

## What's still your job

- **Say the hook first.** The tool uses your first sentence if it's short. A strong one beats any edit.
- **Film it well.** Vertical, phone at eye level, head in the upper third, quiet room, facing a window.
- **Remove your retakes.** The tool cuts silence but can't tell which take you preferred. Run
  `autoedit transcript video.mov` to see the timestamps, then `--cut 12.3-14.1` to remove a part.
- **Read every caption.** Speech recognition misspells words, especially names and Taglish. Fix with
  `--fix "wrong=right"`.
- **Use music you have the rights to.** Pixabay Music and Meta's Sound Collection are good starting points. Don't rip
  songs from other people's reels.
