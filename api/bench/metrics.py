"""Scoring for STT outputs. Normalisation is applied to reference and hypothesis alike so
that punctuation, width, casing, spacing, Simplified/Traditional and numeral style do not
count as recognition errors; Traditional-ness is reported as its own metric instead.
"""

import re
import unicodedata
from dataclasses import dataclass

from opencc import OpenCC
from rapidfuzz.distance import Levenshtein

from e2e.judge import SIMPLIFIED

_S2T = OpenCC("s2t")
_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)
_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "萬": 10000, "万": 10000}
_CN_NUM = re.compile(r"[零〇一二兩两三四五六七八九十百千萬万]+")


def _cn_to_int(text: str) -> int | None:
    total, section, number = 0, 0, 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            unit = _CN_UNITS[char]
            if unit == 10000:
                total += (section + number) * unit
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
        else:
            return None
    return total + section + number


def _numerals(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        value = _cn_to_int(match.group(0))
        # keep single digits / ambiguous short forms (e.g. 一 in 一下) untouched
        return str(value) if value is not None and len(match.group(0)) >= 2 else match.group(0)

    return _CN_NUM.sub(repl, text)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _S2T.convert(text)
    text = _numerals(text)
    text = _PUNCT.sub("", text)
    return text.lower()


@dataclass
class Score:
    cer: float
    substitutions: int
    deletions: int
    insertions: int
    term_recall: float | None
    terms_missed: list[str]
    traditional: bool
    simplified_chars: list[str]


def score(reference: str, hypothesis: str, terms: list[str]) -> Score:
    ref, hyp = normalize(reference), normalize(hypothesis)
    ops = Levenshtein.editops(ref, hyp)
    subs = sum(op.tag == "replace" for op in ops)
    dels = sum(op.tag == "delete" for op in ops)
    ins = sum(op.tag == "insert" for op in ops)
    cer = (subs + dels + ins) / max(len(ref), 1)

    missed = [term for term in terms if normalize(term) not in hyp]
    recall = None if not terms else 1 - len(missed) / len(terms)

    simplified = sorted(set(hypothesis) & SIMPLIFIED)
    return Score(cer, subs, dels, ins, recall, missed, not simplified, simplified)
