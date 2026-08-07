# BYTEDANCE_TTS_API_KEY="你的密钥"
# OPEN_NOTEBOOK_URL="http://127.0.0.1:5055" \
# OPEN_NOTEBOOK_TRANSFORMATION="blabber_dialogue_script" \
# OPEN_NOTEBOOK_MODEL_ID="model:bjxo8xen31d7o6ylwwxq" \
# OPEN_NOTEBOOK_TIMEOUT="300" \
# OPEN_NOTEBOOK_CHUNK_MINUTES="2" \

import asyncio
from main import run

voices = {
    "HostA": "拟人狗狗声线，普通话标准，声音阳光温暖、活泼热情，略带憨萌和自然笑意，语速稍快，吐字清楚，像充满好奇心的喜剧播客主持人",
    "HostB": "拟人鸭子声线，普通话标准，声音明快俏皮、机灵有趣，音调略高但不尖锐，带轻微吐槽感和丰富表情，节奏轻快，吐字清楚"
    }

path = asyncio.run(run(
    prompt="生成一期由活泼狗狗阿汪和机灵鸭子嘎嘎主持的中文趣味播客，主题是：AI能不能替我们想点子？对话轻松幽默、有来有回",
    target_minutes=2,
    custom_voices=voices
))

print(f"生成完成：{path}")
