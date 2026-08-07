from __future__ import annotations

import json
import os
import re
import subprocess

MAX_IMAGE_DATA_URL_LENGTH = 8 * 1024 * 1024


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise RuntimeError("视觉模型没有返回可解析的 JSON")
        return json.loads(match.group(0))


def analyze_character_voice(image_data_url: str, speaker: str) -> dict:
    api_url = os.getenv(
        "VISION_API_URL", "https://linkapi.ai/v1/chat/completions"
    ).strip()
    api_key = os.getenv("VISION_API_KEY", "").strip()
    model = os.getenv("VISION_MODEL_ID", "").strip()
    if not api_key or not model:
        raise RuntimeError("未配置 VISION_API_KEY 或 VISION_MODEL_ID")
    if not image_data_url.startswith("data:image/"):
        raise ValueError("仅支持图片 Data URL")
    if len(image_data_url) > MAX_IMAGE_DATA_URL_LENGTH:
        raise ValueError("图片过大，请上传 6MB 以内的图片")
    if speaker not in {"HostA", "HostB"}:
        raise ValueError("speaker 必须是 HostA 或 HostB")

    host_hint = "男主持" if speaker == "HostA" else "女主持"
    instruction = (
        f"你是播客配音导演。请根据图片的视觉风格、表情、服装和整体气质，"
        f"为{host_hint}设计匹配的中文 TTS 声线。不要识别人物身份，也不要推断种族、"
        "健康、宗教等敏感属性。只输出 JSON，不要 Markdown："
        '{"label":"8字以内声线名称","summary":"20字以内形象气质概括",'
        '"voice_prompt":"60至100字，包含年龄感、普通话、音色、情绪、语速、表达方式；'
        '不要包含要朗读的台词"}'
    )
    payload = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }],
        "temperature": 0.3,
    }).encode("utf-8")
    completed = subprocess.run(
        [
            "curl",
            "-sS",
            "--fail-with-body",
            "--max-time",
            "120",
            api_url,
            "-H",
            f"Authorization: Bearer {api_key}",
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            "@-",
        ],
        input=payload,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace")[:500]
        body_detail = completed.stdout.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"视觉模型请求失败：{' '.join(part for part in (detail, body_detail) if part)}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("视觉模型返回的内容不是 JSON") from error

    try:
        content = result["choices"][0]["message"]["content"]
        analyzed = _extract_json(content)
        label = str(analyzed["label"]).strip()[:20]
        summary = str(analyzed["summary"]).strip()[:80]
        voice_prompt = str(analyzed["voice_prompt"]).strip()[:300]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"视觉模型返回格式错误：{result}") from error
    if not label or not voice_prompt:
        raise RuntimeError("视觉模型返回的声线信息为空")
    return {
        "speaker": speaker,
        "label": label,
        "summary": summary,
        "voice_prompt": voice_prompt,
    }
