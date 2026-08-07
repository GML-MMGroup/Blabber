from __future__ import annotations


VOICE_PROFILES = {
    "cartoon": {
        "HostA": (
            "青年女性卡通角色，普通话标准，声音清脆明亮、机灵俏皮；"
            "语气自信活泼，带自然笑意，吐字清楚，像反应敏捷的年轻播客主持人"
        ),
        "HostB": (
            "青年男性卡通角色，普通话标准，声音阳光清朗、热情有活力；"
            "语气忠诚友善又略带顽皮，节奏轻快，像幽默亲切的年轻播客主持人"
        ),
    },
}

VOICE_PROFILES_EN = {
    "cartoon": {
        "HostA": "a bright, quick-witted young female cartoon duck host with a clear conversational American accent",
        "HostB": "an upbeat, friendly young male cartoon dog host with a clear conversational American accent",
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
