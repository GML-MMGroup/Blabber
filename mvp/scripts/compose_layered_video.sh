#!/usr/bin/env bash
#
# 使用 FFmpeg 按以下顺序合成播客视频：
#
#   背景图片
#      ↓
#   男角色 ProRes 4444 Alpha 动画
#      ↓
#   女角色 ProRes 4444 Alpha 动画
#      ↓
#   桌面、麦克风和盆栽透明前景
#
# 默认输出：
#   mvp/output/ffmpeg-layered/cartoon-podcast-new-foreground.mp4
#
# 用法：
#   ./mvp/scripts/compose_layered_video.sh
#
# 也可以依次传入 5 个自定义路径：
#   ./mvp/scripts/compose_layered_video.sh \
#     background.png \
#     male.mov \
#     female.mov \
#     foreground.png \
#     output.mp4

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 输入素材。命令行参数为空时使用项目中的默认素材。
BACKGROUND="${1:-${PROJECT_ROOT}/assets/background/background.png}"
MALE_ACTION="${2:-${PROJECT_ROOT}/assets/action/cartoon-dialogue-male-alpha-prores4444.mov}"
FEMALE_ACTION="${3:-${PROJECT_ROOT}/assets/action/cartoon-dialogue-female-alpha-prores4444.mov}"
FOREGROUND="${4:-${PROJECT_ROOT}/assets/background/scene2-foreground-alpha-clean-1920x1080_副本.png}"
OUTPUT="${5:-${PROJECT_ROOT}/mvp/output/ffmpeg-layered/cartoon-podcast-new-foreground.mp4}"

# 最终画布和时间参数。
CANVAS_WIDTH=1920
CANVAS_HEIGHT=1080
FPS=24

# 两个人物素材使用相同尺寸，确保视角和比例一致。
ACTOR_SIZE_MALE=735
ACTOR_SIZE_FEMALE=675

# overlay 坐标是缩放后人物方形画布左上角的位置。
MALE_X=184
MALE_Y=195
FEMALE_X=900
FEMALE_Y=195

# 两条动作素材各有 121 帧；121 ÷ 24 ≈ 5.04 秒。
OUTPUT_FRAMES=121

# H.264 输出质量。CRF 越低质量越高、文件越大。
CRF=18
PRESET="slow"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "错误：找不到 ffmpeg，请先安装 FFmpeg。" >&2
  exit 1
fi

# 在开始编码前检查所有输入，避免 FFmpeg 运行后才发现路径错误。
for input_path in \
  "${BACKGROUND}" \
  "${MALE_ACTION}" \
  "${FEMALE_ACTION}" \
  "${FOREGROUND}"
do
  if [[ ! -f "${input_path}" ]]; then
    echo "错误：素材不存在：${input_path}" >&2
    exit 1
  fi
done

mkdir -p "$(dirname "${OUTPUT}")"

echo "开始合成："
echo "  背景：${BACKGROUND}"
echo "  男角色：${MALE_ACTION}"
echo "  女角色：${FEMALE_ACTION}"
echo "  前景：${FOREGROUND}"
echo "  输出：${OUTPUT}"

# 使用数组保存参数，路径中包含空格或中文时不会被错误拆分。
ffmpeg_args=(
  -y

  # 静态背景循环输出，并从输入阶段就统一为 24 FPS。
  -loop 1
  -framerate "${FPS}"
  -i "${BACKGROUND}"

  # 两条 MOV 已包含 ProRes 4444 Alpha，FFmpeg 会自动识别透明通道。
  -i "${MALE_ACTION}"
  -i "${FEMALE_ACTION}"

  # 透明前景同样循环，持续覆盖完整视频时长。
  -loop 1
  -framerate "${FPS}"
  -i "${FOREGROUND}"

  -filter_complex "
    [0:v]
      scale=${CANVAS_WIDTH}:${CANVAS_HEIGHT},
      format=rgba
    [background];

    [1:v]
      scale=${ACTOR_SIZE_MALE}:${ACTOR_SIZE_MALE},
      format=rgba
    [male];

    [2:v]
      scale=${ACTOR_SIZE_FEMALE}:${ACTOR_SIZE_FEMALE},
      format=rgba
    [female];

    [3:v]
      scale=${CANVAS_WIDTH}:${CANVAS_HEIGHT},
      format=rgba
    [foreground];

    [background][male]
      overlay=x=${MALE_X}:y=${MALE_Y}:format=auto
    [with_male];

    [with_male][female]
      overlay=x=${FEMALE_X}:y=${FEMALE_Y}:format=auto
    [with_actors];

    [with_actors][foreground]
      overlay=x=0:y=0:format=auto,
      format=yuv420p
    [final]
  "

  # 只输出滤镜图中的最终画面，不保留输入素材中的其他流。
  -map "[final]"

  # 固定输出帧数和帧率，使两个人物保持相同时间基准。
  -frames:v "${OUTPUT_FRAMES}"
  -r "${FPS}"

  # 当前动作素材不含节目音轨，因此输出无声视频。
  -an

  # H.264 + yuv420p 具有较好的浏览器和播放器兼容性。
  -c:v libx264
  -preset "${PRESET}"
  -crf "${CRF}"

  # 将 MP4 索引放到文件开头，便于网页边下载边播放。
  -movflags +faststart
  "${OUTPUT}"
)

ffmpeg "${ffmpeg_args[@]}"

echo "合成完成：${OUTPUT}"
