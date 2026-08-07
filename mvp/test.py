from __future__ import annotations

import argparse
from pathlib import Path

from blabber.seedance_animator import (
    AlphaConfig,
    DEFAULT_PROMPT,
    convert_to_alpha_assets,
    generate_character_motion,
)

MVP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MVP_ROOT.parent
CHARACTER_ROOT = PROJECT_ROOT / "assets" / "character"
ACTION_ROOT = PROJECT_ROOT / "assets" / "action"


def available_characters() -> tuple[str, ...]:
    """Return character IDs derived from assets/character/<character-id>.png."""
    return tuple(
        path.stem
        for path in sorted(CHARACTER_ROOT.glob("*.png"))
        if path.is_file()
    )


STANDBY_PROMPT = """
【主体与参考】
以@图片1中的单个人物为唯一主体，严格保持身份、脸型、五官、发型、服装、材质和画风一致。首尾姿态与参考图片尽量一致。

【姿态与构图】
人物正面坐姿，面向镜头，腰部以上完整入镜。头顶、头发、双肩、双臂、手肘和双手均不得被画面边缘截断；人物四周保留至少 12% 安全留白，人物位置和尺寸保持不变。

【5 秒待机动作】
0–1 秒：自然坐定，嘴巴闭合。
1–14 秒：保持闭嘴，轻微呼吸，自然眨眼一次，伴随幅度很小的点头和肩部起伏。
14–15 秒：回到与首帧接近的闭嘴坐姿。
不说话、不挥手、不起身、不转身。

【摄影机与光照】
固定正面机位，中景，镜头完全静止，不推拉、不平移、不摇镜、不变焦、不切镜。25 fps 观感。左前方柔和棚拍主光，约 4000K，曝光和清晰度稳定。

【绿幕母版】
这是色键素材。除人物外的所有像素必须是完全相同、100% 饱和的 #00FF00，RGB 尽量严格保持 (0,255,0)。背景不能变成灰色、灰绿色或自然场景，不能出现纹理、渐变、暗角、地面、家具、桌面、麦克风、阴影、反光、光斑或景深。人物不穿绿色且没有绿色配饰。人物轮廓清楚，头发丝和衣服边缘自然。

【禁止内容】
不新增人物或物体，不出现文字、字幕、Logo、水印或边框，不改变人物身份，不裁切人物。
""".strip()

COMBINED_PROMPT = """
【主体与参考】
以@图片1中的单个角色为唯一主体，严格保持身份、脸型、五官、发型、服装、材质和画风一致。

【姿态与构图】
角色正面坐姿，面向镜头，腰部以上完整入镜。头顶、头发、双肩、双臂、手肘和双手均不得被画面边缘截断；角色四周保留至少 12% 安全留白。角色在整个 15 秒内保持相同位置和尺寸。

【15 秒连续动作时间线】
0–1 秒（待机 1 秒）：角色嘴巴始终闭合，自然坐定，仅有轻微呼吸，不说话、不挥手。
1–6 秒（单独说话 5 秒）：角色像播客主持人一样自然连续说话，嘴唇做克制、清晰、连续的开合；期间自然眨眼一次，伴随轻微呼吸和非常小的点头。
6–8 秒（待机 2 秒）：立即停止说话，嘴巴自然闭合，只保留轻微呼吸和一次自然眨眼。
8–10 秒（单独说话 2 秒）：重新自然说话，嘴唇连续开合，身体和头部动作保持克制。
10–13 秒（待机 3 秒）：停止说话并保持闭嘴，只做轻微呼吸、自然眨眼和很小的点头。
13–14 秒（单独说话 1 秒）：进行一段短促但自然的说话动作，嘴唇清晰开合，不改变坐姿。
14–15 秒（待机 1 秒）：停止说话，嘴巴闭合，回到与第 0 秒接近的自然坐姿。
三段说话动作必须彼此独立；所有待机段都必须完全闭嘴，不能残留说话口型。全部阶段必须是同一个连续镜头，切换自然平滑，不切镜、不闪烁、不缩放、不跳帧，角色身份、位置、尺寸和构图不得变化。

【摄影机与光照】
固定正面机位，中景，镜头完全静止，不推拉、不平移、不摇镜、不变焦、不切镜。25 fps 观感。左前方柔和棚拍主光，约 4000K，曝光、色温和清晰度稳定。

【绿幕母版】
这是色键素材。除角色外的所有像素必须是完全相同、100% 饱和的 #00FF00，RGB 尽量严格保持 (0,255,0)。背景从首帧到末帧颜色恒定，不能变成灰色、灰绿色或自然场景，不能出现纹理、渐变、暗角、地面、家具、桌面、麦克风、阴影、反光、光斑或景深。角色不穿绿色且没有绿色配饰，角色轮廓、头发丝和衣服边缘自然。

【禁止内容】
不新增角色或物体，不出现文字、字幕、Logo、水印或边框，不改变角色身份，不裁切角色，不产生镜头运动、画面缩放、身体比例变化或复杂肢体动作。
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成或转换 Seedance 透明人物待机/说话动作",
    )
    character_choices = available_characters()
    if not character_choices:
        raise FileNotFoundError(f"没有找到角色参考图：{CHARACTER_ROOT}/*.png")
    parser.add_argument(
        "--character",
        choices=character_choices,
        default="funny-podcast-duck",
        help=(
            "角色 ID，对应 assets/character/<角色ID>.png；"
            "默认 funny-podcast-duck"
        ),
    )
    parser.add_argument(
        "--action",
        choices=("standby", "dialogue", "combined"),
        default="combined",
        help=(
            "动作类型：standby 使用 STANDBY_PROMPT，dialogue 使用 "
            "DEFAULT_PROMPT，combined 在15秒内生成5秒/2秒/1秒独立说话段"
        ),
    )
    parser.add_argument(
        "--reference-image", type=Path,
        help="覆盖角色参考图；未指定时使用 --character 对应的 PNG",
    )
    parser.add_argument(
        "--source", type=Path,
        help="跳过 Seedance，直接把已有绿幕 MP4 转成透明素材",
    )
    parser.add_argument(
        "--screen", choices=("green", "blue"), default="green",
        help="要求 Seedance 生成的幕布颜色，默认 green",
    )
    parser.add_argument(
        "--key-color",
        help="FFmpeg 色键颜色，例如 #00FF00 或 0x00FF00；默认跟随 --screen",
    )
    parser.add_argument(
        "--keyer", choices=("chromakey", "colorkey"), default="chromakey",
        help="色键算法；chromakey 使用 YUV，colorkey 使用 RGB",
    )
    parser.add_argument(
        "--similarity", type=float, default=0.18,
        help="颜色匹配容差，越大抠除越多，默认 0.18",
    )
    parser.add_argument(
        "--blend", type=float, default=0.075,
        help="Alpha 软边范围，默认 0.075",
    )
    parser.add_argument(
        "--despill", type=float, default=0.42,
        help="去除人物边缘幕布反色的强度，0 表示关闭，默认 0.42",
    )
    parser.add_argument(
        "--despill-expand", type=float, default=0.08,
        help="去反色区域扩张量，默认 0.08",
    )
    parser.add_argument(
        "--no-prepare-reference", action="store_true",
        help="不把参考人物图预先铺到指定纯色幕布上",
    )
    parser.add_argument(
        "--force-key", action="store_true",
        help="即使输入文件已有 Alpha 标记，也重新执行色键",
    )
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", help="覆盖默认动作提示词")
    prompt_group.add_argument(
        "--prompt-file", type=Path,
        help="从 UTF-8 文件读取动作提示词",
    )
    parser.add_argument("--model", help="覆盖默认 Seedance 模型 ID")
    parser.add_argument("--duration", type=int, default=15)
    parser.add_argument("--fps", type=int, choices=(25, 30, 60), default=25)
    parser.add_argument("--resolution", default="720p")
    parser.add_argument("--ratio", default="1:1")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    custom_prompt = args.prompt
    if args.prompt_file:
        custom_prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    action_prompts = {
        "standby": STANDBY_PROMPT,
        "dialogue": DEFAULT_PROMPT,
        "combined": COMBINED_PROMPT,
    }
    default_action_prompt = action_prompts[args.action]
    selected_prompt = custom_prompt or default_action_prompt
    selected_duration = 15 if args.action == "combined" else args.duration
    reference_image = (
        args.reference_image.resolve()
        if args.reference_image
        else CHARACTER_ROOT / f"{args.character}.png"
    )
    alpha_config = AlphaConfig(
        screen=args.screen,
        key_color=args.key_color,
        keyer=args.keyer,
        similarity=args.similarity,
        blend=args.blend,
        despill=args.despill,
        despill_expand=args.despill_expand,
        prepare_reference=not args.no_prepare_reference,
        force_key=args.force_key,
    )
    name = f"{args.character}-{args.action}-alpha-prores4444"
    character_action_root = ACTION_ROOT / args.character
    output_path = character_action_root / f"{name}.mp4"
    formats = ("png", "mp4")

    if args.source:
        outputs = convert_to_alpha_assets(
            args.source.resolve(),
            output_path,
            fps=args.fps,
            formats=formats,
            alpha_config=alpha_config,
        )
        result = outputs["mp4"]
    else:
        result = generate_character_motion(
            image_paths=[reference_image],
            output_path=output_path,
            prompt=selected_prompt,
            model=args.model,
            duration=selected_duration,
            resolution=args.resolution,
            ratio=args.ratio,
            fps=args.fps,
            output_formats=formats,
            alpha_config=alpha_config,
            timeout=args.timeout,
        )

    print(f"MP4 幕布母版：{output_path}")
    print(f"本次主输出：{result}")
    print(f"透明 PNG 序列：{character_action_root / f'{name}-png'}")
    print("注意：MP4 不含 Alpha；透明度保存在 PNG 序列中。")


if __name__ == "__main__":
    main()
