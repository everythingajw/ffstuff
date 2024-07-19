import itertools
import math
import shutil
from pathlib import Path
import subprocess
import re
from typing import Tuple, Optional, List


def flatten(xs) -> list:
    return list(itertools.chain.from_iterable(xs))


def wait_all(*subprocesses) -> None:
    try:
        for sub in subprocesses:
            sub.wait()
    except KeyboardInterrupt:
        # First, immediately terminate all subprocesses.
        for sub in subprocesses:
            sub.terminate()
        # Now wait for everything
        for sub in subprocesses:
            sub.wait()
        # Propagate error
        # We don't want to really explicitly handle the exception here - we just want to "forward" it
        # to the child process.
        raise


def get_media_duration(media_path: str | Path) -> float:
    lines = subprocess.check_output(["ffmpeg", "-hide_banner", "-xerror", "-loglevel", "quiet",
                                     "-stats_period", "0.01",
                                     "-i", str(media_path), "-c", "copy", "-f", "null", "-"],
                                    stderr=subprocess.STDOUT).decode().splitlines()
    # TODO: Should a more robust time regex be used here?
    timestamps = sorted(flatten([re.findall(r"(?<=time=)\S+", s) for s in lines]))
    if len(timestamps) == 0:
        raise ValueError("no video duration found")
    raw = timestamps[-1]
    if re.fullmatch(r"^\d+:\d+:\d+.\d+$", raw) is None:
        raise ValueError(f"video duration does not match regex: {raw!r}")
    hours, minutes, seconds = tuple(map(float, raw.split(":")))
    return (hours * 60 * 60) + (minutes * 60) + seconds


def get_video_dimensions(video_path: str | Path) -> Tuple[int, int]:
    dims = subprocess.check_output(["ffprobe", "-hide_banner", "-v", "error", "-select_streams", "v",
                                    "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
                                    str(video_path)], stderr=subprocess.STDOUT).decode().strip().split('x')
    # TODO: handle nonzero exit code
    if len(dims) != 2:
        raise ValueError(f"Dimensions did not split into two on x: dimensions were {dims}")
    # width, height
    return int(dims[0]), int(dims[1])


def fs_delete(*paths) -> None:
    for path in paths:
        if path is None:
            continue
        path = Path(str(path))
        if path.is_dir():
            shutil.rmtree(str(path), ignore_errors=True)
        else:
            path.unlink()


def ffmpeg_get_hwaccel_decode_methods() -> List[str]:
    hwaccels = subprocess.check_output("ffmpeg -hide_banner -loglevel quiet -hwaccels".split(),
                                       stderr=subprocess.DEVNULL).decode().strip().splitlines()[1:]
    return [s.strip() for s in hwaccels if len(s.strip()) > 0]


def ffmpeg_has_cuda_decode():
    return 'cuda' in ffmpeg_get_hwaccel_decode_methods()


def get_ffmpeg_common_options(stats_period: float = 0.25, log_level: str = None, show_stats: bool = True) -> List[str]:
    stats_period = round(stats_period, 3)
    if not math.isfinite(stats_period) or stats_period < 0.001:
        raise ValueError(f"invalid stats period {stats_period}, must be at least 0.001")
    if log_level is None:
        log_level = "quiet"
    hwaccel_decode = "-hwaccel cuda".split() if ffmpeg_has_cuda_decode() else []
    stats = ["-stats"] if show_stats else []
    return [str(x) for x in ["-hide_banner", "-xerror",
                             "-loglevel", log_level,
                             *stats, "-stats_period", f"{stats_period:.3f}",
                             "-err_detect", "explode",
                             *hwaccel_decode]]
