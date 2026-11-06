#!/usr/bin/env python3
"""Writes a greyscale person mask video with Google's MediaPipe, for Windows. Usage: personmask.py in.mp4 mask.mp4 [FRAMES]

FRAMES, such as 60-120,300-390, limits the work to those frames (end excluded); the rest come out black.
Same job as personmask.swift, which uses Apple's Vision on a Mac.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

MODEL = Path(__file__).resolve().parent / "models/selfie_multiclass_256x256.tflite"
SMALL_W, SMALL_H = 360, 640  # the model sees 256x256, so full-size frames only cost time


def main(src, out, frames=None):
    wanted = [tuple(int(x) for x in part.split("-")) for part in frames.split(",")] if frames else None
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                                      "-of", "json", src], capture_output=True, text=True, check=True).stdout)["streams"][0]
    options = vision.ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), running_mode=vision.RunningMode.VIDEO,
                                           output_confidence_masks=True, output_category_mask=False)
    reader = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"scale={SMALL_W}:{SMALL_H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              stdout=subprocess.PIPE)
    writer = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{SMALL_W}x{SMALL_H}",
                               "-r", info["r_frame_rate"], "-i", "-", "-vf", f"scale={info['width']}:{info['height']}:flags=bicubic",
                               "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    size, count, black = SMALL_W * SMALL_H * 3, 0, bytes(SMALL_W * SMALL_H)
    with vision.ImageSegmenter.create_from_options(options) as segmenter:
        while True:
            raw = reader.stdout.read(size)
            if len(raw) < size:
                break
            if wanted and not any(a <= count < b for a, b in wanted):
                writer.stdin.write(black)
            else:
                frame = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.frombuffer(raw, np.uint8).reshape(SMALL_H, SMALL_W, 3))
                background = segmenter.segment_for_video(frame, count * 33).confidence_masks[0].numpy_view()  # class 0 is background
                writer.stdin.write(((1 - background) * 255).clip(0, 255).astype(np.uint8).tobytes())
            count += 1
    writer.stdin.close()
    if reader.wait() or writer.wait():
        sys.exit("Making the person mask failed.")
    print(f"{count} frames")


if __name__ == "__main__":
    main(*sys.argv[1:4])
