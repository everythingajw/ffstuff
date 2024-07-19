#!/usr/bin/env python3
import math
import sys
import os
import argparse
import tempfile
from pathlib import Path
import subprocess
import re
import itertools
from typing import Tuple
from typing import List
from typing import Optional
from typing import Any
import utils
import collections
import multiprocessing
import multiprocessing.pool


def get_cropdetect_chunk_starts(video_path: str | Path, num_chunks: int) -> List[float]:
    if num_chunks <= 0:
        raise ValueError(f"Number of chunks must be at least 1 (was {num_chunks})")

    video_duration = utils.get_media_duration(video_path)

    chunk_size = round(video_duration / num_chunks, 3)
    if chunk_size < 1:
        raise ValueError("Attempt to chunk video multiple times per second")

    chunk_starts = []
    current_chunk_start = 0
    for _ in range(num_chunks):
        chunk_starts.append(round(current_chunk_start, 3))
        current_chunk_start += chunk_size
    return chunk_starts


def cropdetect_chunk(video_path: str | Path, start: float, chunk_length: float,
                     video_codec: str) -> collections.Counter:
    # It would be nice to use the copy codec instead of a "regular" codec, but "filtering and streamcopy cannot
    # be used together". Don't know why, that's just the way it is.
    ff_args = ["ffmpeg", *utils.get_ffmpeg_common_options(log_level="info", show_stats=True),
               "-ss", round(start, 3), "-i", video_path, "-t",
               round(chunk_length, 3), "-c:v", video_codec, "-vf", "cropdetect", "-f", "null", "-"]
    crops = subprocess.check_output([str(a) for a in ff_args], stderr=subprocess.STDOUT).decode().splitlines()
    crops = utils.flatten(re.findall(r"(?<=crop=)\d+:\d+:\d+:\d+", c) for c in crops)
    crops = map(lambda point: tuple(int(s.strip()) for s in point.split(":")), crops)

    # Keeping only length 4 tuples probably isn't the best way to do this, but it'll do.
    return collections.Counter(c for c in crops if len(c) == 4)


def cropdetect_video(video_path: str | Path, num_cropdetect_chunks: int,
                     cropdetect_chunk_duration: float, video_codec: str) -> collections.Counter:
    """
    Apply crop detection to an entire video.
    :param video_path: The path to the video
    :param num_cropdetect_chunks: The number of equally sized chunks to break the video into to perform crop detection on.
    :param cropdetect_chunk_duration: The length of each chunk to cropdetect.
    :return: A counter counting the crop point and the number of times it occurred.
    """
    if num_cropdetect_chunks <= 0:
        raise ValueError("Number of chunks must be at least 1")
    cropdetect_chunk_duration = round(cropdetect_chunk_duration, 3)
    if cropdetect_chunk_duration <= 0:
        raise ValueError("Chunk duration must be a positive, nonzero number")
    # logger().debug("perform cropdetect with video codec %s on %s", video_codec, video_path)
    total_video_duration = utils.get_media_duration(video_path)

    # Optimization point: if the desired chunk duration runs into the next chunk, make the duration the total
    # length of the chunk. If we don't do this, then the chunks overlap and the same frames are analyzed more
    # than once. This is an expensive call, so we'll take what we can get.
    total_chunk_duration = round(total_video_duration / num_cropdetect_chunks)

    # If the total duration of each chunk is unreasonably small, we won't try to do anything. Because that
    # seems like the sensible thing to do.
    if total_chunk_duration < 0.1:
        raise ValueError("too many chunks for cropdetect. %d chunks, video is %.3f sec", num_cropdetect_chunks,
                         total_video_duration)

    cropdetect_chunk_duration = min(cropdetect_chunk_duration, total_chunk_duration)
    # logger().debug("cropdetect duration is %.3f sec with %d chunks", cropdetect_chunk_duration, num_cropdetect_chunks)
    chunk_starts = get_cropdetect_chunk_starts(video_path, num_cropdetect_chunks)
    crop_points = collections.Counter()
    thread_pool_size = multiprocessing.cpu_count()

    # logger().debug("thread pool size is %s", thread_pool_size)

    def aux(i, start):
        # logger().debug("cropdetect chunk %d/%d starting at %.3f sec", i, num_cropdetect_chunks, start)
        return cropdetect_chunk(video_path, start, cropdetect_chunk_duration, video_codec)

    with multiprocessing.pool.ThreadPool(thread_pool_size) as p:
        for points in p.map(lambda e: aux(*e), enumerate(chunk_starts, 1)):
            crop_points.update(points)
    return crop_points


def crop_video(video_path: str | Path, output_path: str | Path, num_cropdetect_chunks: int,
               cropdetect_chunk_duration: float, video_codec: str = 'libx265',
               output_format: Optional[str] = None) -> bool:
    """
    Crop the video.

    The output file is produced if the video is actually cropped. See return value.

    :param video_path:
    :param output_path:
    :param num_cropdetect_chunks:
    :param cropdetect_chunk_duration:
    :param video_codec:
    :return: True if the video is cropped, false if it is not cropped. A return value of false does not necessarily
             mean that an error occurred - it only means that the video was not cropped.
    """
    if video_codec is None or len(video_codec) == 0:
        video_codec = 'libx265'

    # logger().info("crop video at %s with codec %s", str(video_path), video_codec)
    crop_points: List[Tuple[Any, int]] = cropdetect_video(video_path, num_cropdetect_chunks,
                                                          cropdetect_chunk_duration, video_codec).most_common(1)
    if len(crop_points) == 0:
        print("No crop point found", file=sys.stderr)  # TODO: change
        return False

    (out_width, out_height, start_crop_x, start_crop_y) = crop_points[0][0]
    (current_width, current_height) = utils.get_video_dimensions(video_path)
    # logger().debug("video dimensions are %dx%d", current_width, current_height)
    # logger().debug("crop point is %d:%d:%d:%d", out_width, out_height, start_crop_x, start_crop_y)

    # If we're only shaving off a few pixels, it's not worth it to crop. Encoding is expensive.
    # Crop points are out_width:out_height:start_x:start_y
    new_width = current_width - out_width
    new_height = current_height - out_height
    if abs(current_width - new_width) < 10 and abs(current_height - new_height) < 10:
        # logger().warning(
        #     "not cropping because video is too close to cropped size. video size = %dx%d, cropped size = %dx%d",
        #     current_width, current_height, out_width, out_height)
        return False

    output_format = [] if output_format is None else ["-f", output_format]

    # We'll copy-encode all streams, except for video
    ff_args = ["-y", *utils.get_ffmpeg_common_options(),
               "-i", str(video_path),
               "-map", "0",
               "-c:s", "copy",
               "-c:a", "copy",
               "-c:d", "copy",
               "-c:v", video_codec,
               "-filter:v", f"crop={out_width}:{out_height}:{start_crop_x}:{start_crop_y}",
               *output_format,
               str(output_path)]
    # logger().debug("starting ffmpeg with args %s", str(ff_args))
    ff = subprocess.Popen(["ffmpeg", *ff_args])
    utils.wait_all(ff)
    if ff.returncode != 0:
        raise ValueError("crop error")
    return True


def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", required=True, help="Output file", metavar="FILE",
                        dest="output_file_path")
    parser.add_argument("-f", "--format", default=None, metavar="FORMAT", dest="output_video_format",
                        required=False, help="Output video format")
    parser.add_argument("-n", "--num-chunks", default=10, metavar="N", dest="num_chunks",
                        required=False, type=int, help="Number of chunks to use for cropdetect")
    parser.add_argument("-d", "--chunk-duration", default=20, metavar="SECS", dest="chunk_duration",
                        required=False, type=float, help="Duration of each chunk for cropdetect")
    parser.add_argument("-c", "--video-codec", default=None, metavar="CODEC", dest="video_codec",
                        required=False, type=str, help="Video codec to use when cropping")
    parser.add_argument("input_file", metavar="FILE", type=str, nargs='+', help="Input file",
                        required=True, dest="input_file_path")
    return parser


def main():
    args = make_arg_parser().parse_args()
    if len(args.output_file_path) == 0:
        print("No output file path specified", file=sys.stderr)
        return 1
    if args.num_chunks <= 0:
        print("Number of chunks must be at least 1", file=sys.stderr)
        return 1
    if not math.isfinite(args.chunk_duration) or args.chunk_duration <= 0:
        print("Chunk duration must be positive and nonzero", file=sys.stderr)
        return 1

    cropped = crop_video(args.input_file_path, args.output_file_path, args.num_chunks, args.chunk_duration,
                         args.video_codec, args.output_video_format)

    if cropped:
        print("Video cropped")
    else:
        print("Crop skipped, output file not created", file=sys.stderr)

    return 0


if __name__ == '__main__':
    exit(main())
