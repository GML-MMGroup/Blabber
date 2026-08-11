from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from blabber.compose import compose_episode
from blabber.podcast_tts import VolcenginePodcastTTS
from blabber.script_generator import (
    DEFAULT_TARGET_MINUTES,
    OpenNotebookScriptGenerator,
    ScriptGenerator,
    is_chinese,
)
from blabber.schema import Episode
from blabber.tts_engine import ByteDanceSeedAudioTTSEngine, EdgeTTSEngine
from blabber.voices import DEFAULT_CHARACTER_SET, voice_for

OUTPUT_ROOT = Path(__file__).parent / "output"
INTER_REQUEST_DELAY_SECONDS = 0.4


def _pick_generator() -> ScriptGenerator:
    """Build the required OpenNotebook-backed script generator."""
    base_url = os.getenv("OPEN_NOTEBOOK_URL", "").strip()
    if not base_url:
        raise RuntimeError(
            "OPEN_NOTEBOOK_URL 未配置；脚本生成必须使用 OpenNotebook，"
            "例如 OPEN_NOTEBOOK_URL=http://127.0.0.1:5055"
        )
    return OpenNotebookScriptGenerator(
        base_url=base_url,
        episode_profile=os.getenv("OPEN_NOTEBOOK_EPISODE_PROFILE", "default"),
        speaker_profile=os.getenv("OPEN_NOTEBOOK_SPEAKER_PROFILE", "default"),
        transformation_name=os.getenv(
            "OPEN_NOTEBOOK_TRANSFORMATION", "blabber_dialogue_script"
        ),
        model_id=os.getenv("OPEN_NOTEBOOK_MODEL_ID", "").strip() or None,
        request_timeout=float(os.getenv("OPEN_NOTEBOOK_TIMEOUT", "300")),
        chunk_minutes=float(os.getenv("OPEN_NOTEBOOK_CHUNK_MINUTES", "2")),
    )


async def _notify(callback, payload: dict) -> None:
    if callback is None:
        return
    result = callback(payload)
    if inspect.isawaitable(result):
        await result


async def run(
    prompt: str,
    target_minutes: float,
    on_progress=None,
    character_set: str = DEFAULT_CHARACTER_SET,
    custom_voices: dict[str, str] | None = None,
    speaker_ids: list[str] | tuple[str, str] | None = None,
    episode: Episode | None = None,
) -> Path:
    run_dir = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    clips_dir = run_dir / "clips"

    # PodcastTTS accepts either a topic prompt or an approved editable dialogue.
    podcast_app_id = os.getenv("VOLCENGINE_SPEECH_APP_ID", "").strip()
    podcast_access_key = os.getenv("VOLCENGINE_SPEECH_ACCESS_KEY", "").strip()
    if podcast_app_id and podcast_access_key:
        await _notify(on_progress, {
            "stage": "podcast",
            "topic": prompt,
            "total": 1,
            "completed": 0,
        })
        selected_speakers = tuple(speaker_ids or VolcenginePodcastTTS.DEFAULT_SPEAKERS)
        nlp_texts = (
            [
                {
                    "speaker": selected_speakers[0 if turn.speaker == "HostA" else 1],
                    "text": turn.text,
                }
                for turn in episode.turns
            ]
            if episode
            else None
        )
        result = await VolcenginePodcastTTS(
            podcast_app_id,
            podcast_access_key,
            timeout=float(os.getenv("BYTEDANCE_TTS_TIMEOUT", "300")),
        ).generate(
            None if episode else prompt,
            run_dir,
            target_minutes=None if episode else target_minutes,
            on_progress=on_progress,
            topic=episode.topic if episode else prompt,
            speakers=selected_speakers,
            nlp_texts=nlp_texts,
        )
        (run_dir / "podcast-result.json").write_text(
            json.dumps({
                "task_id": result.task_id,
                "provider_audio_url": result.provider_audio_url,
                "clips": result.clips,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        await _notify(on_progress, {
            "stage": "complete",
            "topic": result.episode.topic,
            "total": len(result.episode.turns),
            "completed": len(result.episode.turns),
            "skipped": 0,
            "episode": asdict(result.episode),
            "final_path": str(result.final_path),
            "script_path": str(result.script_path),
            "provider_audio_url": result.provider_audio_url,
        })
        return result.final_path

    episode = episode or _pick_generator().generate(prompt, target_minutes)
    chinese = is_chinese(prompt)

    script_path = run_dir / "script.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        json.dumps(asdict(episode), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    await _notify(on_progress, {
        "stage": "script",
        "topic": episode.topic,
        "total": len(episode.turns),
        "completed": 0,
        "script_path": str(script_path),
    })

    byte_tts_key = os.getenv("BYTEDANCE_TTS_API_KEY", "").strip()
    tts = (
        ByteDanceSeedAudioTTSEngine(
            byte_tts_key,
            timeout=float(os.getenv("BYTEDANCE_TTS_TIMEOUT", "300")),
        )
        if byte_tts_key
        else EdgeTTSEngine()
    )
    clip_paths = []
    skipped = []
    for i, turn in enumerate(episode.turns):
        clip_path = clips_dir / f"{i:02d}_{turn.speaker}.mp3"
        voice = voice_for(
            turn.speaker,
            chinese=chinese,
            character_set=character_set,
            custom_voices=custom_voices,
        )
        try:
            await tts.synthesize(turn.text, voice, clip_path)
            clip_paths.append(clip_path)
            print(f"  [{i + 1}/{len(episode.turns)}] {turn.speaker}: {turn.text}")
        except Exception as e:
            skipped.append(i)
            print(f"  [{i + 1}/{len(episode.turns)}] 跳过（合成持续失败）：{turn.speaker}: {turn.text} ({e})")
        await _notify(on_progress, {
            "stage": "tts",
            "topic": episode.topic,
            "total": len(episode.turns),
            "completed": i + 1,
            "speaker": turn.speaker,
            "text": turn.text,
            "skipped": len(skipped),
        })
        await asyncio.sleep(INTER_REQUEST_DELAY_SECONDS)

    if skipped:
        print(f"\n注意：有 {len(skipped)} 句因反复合成失败被跳过，最终音频里会少这几句。")

    final_path = compose_episode(clip_paths, run_dir / "final.mp3")
    await _notify(on_progress, {
        "stage": "complete",
        "topic": episode.topic,
        "total": len(episode.turns),
        "completed": len(episode.turns),
        "skipped": len(skipped),
        "final_path": str(final_path),
        "script_path": str(script_path),
    })
    return final_path


def main() -> None:
    if len(sys.argv) < 2:
        print('用法: python main.py "做一期关于咖啡文化的播客" [目标分钟数，默认 35]')
        sys.exit(1)

    prompt = sys.argv[1]
    target_minutes = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET_MINUTES
    print(f"生成中: {prompt}（目标时长 ~{target_minutes:.0f} 分钟，句数较多，合成会花几分钟）")
    final_path = asyncio.run(run(prompt, target_minutes))
    print(f"\n完成！最终音频: {final_path}")


if __name__ == "__main__":
    main()
