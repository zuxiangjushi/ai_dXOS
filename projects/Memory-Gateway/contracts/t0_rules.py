import re
from dataclasses import dataclass

MEMORY_VERB = re.compile(r"(记住|记一下|记下来|以后都|从现在起|今后|一定要|别忘)")
NEGATION    = re.compile(r"(不再|别再|已经改成|改用|放弃了|换成|不用了)")
FORGET      = re.compile(r"(忘掉|忘记|删除.{0,8}记忆|清空记忆)")
DECLARATIVE = re.compile(r"(我叫|我负责|我们项目|我的偏好|我习惯|我用)")

@dataclass(frozen=True)
class RuleHit:
    tier: str
    rule: str
    @property
    def is_a(self):
        return self.tier == "A"

def classify_tier(text):
    if FORGET.search(text):
        return RuleHit("A", "forget")
    if MEMORY_VERB.search(text):
        return RuleHit("A", "memory_verb")
    if NEGATION.search(text):
        return RuleHit("A", "negation_flip")
    if DECLARATIVE.search(text):
        return RuleHit("A", "declarative")
    return RuleHit("B", "async_default")
