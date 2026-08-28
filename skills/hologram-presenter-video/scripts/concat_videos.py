#!/usr/bin/env python3
"""Hard-cut storyboard clips into one MP4, normalizing only when required."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def fail(message: str) -> "NoReturn":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def relative_path(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        fail(f"{label} must be a relative path: {value}")
    return path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def probe(path: Path) -> dict:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,sample_rate,channels",
            "-of",
            "json",
            os.fspath(path),
        ]
    )
    if result.returncode != 0:
        fail(f"ffprobe could not read {path}: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"ffprobe returned invalid JSON for {path}: {exc}")
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video:
        fail(f"clip has no video stream: {path}")
    return {"video": video, "audio": audio}


def signature(info: dict) -> tuple:
    video = info["video"]
    audio = info["audio"] or {}
    return (
        video.get("codec_name"),
        video.get("width"),
        video.get("height"),
        video.get("pix_fmt"),
        video.get("r_frame_rate"),
        audio.get("codec_name"),
        audio.get("sample_rate"),
        audio.get("channels"),
    )


def write_concat_list(path: Path, clips: list[Path]) -> None:
    lines = []
    for clip in clips:
        escaped = os.fspath(clip.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_copy(clips: list[Path], output: Path, work: Path) -> bool:
    concat_list = work / "concat.txt"
    write_concat_list(concat_list, clips)
    candidate = work / "copy.mp4"
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            os.fspath(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            os.fspath(candidate),
        ]
    )
    if result.returncode != 0:
        return False
    probe(candidate)
    candidate.replace(output)
    return True


def normalize_clip(source: Path, target: Path, width: int, height: int, has_audio: bool) -> None:
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    )
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", os.fspath(source)]
    if has_audio:
        command.extend(["-map", "0:v:0", "-map", "0:a:0"])
    else:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
            ]
        )
    command.extend(
        [
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            os.fspath(target),
        ]
    )
    result = run(command)
    if result.returncode != 0:
        fail(f"failed to normalize {source}: {result.stderr.strip()}")
    probe(target)


def normalize_and_concat(clips: list[Path], infos: list[dict], output: Path, work: Path) -> None:
    first_video = infos[0]["video"]
    width = max(2, int(first_video.get("width") or 2))
    height = max(2, int(first_video.get("height") or 2))
    width -= width % 2
    height -= height % 2

    normalized = []
    for index, (clip, info) in enumerate(zip(clips, infos), start=1):
        target = work / f"normalized-{index:03d}.mp4"
        normalize_clip(clip, target, width, height, info["audio"] is not None)
        normalized.append(target)

    concat_list = work / "normalized-concat.txt"
    write_concat_list(concat_list, normalized)
    candidate = work / "normalized-final.mp4"
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            os.fspath(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            os.fspath(candidate),
        ]
    )
    if result.returncode != 0:
        fail(f"failed to concatenate normalized clips: {result.stderr.strip()}")
    probe(candidate)
    candidate.replace(output)


def load_ids(storyboard: Path) -> list[str]:
    try:
        payload = json.loads(storyboard.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"storyboard does not exist: {storyboard}")
    except json.JSONDecodeError as exc:
        fail(f"storyboard is invalid JSON: {exc}")
    if not isinstance(payload, list) or not payload:
        fail("storyboard must be a non-empty top-level array")
    ids = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            fail(f"storyboard item {index} has no valid string id")
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        fail("storyboard ids must be unique")
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--clips-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        fail("ffmpeg and ffprobe must both be available on PATH")

    storyboard = relative_path(args.storyboard, "--storyboard")
    clips_dir = relative_path(args.clips_dir, "--clips-dir")
    output = relative_path(args.output, "--output")
    if output.suffix.lower() != ".mp4":
        fail("--output must end in .mp4")
    output.parent.mkdir(parents=True, exist_ok=True)

    ids = load_ids(storyboard)
    clips = [clips_dir / f"{clip_id}.mp4" for clip_id in ids]
    missing = [os.fspath(path) for path in clips if not path.is_file()]
    if missing:
        fail("missing canonical clips: " + ", ".join(missing))

    infos = [probe(path) for path in clips]
    with tempfile.TemporaryDirectory(prefix=".hologram-concat-", dir=output.parent) as temporary:
        work = Path(temporary)
        compatible = len({signature(info) for info in infos}) == 1
        if not (compatible and concat_copy(clips, output, work)):
            normalize_and_concat(clips, infos, output, work)

    probe(output)
    print(os.fspath(output))


if __name__ == "__main__":
    main()
