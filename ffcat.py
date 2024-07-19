#!/usr/bin/env python3

import sys
import os
import argparse
import tempfile
from pathlib import Path
import subprocess
import utils


def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", required=True, help="Output file", metavar="FILE",
                        dest="output_file_path")
    parser.add_argument("-f", "--format", default=None, metavar="FORMAT", dest="output_video_format",
                        required=False, help="Output video format")
    parser.add_argument("input_files", metavar="FILES", type=str, nargs='+', help="Input files")
    return parser


def main() -> int:
    args = make_arg_parser().parse_args()
    if len(args.output_file_path) == 0:
        print("No output file path specified", file=sys.stderr)
        return 1

    list_file = None

    try:
        (fd, list_file) = tempfile.mkstemp(prefix="ffcat_list")
        os.close(fd)
        lines = "\n".join(f"file '{in_file}'" for in_file in args.input_files)
        with open(list_file, "w") as f:
            f.write(lines)
        ff_args = ["ffmpeg", "-safe", "0", "-f", "concat", "-i", list_file, "-c", "copy"]
        if args.output_video_format is not None:
            ff_args.extend(["-f", args.output_video_format])
        ff_args.extend(["-o", args.output_file_path])
        ff = subprocess.Popen(ff_args)
        try:
            ff.wait()
        except KeyboardInterrupt:
            ff.terminate()
            ff.wait()
            return 1
    finally:
        utils.fs_delete(list_file)
    return 0


if __name__ == "__main__":
    exit(main())
