import itertools
import json
import re
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from math import ceil
from typing import Optional

from blabber.compose import PAUSE_MS
from blabber.schema import Episode, Turn

PAUSE_SECONDS = PAUSE_MS / 1000

# Rough conversational TTS speech rates, used only to estimate how many
# segments are needed to fill a target episode length. Chinese rate is
# measured empirically (edge-tts default rate); English is an approximation
# for a ~155 wpm conversational pace.
CHARS_PER_SEC_ZH = 4.6
WORDS_PER_SEC_EN = 2.6

DEFAULT_TARGET_MINUTES = 35.0

# Safety cap: stop cycling through the segment pool after this many segment
# uses, regardless of target_minutes, so a bad/huge target can't runaway.
MAX_SEGMENT_USES_MULTIPLIER = 4


class ScriptGenerator(ABC):
    @abstractmethod
    def generate(
        self, prompt: str, target_minutes: float = DEFAULT_TARGET_MINUTES, on_progress=None
    ) -> Episode:
        ...


def _extract_topic(prompt: str) -> str:
    """Strip common instruction phrasing to pull out the bare topic."""
    cleaned = prompt.strip().rstrip("。.!?")
    for pattern in (
        r"^(做一期|来一期|生成一期|录一期)?关于",
        r"^(make|create|do|generate)\s+a\s+podcast\s+about",
        r"^a\s+podcast\s+about",
    ):
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"(的播客|播客)$", "", cleaned).strip()
    return cleaned or prompt.strip()


def is_chinese(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text))


_ZH_INTRO = [
    ("HostA", "大家好，欢迎收听本期节目，今天我们要用比较长的篇幅，好好聊聊{topic}这个话题，希望能带大家从不同角度深入了解一下。"),
    ("HostB", "对，{topic}其实值得慢慢聊，我们今天准备了好几个不同的切入点，尽量让内容更丰富一些，大家可以慢慢听、慢慢琢磨。"),
]

_ZH_OUTRO = [
    ("HostA", "好了，今天关于{topic}就先聊到这里，感谢大家听到最后，希望这些内容能给你带来一些新的想法。"),
    ("HostB", "如果你对{topic}还有别的想法或者问题，也欢迎留言告诉我们，我们下期节目再见，拜拜！"),
]

_ZH_SEGMENTS = [
    [  # 起源背景
        ("HostA", "先从头说起吧，{topic}最早是怎么出现的，你了解过背后的故事吗？我一直挺好奇这种东西是怎么慢慢发展起来的。"),
        ("HostB", "了解一些，其实很多东西一开始都没那么起眼，是慢慢被更多人注意到，才变成现在这个样子的，中间也经历了不少变化。"),
        ("HostA", "对，很多流行的东西回头看，最开始都特别朴素，反而是后来的发展让它变得复杂起来，甚至连最初的人都没想到会走到今天这一步。"),
        ("HostB", "而且不同的人接触到它的契机也完全不一样，有人是因为工作需要，有人纯粹是生活里偶然碰上的，路径完全不同，但最后好像都殊途同归。"),
        ("HostA", "这也是我觉得挺有意思的地方，起点不同，但最后大家聊起来居然还挺有共鸣的，好像总能找到共同语言。"),
        ("HostB", "对，这种共鸣感其实挺难得的，也是我们今天想好好聊聊{topic}这个话题的原因之一，希望能把这份共鸣传递给更多人。"),
    ],
    [  # 流行原因
        ("HostA", "那我们聊聊现在为什么这么多人开始关注{topic}，你觉得背后的原因是什么？是突然火起来的，还是慢慢积累的？"),
        ("HostB", "我觉得跟大环境的变化有关系，大家的生活节奏和关注点这几年确实在变，很多以前不太被重视的东西开始被重新看见。"),
        ("HostA", "确实，以前可能没什么人会专门讨论这些，但现在好像变成了大家茶余饭后都会聊的东西，讨论的门槛也变低了。"),
        ("HostB", "而且社交媒体也放大了这种关注，一个小事情很容易就被更多人看到、讨论，进而形成一种连锁反应。"),
        ("HostA", "所以某种程度上，不是它突然变重要了，是我们看待它的方式变了，关注的角度也变得更多元了。"),
        ("HostB", "这个说法我很认同，视角变了，理解自然也会跟着变，这也是为什么同一件事，不同时间讨论起来感觉完全不一样。"),
    ],
    [  # 常见误解
        ("HostA", "接下来想聊聊，大家对{topic}是不是有一些常见的误解？我觉得这个挺值得拿出来说说的。"),
        ("HostB", "有的，很多人第一印象往往是比较片面的，容易只看到表面的东西，没有真正深入去了解过。"),
        ("HostA", "比如说呢？能不能举个具体点的例子，让大家更有画面感一点。"),
        ("HostB", "比如觉得这只是件很简单的事情，但真正深入了解之后，会发现里面门道其实挺多的，远比表面看起来复杂。"),
        ("HostA", "这种以偏概全确实挺常见的，很多时候大家只是没机会真正去了解全貌，就已经下了结论。"),
        ("HostB", "所以我觉得多聊聊、多分享，其实就是在慢慢消除这些误解，让更多人看到更完整的一面。"),
    ],
    [  # 个人经历
        ("HostA", "说到这儿，你自己有没有什么跟{topic}相关的经历，可以跟大家分享一下？我很好奇你的第一次接触是什么样的。"),
        ("HostB", "还真有，我记得有一次因为这件事，整个想法都被彻底改变了，之前的一些固有印象一下子就被打破了。"),
        ("HostA", "愿闻其详，具体是怎么回事，能不能详细说说当时的情况？"),
        ("HostB", "当时完全是抱着随便看看的心态接触的，结果发现比想象中有意思太多了，一下子就投入进去了。"),
        ("HostA", "这种反差感我特别能理解，很多时候真正接触之后才知道自己之前想得太简单了。"),
        ("HostB", "对，所以我现在也很愿意鼓励身边的人多去实际体验一下，而不是光听别人说就下判断。"),
    ],
    [  # 专业/行业视角
        ("HostA", "换个角度，如果从更专业一点的视角来看{topic}，会有什么不一样的理解？"),
        ("HostB", "从这个角度看，会发现背后其实有一整套逻辑和门槛，不是表面看起来那么简单，很多细节外行很难注意到。"),
        ("HostA", "确实，很多外行看热闹，但真正在这个领域里的人考虑的东西完全不是一个维度的。"),
        ("HostB", "而且这个领域这些年也在不断变化，从业者也要不停地学习和调整，才能跟得上节奏。"),
        ("HostA", "这么听下来，其实还挺不容易的，光是跟上变化就已经很花精力了。"),
        ("HostB", "是的，这也是我一直很尊重这个领域里认真做事的人的原因，背后的付出往往不为人知。"),
    ],
    [  # 数据/科学角度
        ("HostA", "如果我们看一些关于{topic}的数据或者研究，会不会有一些让人意外的发现？"),
        ("HostB", "会的，很多时候数据呈现出来的结果，跟大家凭直觉的判断其实不太一样，反差还挺大的。"),
        ("HostA", "能不能举个例子，让听众也感受一下这种反差？"),
        ("HostB", "比如大家普遍以为的一种情况，实际统计下来占比反而没那么高，反倒是另一种情况更常见一些。"),
        ("HostA", "这也提醒我们，很多时候不能只凭感觉下结论，还是要多看看实际的情况再说。"),
        ("HostB", "对，保持一点好奇心，愿意去查证，往往能发现很多意料之外的东西，挺有意思的。"),
    ],
    [  # 文化/地域差异
        ("HostA", "那从文化或者地域的角度来看{topic}，会不会存在挺大的差异？"),
        ("HostB", "差异其实挺明显的，不同地方的人对待这件事的态度和习惯都不太一样，有时候甚至完全相反。"),
        ("HostA", "这种差异是怎么形成的呢，跟历史或者生活方式有关系吗？"),
        ("HostB", "多多少少都有关系，环境和习惯塑造了大家不同的理解方式，很难一概而论。"),
        ("HostA", "所以了解这些差异，其实也是在了解不同的生活方式和价值观。"),
        ("HostB", "没错，这也是我觉得聊这类话题特别有意思的地方，能打开不少新的视角，挺开眼界的。"),
    ],
    [  # 争议话题
        ("HostA", "关于{topic}，这里边有没有什么比较有争议的地方，大家意见不太一致的？"),
        ("HostB", "肯定是有的，几乎每个被广泛讨论的话题，都会有支持和反对的不同声音，很难做到完全一致。"),
        ("HostA", "那你自己更倾向于哪一边，还是觉得两边都有道理？"),
        ("HostB", "我觉得两边都有各自的立场和理由，很难简单地说谁对谁错，需要具体情况具体看待。"),
        ("HostA", "这种复杂性其实也挺正常的，很多事情本来就不是非黑即白的。"),
        ("HostB", "对，保持开放的心态去看待不同的声音，我觉得比急着下结论要重要得多。"),
    ],
    [  # 冷知识/趣事
        ("HostA", "轻松一点，有没有什么跟{topic}相关的冷知识，可以分享给大家？"),
        ("HostB", "有一个我一直觉得挺有意思的小知识，很多人可能都没注意到，说出来大家肯定会觉得挺意外。"),
        ("HostA", "快说说，我很好奇，卖个关子也行，先给点提示。"),
        ("HostB", "其实背后还有一段挺意外的小故事，跟大家平时想的完全不太一样，听完可能会颠覆一点认知。"),
        ("HostA", "这个真的挺冷门的，我之前完全没听说过，算是又长知识了。"),
        ("HostB", "对吧，我第一次知道的时候也觉得挺意外的，特别适合当聊天时候的小谈资。"),
    ],
    [  # 日常生活影响
        ("HostA", "说回日常生活，{topic}其实对我们普通人有什么实际的影响吗？"),
        ("HostB", "影响还挺具体的，可能不知不觉就已经渗透到日常的一些选择里了，只是平时没太留意。"),
        ("HostA", "能不能具体说说，是哪些方面会受到影响，举个贴近生活的例子？"),
        ("HostB", "比如在做决定的时候，可能会不自觉地考虑到跟这个相关的一些因素，慢慢变成一种习惯。"),
        ("HostA", "这么一说，好像确实是这样，只是平时没有特别意识到而已。"),
        ("HostB", "对，很多影响都是潜移默化的，回头想想才会发现原来一直都在，只是没被察觉。"),
    ],
    [  # 未来趋势
        ("HostA", "那往后看，你觉得{topic}接下来会往什么方向发展？"),
        ("HostB", "我个人觉得会越来越受到重视，讨论的深度和广度都会继续增加，关注的人也会越来越多。"),
        ("HostA", "会不会出现一些现在还没预料到的新变化，让大家觉得意外？"),
        ("HostB", "很有可能，很多领域的发展往往都会带出一些意料之外的新方向，谁也说不准。"),
        ("HostA", "挺期待看看接下来会怎么发展的，感觉还有不少想象空间。"),
        ("HostB", "我也是，所以这也是值得大家持续关注的一个话题，说不定过阵子又有新说法。"),
    ],
    [  # 给听众的建议
        ("HostA", "接下来想问问，如果听众对{topic}感兴趣，你会给他们什么建议？"),
        ("HostB", "我会建议先别急着下判断，多花点时间实际去了解和体验一下，感受会更真实一些。"),
        ("HostA", "还有别的建议吗，比如从哪里开始比较合适？"),
        ("HostB", "保持开放的心态很重要，很多认识都是慢慢积累起来的，不用一次就求全求快。"),
        ("HostA", "这个建议我觉得挺实用的，也适用于很多其他话题，不只是{topic}。"),
        ("HostB", "希望大家都能从自己感兴趣的角度，找到属于自己理解{topic}的方式。"),
    ],
    [  # 经济/产业角度
        ("HostA", "我们再聊聊经济层面，{topic}背后其实也牵扯到不小的产业规模吧？"),
        ("HostB", "对，很多人可能没意识到，围绕这个话题其实已经形成了不小的产业链，涉及的环节也不少。"),
        ("HostA", "能具体说说都有哪些环节吗，听起来还挺庞大的。"),
        ("HostB", "从最上游到最后触达普通人，中间要经过好几道流程，每个环节都有各自的门道和讲究。"),
        ("HostA", "这么看，其实背后的商业逻辑还挺值得研究的，不只是表面看到的那么简单。"),
        ("HostB", "没错，很多我们习以为常的东西，背后其实都有一整套经济逻辑在支撑着。"),
    ],
    [  # 案例分享
        ("HostA", "最后再聊一个具体的案例吧，有没有什么跟{topic}相关、比较有代表性的例子？"),
        ("HostB", "有一个我印象特别深，当时的情况跟我们前面聊到的很多点都能对上，挺有代表性的。"),
        ("HostA", "具体是什么样的情况，能详细讲讲吗？"),
        ("HostB", "简单说就是从一个很小的契机开始，慢慢发展成后来大家都能看到的结果，过程挺曲折的。"),
        ("HostA", "这种案例听起来特别真实，比单纯讲道理更有说服力。"),
        ("HostB", "对，具体的例子总是更容易让人有共鸣，这也是我喜欢用案例来聊{topic}的原因。"),
    ],
]

_EN_INTRO = [
    ("HostA", "Hey everyone, welcome back to the show. Today we're doing a longer deep-dive episode, and we're going to unpack {topic} from a bunch of different angles, so settle in."),
    ("HostB", "Yeah, {topic} is honestly a topic that deserves more than a quick surface-level chat, so we've lined up several different threads to pull on today."),
]

_EN_OUTRO = [
    ("HostA", "Alright, that wraps up today's deep dive into {topic}. Thanks so much for sticking with us through the whole episode, we really appreciate it."),
    ("HostB", "If you've got thoughts or questions about {topic} after listening to all this, drop us a note, we'd love to hear it. See you next time, bye!"),
]

_EN_SEGMENTS = [
    [  # origins
        ("HostA", "Let's start from the beginning — how did {topic} even get started, do you know the backstory behind it? I've always been curious how these things take shape."),
        ("HostB", "A little, honestly a lot of things start out pretty small and unremarkable, and it's only over time that more people start paying attention and it grows into what we know now."),
        ("HostA", "Right, so many things that end up popular were actually really humble at the start, and it's the later developments that made them feel so much bigger and more complex."),
        ("HostB", "And the way different people first come across it varies a lot too — some through work, some just stumble into it in everyday life, totally different paths that somehow end up in the same place."),
        ("HostA", "That's what I find interesting, different starting points but somehow when people talk about it there's still a lot of common ground."),
        ("HostB", "Yeah, that shared understanding is actually pretty rare, and honestly it's part of why we wanted to dig into {topic} properly today."),
    ],
    [  # why it matters now
        ("HostA", "Let's talk about why so many people are paying attention to {topic} right now — do you think it just suddenly took off, or was it more gradual?"),
        ("HostB", "I think it's tied to bigger shifts in how people live day to day, our pace of life and what we pay attention to has genuinely changed over the past few years."),
        ("HostA", "Right, a few years ago barely anyone would bring this up casually, but now it's turned into something people chat about all the time, the barrier to talking about it has dropped."),
        ("HostB", "And social media amplifies it too, something small can get seen and discussed by way more people almost instantly, which kind of snowballs on itself."),
        ("HostA", "So in a way it's not that the thing itself suddenly became important, it's more that how we look at it has changed."),
        ("HostB", "Exactly, and once the perspective shifts, understanding naturally shifts along with it — that's why the same topic can feel totally different depending on when you're discussing it."),
    ],
    [  # misconceptions
        ("HostA", "Let's get into this — are there some common misconceptions people have about {topic}? I think this is worth unpacking a bit."),
        ("HostB", "Definitely, a lot of people's first impression tends to be pretty one-sided, because they haven't really taken the time to look into it properly."),
        ("HostA", "Can you give a concrete example, just so listeners have something to picture?"),
        ("HostB", "Sure, people often assume it's a really simple thing, but once you actually dig in you realize there's a lot more nuance than the surface suggests."),
        ("HostA", "That kind of oversimplification is really common, a lot of the time people just haven't had the chance to see the full picture before forming an opinion."),
        ("HostB", "So I think talking about it more openly is actually a way of slowly chipping away at those misconceptions, letting more people see the fuller story."),
    ],
    [  # personal story
        ("HostA", "So on that note, do you have any personal experience with {topic} you could share with everyone? I'm curious what your first real encounter with it was like."),
        ("HostB", "I actually do, there was one moment where my whole take on it completely flipped, some assumptions I'd been carrying around just got shattered."),
        ("HostA", "I want to hear more, walk us through what happened."),
        ("HostB", "I went in with a pretty casual, just-checking-it-out mindset, and it ended up being way more interesting than I expected, I got pulled in almost immediately."),
        ("HostA", "I really relate to that gap between expectation and reality, a lot of the time you only realize how oversimplified your first impression was once you actually experience it."),
        ("HostB", "Right, which is why I try to encourage people around me to actually go try things themselves instead of just going off what someone else told them."),
    ],
    [  # industry angle
        ("HostA", "Let's shift gears — if we look at {topic} from a more professional, industry-level angle, does the picture change much?"),
        ("HostB", "It does, from that angle you start noticing there's a whole system of logic and thresholds behind it that isn't obvious from the outside at all."),
        ("HostA", "Right, outsiders just see the highlights, but the people actually working in that space are thinking about it on a completely different level."),
        ("HostB", "And the field keeps shifting too, so people working in it have to keep learning and adjusting just to stay current."),
        ("HostA", "Hearing that, it actually sounds pretty demanding, just keeping pace with the changes takes real effort."),
        ("HostB", "Yeah, and that's exactly why I have a lot of respect for the people who take this seriously, most of that effort is invisible from the outside."),
    ],
    [  # data and research
        ("HostA", "If we look at some data or research around {topic}, are there any findings that would surprise people?"),
        ("HostB", "There are, a lot of the time what the data actually shows doesn't match what people assume based purely on gut instinct."),
        ("HostA", "Can you give an example, something that would really illustrate that gap for listeners?"),
        ("HostB", "Sure, something most people assume is the common case actually turns out to be a smaller share than expected, while a less obvious scenario is actually more typical."),
        ("HostA", "That's a good reminder not to jump to conclusions based purely on intuition, it's worth actually checking what the numbers say."),
        ("HostB", "Right, staying curious and being willing to verify things tends to turn up all kinds of surprises, it's honestly one of the fun parts."),
    ],
    [  # cultural differences
        ("HostA", "Looking at this from a cultural or regional angle, are there big differences in how {topic} is approached in different places?"),
        ("HostB", "There really are, people in different places have pretty different attitudes and habits around it, sometimes even opposite approaches."),
        ("HostA", "Where do you think those differences come from, is it tied to history or lifestyle?"),
        ("HostB", "It's a mix of both really, environment and daily habits shape how people understand it, it's hard to generalize across the board."),
        ("HostA", "So understanding those differences is really a way of understanding different lifestyles and values more broadly."),
        ("HostB", "Exactly, and that's part of why I find these kinds of conversations so interesting, it opens up a lot of new perspectives you wouldn't get otherwise."),
    ],
    [  # controversy
        ("HostA", "Are there any genuinely controversial aspects of {topic}, places where people just don't agree?"),
        ("HostB", "For sure, pretty much any topic that gets widely discussed ends up with people on both sides, it's rare for everyone to agree."),
        ("HostA", "Where do you personally land on it, or do you think both sides have a point?"),
        ("HostB", "Honestly I think both sides have legitimate reasoning behind their position, it's hard to just call one side right and the other wrong."),
        ("HostA", "That kind of complexity feels pretty normal actually, a lot of things just aren't as black and white as we'd like them to be."),
        ("HostB", "Right, staying open to different viewpoints matters a lot more than rushing to a conclusion, at least in my opinion."),
    ],
    [  # fun facts
        ("HostA", "Let's lighten it up a bit — any fun trivia related to {topic} you can share with everyone?"),
        ("HostB", "There's one I've always found really interesting, something most people probably haven't noticed before, it tends to catch people off guard."),
        ("HostA", "Go on, don't leave us hanging, give us a hint first if you want to build it up."),
        ("HostB", "There's actually a pretty surprising little story behind it, quite different from what most people assume, it might change how you think about it."),
        ("HostA", "That's genuinely obscure, I had never heard that before, learned something new today."),
        ("HostB", "Right? I remember being pretty surprised the first time I heard it too, it's a great bit of trivia to bring up in conversation."),
    ],
    [  # everyday impact
        ("HostA", "Bringing it back to everyday life, does {topic} actually have any real impact on regular people like us?"),
        ("HostB", "It does, in some pretty concrete ways actually, it's quietly worked its way into some of our everyday choices without us really noticing."),
        ("HostA", "Can you get specific, what kinds of decisions does it actually show up in?"),
        ("HostB", "For example, when making a decision, people might unconsciously factor in something related to this without realizing, it just becomes a habit over time."),
        ("HostA", "Now that you mention it, that does sound about right, I just never really stopped to notice it before."),
        ("HostB", "Right, a lot of these influences are pretty subtle, it's only when you stop and think about it that you realize it's been there all along."),
    ],
    [  # future trends
        ("HostA", "Looking ahead, where do you think {topic} is headed from here?"),
        ("HostB", "Personally I think it's only going to get more attention, both the depth and breadth of the conversation around it will keep growing."),
        ("HostA", "Do you think there could be some unexpected turns that catch everyone off guard?"),
        ("HostB", "Very possibly, a lot of fields end up taking directions nobody really predicted, it's honestly hard to say for sure."),
        ("HostA", "I'm genuinely curious to see how it develops, there still feels like a lot of room for surprises."),
        ("HostB", "Same here, which is exactly why it's worth keeping an eye on, there might be a whole new take on it before too long."),
    ],
    [  # advice for listeners
        ("HostA", "Last thing on this thread — if a listener is curious about {topic}, what advice would you give them?"),
        ("HostB", "I'd say don't rush to judgment, spend some real time actually exploring and experiencing it firsthand, it tends to feel a lot more genuine that way."),
        ("HostA", "Any other advice, maybe where's a good place to actually start?"),
        ("HostB", "Staying open-minded really matters, most understanding builds up gradually, you don't need to have it all figured out right away."),
        ("HostA", "That's genuinely useful advice, honestly it applies to a lot of other topics too, not just {topic}."),
        ("HostB", "Hope everyone finds their own way into understanding {topic}, starting from whatever angle actually interests them personally."),
    ],
    [  # economics/industry scale
        ("HostA", "Let's talk economics for a second, there's actually a decent-sized industry built around {topic}, right?"),
        ("HostB", "Right, a lot of people probably don't realize there's a whole supply chain built up around this topic, with quite a few moving parts involved."),
        ("HostA", "Can you walk through what some of those parts actually look like, it sounds pretty extensive."),
        ("HostB", "From the very start all the way to reaching everyday people, it goes through several stages, and each one has its own particular logic and quirks."),
        ("HostA", "Looking at it that way, the business side of this is honestly worth studying on its own, it's a lot more than what's visible on the surface."),
        ("HostB", "Exactly, a lot of things we take for granted actually have a whole economic system quietly supporting them behind the scenes."),
    ],
    [  # case study
        ("HostA", "Let's close with a concrete example — is there a specific case related to {topic} that really stands out to you?"),
        ("HostB", "There's one that really stuck with me, the situation lined up with a lot of the points we've touched on today, it felt pretty representative."),
        ("HostA", "What happened exactly, can you walk us through it?"),
        ("HostB", "It basically started from a really small moment and gradually grew into something everyone could see later on, the whole process was pretty winding."),
        ("HostA", "Stories like that feel a lot more real, honestly more convincing than just talking in the abstract."),
        ("HostB", "Agreed, a concrete example always resonates more, which is exactly why I like using real cases when we talk about {topic}."),
    ],
]


def _estimate_seconds(texts: list[str], chinese: bool) -> float:
    if chinese:
        units = sum(len(t) for t in texts)
        rate = CHARS_PER_SEC_ZH
    else:
        units = sum(len(t.split()) for t in texts)
        rate = WORDS_PER_SEC_EN
    return units / rate + PAUSE_SECONDS * len(texts)


def _build_episode_turns(topic: str, chinese: bool, target_minutes: float) -> list[Turn]:
    intro = _ZH_INTRO if chinese else _EN_INTRO
    outro = _ZH_OUTRO if chinese else _EN_OUTRO
    segments = _ZH_SEGMENTS if chinese else _EN_SEGMENTS

    turns: list[Turn] = []
    elapsed = 0.0

    def append(template_turns) -> float:
        texts = [text.format(topic=topic) for _, text in template_turns]
        turns.extend(Turn(speaker=speaker, text=text) for (speaker, _), text in zip(template_turns, texts))
        return _estimate_seconds(texts, chinese)

    elapsed += append(intro)
    outro_seconds = _estimate_seconds([text.format(topic=topic) for _, text in outro], chinese)

    target_seconds = target_minutes * 60
    max_uses = len(segments) * MAX_SEGMENT_USES_MULTIPLIER
    pool = itertools.cycle(segments)
    uses = 0
    while elapsed + outro_seconds < target_seconds and uses < max_uses:
        elapsed += append(next(pool))
        uses += 1

    append(outro)
    return turns


def _parse_open_notebook_transcript(transcript) -> list[Turn]:
    """Parse an open-notebook podcast transcript into HostA/HostB Turns.

    Accepts either:
      - A list of dicts like [{"speaker": "...", "dialogue": "..."}, ...]
        (structured output from podcast_creator)
      - A plain string with "Speaker: text" lines (legacy/fallback)

    Maps the first two distinct speakers to HostA/HostB in order of appearance.
    """
    speaker_map: dict[str, str] = {}
    host_slots = ["HostA", "HostB"]
    turns: list[Turn] = []

    if isinstance(transcript, list):
        for item in transcript:
            if not isinstance(item, dict):
                continue
            raw_speaker = str(item.get("speaker", "")).strip()
            text = str(item.get("dialogue", item.get("text", ""))).strip()
            if not raw_speaker or not text:
                continue
            if raw_speaker not in speaker_map:
                if len(speaker_map) >= len(host_slots):
                    continue
                speaker_map[raw_speaker] = host_slots[len(speaker_map)]
            turns.append(Turn(speaker=speaker_map[raw_speaker], text=text))
    else:
        line_re = re.compile(r"^\**([^:*\n]{1,60}?)\**\s*:\s*\**(.+?)\**\s*$", re.MULTILINE)
        for m in line_re.finditer(str(transcript)):
            raw_speaker = m.group(1).strip()
            text = m.group(2).strip()
            if not text:
                continue
            if raw_speaker not in speaker_map:
                if len(speaker_map) >= len(host_slots):
                    continue
                speaker_map[raw_speaker] = host_slots[len(speaker_map)]
            turns.append(Turn(speaker=speaker_map[raw_speaker], text=text))

    if not turns:
        raise RuntimeError(
            "open-notebook transcript contains no recognisable speaker turns.\n"
            f"Preview: {str(transcript)[:400]}"
        )
    return turns


class OpenNotebookScriptGenerator(ScriptGenerator):
    """LLM-backed podcast script generator via a running open-notebook instance.

    open-notebook (https://github.com/lfnovo/open-notebook) is a self-hosted
    NotebookLM alternative.  This generator calls its REST API to produce a
    proper, researched dialogue script.

    Setup:
      1. Run open-notebook: docker compose up -d
      2. Open http://localhost:5055, configure LLM credentials and at least one
         episode profile + speaker profile.
      3. Set OPEN_NOTEBOOK_URL=http://localhost:5055 (or pass base_url here).
      4. Pass the profile names you configured via episode_profile /
         speaker_profile (or set OPEN_NOTEBOOK_EPISODE_PROFILE /
         OPEN_NOTEBOOK_SPEAKER_PROFILE env vars).

    The generator submits an async job, polls until the transcript is ready,
    and parses the result into HostA/HostB Turns — open-notebook's speaker
    names from the profile are remapped automatically.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:5055",
        episode_profile: str = "default",
        speaker_profile: str = "default",
        transformation_name: Optional[str] = "blabber_dialogue_script",
        model_id: Optional[str] = None,
        request_timeout: float = 300.0,
        chunk_minutes: float = 2.0,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
        request_retries: int = 2,
        retry_delay: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.episode_profile = episode_profile
        self.speaker_profile = speaker_profile
        self.transformation_name = transformation_name
        self.model_id = model_id
        self.request_timeout = request_timeout
        self.chunk_minutes = max(0.5, chunk_minutes)
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.request_retries = max(0, request_retries)
        self.retry_delay = max(0.1, retry_delay)
        # Local Open Notebook traffic must not inherit HTTP(S)_PROXY from
        # the shell; proxying loopback/IPv6 loopback produces misleading 502s.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        for attempt in range(self.request_retries + 1):
            req = urllib.request.Request(
                f"{self.base_url}{path}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with self._opener.open(
                    req, timeout=self.request_timeout
                ) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as error:
                detail = error.read().decode()[:500]
                transient = error.code in {502, 503, 504}
                if transient and attempt < self.request_retries:
                    delay = self.retry_delay * (2 ** attempt)
                    print(
                        f"[open-notebook] Provider 暂时不可用 "
                        f"(HTTP {error.code})，{delay:g}s 后重试 "
                        f"{attempt + 1}/{self.request_retries}",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"open-notebook POST {path} → HTTP {error.code}: "
                    f"{detail}"
                ) from error
            except urllib.error.URLError as error:
                if attempt < self.request_retries:
                    delay = self.retry_delay * (2 ** attempt)
                    print(
                        f"[open-notebook] 连接失败，{delay:g}s 后重试 "
                        f"{attempt + 1}/{self.request_retries}",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"无法连接 open-notebook（{self.base_url}）："
                    f"{error.reason}"
                ) from error
        raise RuntimeError("open-notebook 请求重试后仍失败")

    def _get(self, path: str) -> dict:
        try:
            with self._opener.open(
                f"{self.base_url}{path}", timeout=self.request_timeout
            ) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"open-notebook GET {path} → HTTP {e.code}: {e.read().decode()[:500]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"无法连接 open-notebook（{self.base_url}）：{e.reason}")

    def generate(
        self, prompt: str, target_minutes: float = DEFAULT_TARGET_MINUTES, on_progress=None
    ) -> Episode:
        topic = _extract_topic(prompt)
        chinese = is_chinese(prompt)

        duration_hint = (
            f"目标时长约{target_minutes:g}分钟。" if chinese
            else f"Target episode duration: approximately {target_minutes:g} minutes."
        )

        # Blabber only needs dialogue text: audio is synthesized later by
        # Edge TTS. A Transformation avoids open-notebook's podcast endpoint,
        # which requires a separate voice model even when its audio is unused.
        if self.transformation_name:
            transformations = self._get("/api/transformations")
            transformation = next(
                (
                    item
                    for item in transformations
                    if item.get("name") == self.transformation_name
                ),
                None,
            )
            if transformation is None:
                raise RuntimeError(
                    "open-notebook transformation "
                    f"'{self.transformation_name}' does not exist"
                )
            total_chunks = max(1, ceil(target_minutes / self.chunk_minutes))
            chunk_duration = target_minutes / total_chunks
            turns = []
            print(
                f"[open-notebook] 生成纯文本双主持脚本: {topic}"
                f"（{total_chunks} 段）"
            )
            for index in range(total_chunks):
                part_hint = (
                    f"这是完整节目的第 {index + 1}/{total_chunks} 段，"
                    f"本段目标时长约 {chunk_duration:g} 分钟。"
                    if chinese
                    else f"This is part {index + 1} of {total_chunks}; "
                    f"target about {chunk_duration:g} minutes for this part."
                )
                if index == 0:
                    continuity_hint = (
                        "这是完整长节目的开头。自然开场并直接进入主题；"
                        "本段末尾不要总结、告别，也不要提到下一段。"
                        if chinese
                        else "This is the beginning of one continuous long episode. "
                        "Do not conclude, sign off, or mention another part at the end."
                    )
                else:
                    recent_context = "\n".join(
                        f"{turn.speaker}: {turn.text}" for turn in turns[-6:]
                    )
                    if index == total_chunks - 1:
                        continuity_hint = (
                            "这是同一个长节目的最后一部分。必须紧接下面的上文继续，"
                            "不要重新介绍主题，不要说“回到主题”或重复已讲内容；"
                            "只有本段结尾可以做整期节目的自然总结和告别。\n"
                            f"上文最后对白：\n{recent_context}"
                            if chinese
                            else "This is the final continuation of the same episode. "
                            "Continue directly from the context below without restarting "
                            "or repeating it. Only the end may conclude the whole episode.\n"
                            f"Previous dialogue:\n{recent_context}"
                        )
                    else:
                        continuity_hint = (
                            "这是同一个长节目的中间部分。必须紧接下面的上文继续，"
                            "像一段从未被切开的对话；不要重新欢迎、重新介绍主题、"
                            "总结、告别，禁止出现“这一段”“下一段”“下段接着聊”"
                            "“回到主题”等分段痕迹。\n"
                            f"上文最后对白：\n{recent_context}"
                            if chinese
                            else "This is a middle continuation of the same episode. "
                            "Continue directly from the context below as one unbroken "
                            "conversation. Do not restart, summarize, sign off, mention "
                            "parts, or repeat the topic introduction.\n"
                            f"Previous dialogue:\n{recent_context}"
                        )
                request_body = {
                    "transformation_id": transformation["id"],
                    "input_text": (
                        f"{prompt}\n{duration_hint}\n{part_hint}\n{continuity_hint}"
                    ),
                }
                if self.model_id:
                    request_body["model_id"] = self.model_id
                result = self._post("/api/transformations/execute", request_body)
                output = result.get("output")
                if not output:
                    raise RuntimeError(
                        f"open-notebook transformation returned no output: {result}"
                    )
                chunk_turns = _parse_open_notebook_transcript(output)
                if turns and chunk_turns and turns[-1].speaker == chunk_turns[0].speaker:
                    chunk_turns = [
                        Turn(
                            speaker="HostB" if turn.speaker == "HostA" else "HostA",
                            text=turn.text,
                        )
                        for turn in chunk_turns
                    ]
                turns.extend(chunk_turns)
                if on_progress:
                    on_progress(index + 1, total_chunks)
            return Episode(topic=topic, turns=turns)

        print(f"[open-notebook] 提交播客生成任务: {topic}")
        job = self._post("/api/podcasts/generate", {
            "episode_profile": self.episode_profile,
            "speaker_profile": self.speaker_profile,
            "episode_name": topic,
            "content": prompt,
            "briefing_suffix": duration_hint,
        })
        job_id = job.get("job_id")
        if not job_id:
            raise RuntimeError(f"open-notebook did not return a job_id: {job}")
        print(f"[open-notebook] 任务 ID: {job_id}，等待完成…")

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(self.poll_interval)
            status = self._get(f"/api/podcasts/jobs/{job_id}")
            job_status = status.get("status", "")
            result = status.get("result") or {}
            print(f"[open-notebook] 状态: {job_status}")

            # result is PodcastGenerationOutput serialized:
            # {"episode_id": "...", "transcript": {"transcript": [{speaker, dialogue}, ...]}}
            transcript_wrapper = result.get("transcript") if isinstance(result, dict) else None
            if isinstance(transcript_wrapper, dict):
                raw_transcript = transcript_wrapper.get("transcript")
            else:
                raw_transcript = transcript_wrapper  # might be a string or list directly

            if raw_transcript:
                print("[open-notebook] 脚本已生成，解析中…")
                turns = _parse_open_notebook_transcript(raw_transcript)
                return Episode(topic=topic, turns=turns)

            if job_status in ("failed", "error"):
                raise RuntimeError(
                    f"open-notebook job {job_id} failed: {status.get('error_message', status)}"
                )
        raise TimeoutError(
            f"open-notebook job {job_id} did not produce a transcript within {self.timeout}s"
        )
