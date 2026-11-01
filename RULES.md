# The editing rules

The house style behind Auto Edit. It draws on ideas from Mino Lee's free editing resource, written here in our own
words and tested on real reels. Mino ([@minolee.mp4](https://www.instagram.com/minolee.mp4/)) isn't involved with this project and hasn't endorsed it.

## What Auto Edit does for you

- **Hard cuts only.** No fades, blur or slow zooms. Pauses are removed.
- **The camera stays still.** No automatic zoom on cuts. Zoom is for a line you choose, in another editor.
- **Hook on screen from the first frame.** It just appears, with no animation, and never covers your face.
- **Short captions.** Two or three words at a time, in one plain font, white with a soft shadow, centred mid-frame.
  Captions never end on a weak word like "the" or "ang".
- **Stay out of the app's way.** Text sits clear of the top bar, the bottom caption area and the right-side buttons.
- **Voice first.** Music sits at 25% under the hook, then 10%, and dips when you talk.
- **Sound effects are a seasoning.** Real recordings, off by default. A pop on the hook, a quiet whoosh on some cuts, and
  hits or paper flips on graphics, each peaking on the frame it belongs to.
- **Consistent loudness.** Every export lands around -15 LUFS, so reels match each other.

## Two styles

Don't mix them in one reel. They pull in opposite directions.

- **Clean** (default) follows the rules above: the words do the work, and nothing moves.
- **Behind you** puts big words and pop-up cards behind your head, using `--behind` and `--popup`. It's louder and suits
  list and explainer reels. Graphics stay above your shoulders, so wear something plain and leave space around your head.

## What's still your job

- **Say the hook first.** The tool uses your first sentence if it's short. A strong one beats any edit.
- **Film it well.** Vertical, phone at eye level, head in the upper third, quiet room, facing a window.
- **Remove your retakes.** The tool cuts silence but can't tell which take you preferred. Run
  `autoedit transcript video.mov` to see the timestamps, then `--cut 12.3-14.1` to remove a part.
- **Read every caption.** Speech recognition misspells words, especially names and Taglish. Fix with
  `--fix "wrong=right"`.
- **Use music you have the rights to.** Pixabay Music and Meta's Sound Collection are good starting points. Don't rip
  songs from other people's reels.
