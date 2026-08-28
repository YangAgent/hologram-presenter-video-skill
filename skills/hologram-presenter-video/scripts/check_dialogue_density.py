#!/usr/bin/env python3
"""检查整篇口播稿或 storyboard.json 中逐分镜台词的密度。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import NoReturn


PREFERRED_MIN = 4.2
IDEAL_MIN = 4.6
IDEAL_MAX = 5.0
PREFERRED_MAX = 5.2
HARD_MAX = 5.8
TARGET_DENSITY = 5.0
TOTAL_DURATION_TOLERANCE = 0.10


def fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_relative(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        fail(f"{label} 必须是相对路径：{value}")
    return path


def load_storyboard(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"分镜文件不存在：{path}")
    except json.JSONDecodeError as exc:
        fail(f"分镜文件不是有效 JSON：{exc}")
    if not isinstance(payload, list) or not payload:
        fail("storyboard.json 必须是非空顶层数组")
    return payload


def load_script(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"口播稿不存在：{path}")
    if not text.strip():
        fail("口播稿不能为空")
    return text


def is_cjk(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2EBEF
        or 0x30000 <= codepoint <= 0x323AF
    )


def count_units(text: str) -> int:
    """逐字符扫描，不依赖正则或 H3 提示词标签。"""
    units = 0
    group: str | None = None
    for character in text:
        if is_cjk(character):
            units += 1
            group = None
        elif character.isascii() and character.isalpha():
            if group != "latin":
                units += 1
            group = "latin"
        elif character.isdigit():
            if group != "number":
                units += 1
            group = "number"
        else:
            group = None
    return units


def inspect_item(item: dict, index: int) -> dict:
    if not isinstance(item, dict):
        fail(f"第 {index + 1} 个分镜必须是 JSON 对象")

    segment_id = item.get("id")
    duration = item.get("duration")
    dialogue = item.get("dialogue")
    prompt_value = item.get("prompt_path")

    if not isinstance(segment_id, str) or not segment_id:
        fail(f"第 {index + 1} 个分镜缺少有效 id")
    if not isinstance(duration, int) or isinstance(duration, bool) or not 8 <= duration <= 15:
        fail(f"分镜 {segment_id} 的 duration 必须是 8–15 的整数")
    if not isinstance(dialogue, str) or not dialogue.strip():
        fail(f"分镜 {segment_id} 缺少有效 dialogue")
    if not isinstance(prompt_value, str) or not prompt_value:
        fail(f"分镜 {segment_id} 缺少有效 prompt_path")

    require_relative(prompt_value, f"分镜 {segment_id} 的 prompt_path")
    units = count_units(dialogue)
    density = units / duration
    if density > HARD_MAX:
        status = "FAIL"
    elif density > PREFERRED_MAX:
        status = "WARNING"
    else:
        status = "OK"

    recommended = max(8, math.ceil(units / TARGET_DENSITY))
    recommendation = str(recommended) if recommended <= 15 else "拆分或缩短"
    return {
        "id": segment_id,
        "duration": duration,
        "units": units,
        "density": density,
        "status": status,
        "recommended": recommendation,
    }


def inspect_script(text: str, target_duration: int) -> dict:
    units = count_units(text)
    density = units / target_duration
    estimated_duration = units / TARGET_DENSITY

    if density > HARD_MAX:
        status = "FAIL"
    elif density > PREFERRED_MAX:
        status = "TOO_DENSE"
    elif density < PREFERRED_MIN:
        status = "TOO_SHORT"
    else:
        status = "OK"

    return {
        "target_duration": target_duration,
        "units": units,
        "density": density,
        "estimated_duration": estimated_duration,
        "status": status,
        "ideal_min": math.ceil(target_duration * IDEAL_MIN),
        "ideal_max": math.floor(target_duration * IDEAL_MAX),
        "allowed_min": math.ceil(target_duration * PREFERRED_MIN),
        "allowed_max": math.floor(target_duration * PREFERRED_MAX),
        "hard_max": math.floor(target_duration * HARD_MAX),
    }


def check_target_duration(value: int | None, required: bool) -> int | None:
    if value is None:
        if required:
            fail("使用 --script 时必须提供 --target-duration")
        return None
    if isinstance(value, bool) or value < 8:
        fail("--target-duration 必须是至少 8 秒的整数")
    return value


def run_script_check(script_value: str, target_value: int | None) -> None:
    script_path = require_relative(script_value, "--script")
    target_duration = check_target_duration(target_value, required=True)
    assert target_duration is not None
    result = inspect_script(load_script(script_path), target_duration)

    print("target_duration\tunits\tdensity\testimated_duration\tstatus")
    print(
        f"{result['target_duration']}\t{result['units']}\t{result['density']:.2f}\t"
        f"{result['estimated_duration']:.1f}\t{result['status']}"
    )
    print(
        "ideal_units="
        f"{result['ideal_min']}-{result['ideal_max']}\t"
        f"allowed_units={result['allowed_min']}-{result['allowed_max']}\t"
        f"hard_max_units={result['hard_max']}"
    )

    if result["status"] != "OK":
        if result["status"] == "TOO_SHORT":
            print("口播稿相对目标时长过短，需要扩写或确认慢节奏设计。", file=sys.stderr)
        elif result["status"] == "TOO_DENSE":
            print("口播稿超过 Gate1 建议上限，需要精简。", file=sys.stderr)
        else:
            print("口播稿超过硬上限，必须重新改写。", file=sys.stderr)
        raise SystemExit(1)


def run_storyboard_check(storyboard_value: str, target_value: int | None) -> None:
    storyboard_path = require_relative(storyboard_value, "--storyboard")
    target_duration = check_target_duration(target_value, required=False)
    items = load_storyboard(storyboard_path)
    results = [inspect_item(item, index) for index, item in enumerate(items)]

    print("id\tduration\tunits\tdensity\tstatus\trecommended_duration")
    for result in results:
        print(
            f"{result['id']}\t{result['duration']}\t{result['units']}\t"
            f"{result['density']:.2f}\t{result['status']}\t{result['recommended']}"
        )

    total_mismatch = False
    if target_duration is not None:
        planned_duration = sum(result["duration"] for result in results)
        deviation = abs(planned_duration - target_duration) / target_duration
        total_mismatch = deviation > TOTAL_DURATION_TOLERANCE
        total_status = "FAIL" if total_mismatch else "OK"
        print(
            f"planned_duration={planned_duration}\t"
            f"target_duration={target_duration}\t"
            f"deviation={deviation:.1%}\tstatus={total_status}"
        )

    failures = [result["id"] for result in results if result["status"] == "FAIL"]
    warnings = [result["id"] for result in results if result["status"] == "WARNING"]
    if warnings:
        print("需要人工复核的警戒分镜：" + ", ".join(warnings), file=sys.stderr)
    if total_mismatch:
        print("分镜计划时长总和与目标时长的误差超过 10%。", file=sys.stderr)
    if failures:
        print("超过台词密度硬上限的分镜：" + ", ".join(failures), file=sys.stderr)
    if failures or total_mismatch:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--script", help="相对于当前目录的口播稿路径")
    source.add_argument("--storyboard", help="相对于当前目录的 storyboard.json 路径")
    parser.add_argument("--target-duration", type=int, help="用户要求的目标时长，单位为秒")
    args = parser.parse_args()

    if args.script:
        run_script_check(args.script, args.target_duration)
    else:
        run_storyboard_check(args.storyboard, args.target_duration)


if __name__ == "__main__":
    main()
