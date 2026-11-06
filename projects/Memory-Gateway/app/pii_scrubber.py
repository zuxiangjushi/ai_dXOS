"""日志 PII 脱敏"""
import re

PATTERNS = [
    (re.compile(r'sk-[A-Za-z0-9_-]{10,}'), 'sk-***REDACTED***'),
    (re.compile(r'Bearer\s+[A-Za-z0-9_.-]{10,}'), 'Bearer ***REDACTED***'),
    (re.compile(r'1[3-9]\d{9}'), '1**********'),
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+'), '***@***.***'),
    (re.compile(r'\b\d{17}[\dXx]\b'), '******************'),
    (re.compile(r'postgresql://[^@]+@'), 'postgresql://***@'),
]


def scrub(text: str) -> str:
    if not text:
        return text
    for pat, rep in PATTERNS:
        text = pat.sub(rep, text)
    return text
