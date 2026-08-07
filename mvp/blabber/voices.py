from __future__ import annotations


VOICE_PROFILES = {
    "cartoon": {
        "HostA": (
            "青年男性，普通话标准，声音清朗温暖，带自然笑意和少年感；"
            "性格阳光外向、亲切有活力，语速稍快但吐字清楚，像朋友聊天般轻松"
        ),
        "HostB": (
            "青年女性，普通话标准，声音温暖明亮、柔和甜润但不过分稚嫩；"
            "性格亲切活泼，带自然笑意，节奏轻快，像充满好奇心的年轻播客主持人"
        ),
    },
    "professional": {
        "HostA": (
            "青年男性，普通话标准，声音干净有磁性，音色中低而不厚重；"
            "气质冷静从容、理性专业，吐字利落，语速适中，表达有思考感和可信度"
        ),
        "HostB": (
            "青年女性，普通话标准，声音清晰温润，音色知性优雅而自然；"
            "气质成熟从容、专业亲和，节奏稳定，表达细腻有条理，带轻微自然笑意"
        ),
    },
}

VOICE_PROFILES_EN = {
    "cartoon": {
        "HostA": "a bright, warm young male speaker, upbeat and approachable, with a clear conversational American accent",
        "HostB": "a warm, lively young female speaker with a gentle smile and a clear conversational American accent",
    },
    "professional": {
        "HostA": "a composed young male speaker with a clean medium-low voice, articulate and thoughtful, with a clear American accent",
        "HostB": "a poised young female speaker with a warm, polished voice, articulate and confident, with a clear American accent",
    },
}

DEFAULT_CHARACTER_SET = "cartoon"
CHARACTER_SETS = frozenset(VOICE_PROFILES)


def voice_for(
    speaker: str,
    chinese: bool = True,
    character_set: str = DEFAULT_CHARACTER_SET,
    custom_voices: dict[str, str] | None = None,
) -> str:
    if custom_voices and custom_voices.get(speaker):
        return custom_voices[speaker]
    profiles = VOICE_PROFILES if chinese else VOICE_PROFILES_EN
    selected = character_set if character_set in profiles else DEFAULT_CHARACTER_SET
    return profiles[selected][speaker]
