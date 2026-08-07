import asyncio
import sys
import time
from pathlib import Path

from blabber.video_compose import compose_episode_video


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 generate_video.py output/<run_dir时间戳目录>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"找不到目录: {run_dir}")
        sys.exit(1)

    print(f"生成视频中: {run_dir}（口型同步是 CPU 推理，逐句处理会比较慢）")
    start = time.monotonic()
    out_path = asyncio.run(compose_episode_video(run_dir))
    elapsed = time.monotonic() - start
    print(f"\n完成！耗时 {elapsed:.1f}s，最终视频: {out_path}")


if __name__ == "__main__":
    main()
