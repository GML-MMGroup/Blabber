from dataclasses import dataclass, field


@dataclass
class Turn:
    speaker: str
    text: str


@dataclass
class Episode:
    topic: str
    turns: list[Turn] = field(default_factory=list)
