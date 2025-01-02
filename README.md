# ffstuff

Collection of wrapper utilities for working with ffmpeg.

You must have ffmpeg installed and available on your `$PATH` as `ffmpeg`.

If you want to use a different path to ffmpeg, create the environment variable `FFSTUFF_FFMPEG_PATH` with the appropriate path to ffmpeg as the value.
If this variable exists, its value will always be used instead of trying to use `ffmpeg` from your PATH.

## What's in the box?

- ffcat: concatenate one or more video files together
- ffautocrop: automatically crops off those black bars from videos

## Installing

I personally make symbolic links to each of the binaries in a particular directory. Up to you how you want to do it.

