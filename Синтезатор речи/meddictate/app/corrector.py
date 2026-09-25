# -*- coding: utf-8 -*-
"""
Ядро коррекции распознанного текста.

Слои (в порядке применения):
  1. Жёсткие замены             "съем жалуется"        -> "пациент жалуется"
  2. Спасатель терминов        "максим лента"          -> "амоксициллин"
     (фонетическое сопоставление по скользящему окну 1..3 слова)
  3. Числа/единицы/пунктуация  "температура 38 и 5"    -> "температура 38,5."

Слой 2 включается только там, где модель реально ошиблась: если отличие
от термина - только окончание ("сатурации" вместо "сатурация"), текст
не трогается, потому что падеж в диктовке обычно верный.

Всё считается локально, без интернета. Обработка короткого хвоста
занимает доли миллисекунды за счёт кэша и предфильтра по длине.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, Optional

from .dictionary import Replacement, Term, normalize_word
from .numerals import UNIT_WORDS, format_text

# ---------------------------------------------------------------- фонетика
_TRANS = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'i', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '',
    'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}
_VOWELS = set('аеёиоуыэюя')

#: слова, которые спасатель терминов не трогает никогда
_PROTECTED_WORDS = set(UNIT_WORDS) | {
    "первый", "второй", "третий", "четвёртый", "четвертый", "пятый",
    "шестой", "седьмой", "восьмой", "девятый", "десятый",
}

#: служебные слова - окно из них не считаем ошибкой распознавания
_STOPWORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то",
    "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за",
    "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня", "еще",
    "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь",
    "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя",
    "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже",
    "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому",
    "этого", "какой", "совсем", "ним", "здесь", "этом", "один", "почти",
    "мой", "тем", "чтобы", "нее", "сейчас", "были", "куда", "зачем", "всех",
    "никогда", "можно", "при", "наконец", "два", "об", "другой", "хоть",
    "после", "над", "больше", "тот", "через", "эти", "нас", "про", "всего",
    "них", "какая", "много", "разве", "три", "эту", "моя", "впрочем", "хорошо",
    "свою", "этой", "перед", "иногда", "лучше", "чуть", "том", "нельзя",
    "такой", "им", "более", "всегда", "конечно", "всю", "между",
}


@lru_cache(maxsize=200_000)
def phonetic(word: str) -> str:
    """Фонетический «скелет» слова: без гласных, со слитными согласными."""
    w = normalize_word(word)
    out = []
    for ch in w:
        if ch in _TRANS:
            if ch in _VOWELS:
                continue
            out.append(_TRANS[ch])
        else:
            out.append(ch)
    p = "".join(out)
    p = (p.replace("sch", "sh").replace("yo", "o").replace("kh", "h")
          .replace("ya", "a").replace("yu", "u").replace("ts", "c"))
    p = re.sub(r"(.)\1+", r"\1", p)   # сдвоенные согласные не значимы
    return p


@lru_cache(maxsize=200_000)
def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    m = max(len(a), len(b))
    return 1.0 - _lev(a, b) / m


def same_lexeme(a: str, b: str) -> bool:
    """
    Одно и то же слово в разных формах/падежах?
    "давления" и "давление"  -> True
    "сатурации" и "сатурация" -> True
    "пневмония" и "пневмоторакс" -> False
    """
    if a == b:
        return True
    if min(len(a), len(b)) < 3:
        return a[:2] == b[:2]
    for cut in (1, 2, 3):
        sa = a[:-cut] if len(a) > cut + 2 else a
        sb = b[:-cut] if len(b) > cut + 2 else b
        if min(len(sa), len(sb)) < 3:
            break
        if sa.startswith(sb) or sb.startswith(sa):
            return True
    return False


@lru_cache(maxsize=500_000)
def pair_score(heard: str, term: str) -> tuple[float, float]:
    """(общий счёт, счёт по полным строкам) для пары «услышано» / «термин»."""
    h, t = normalize_word(heard), normalize_word(term)
    if not h or not t:
        return 0.0, 0.0
    full = _ratio(h, t)
    ph = _ratio(phonetic(h), phonetic(t))
    len_ratio = min(len(h), len(t)) / max(len(h), len(t))
    score = max(ph, full * 0.9) * (0.55 + 0.45 * len_ratio)
    return score, full


def _stem_key(word: str) -> str:
    """Ключ для быстрого поиска словосочетаний (устойчив к падежным окончаниям)."""
    n = len(word)
    if n <= 3:
        return word
    if n <= 5:
        return word[:2]
    return word[:3]


@lru_cache(maxsize=300_000)
def _accept_cached(words: tuple[str, ...], term_text: str, in_lexicon: bool,
                   threshold: float, window: str, owner) -> tuple[bool, float]:
    """Кэш решений: одинаковые окна проверяются многократно при живом вводе."""
    term = owner._term_by_text(term_text)
    if term is None:
        return False, 0.0
    term.in_lexicon = in_lexicon
    return owner._accept_impl(list(words), term, window)


@dataclass
class Change:
    """Одна правка: что услышали -> что написали."""
    heard: str
    written: str
    score: float = 1.0
    kind: str = "термин"       # термин | замена


@dataclass
class Match:
    start: int          # индекс первого слова окна
    end: int            # индекс за последним словом окна
    term: Term
    score: float


class Corrector:
    """Держит словарь и применяет все слои коррекции."""

    #: порог для терминов, которых нет в лексиконе модели (их надо спасать)
    OOV_THRESHOLD = 0.55
    #: порог для терминов, которые модель знает сама (высокая планка)
    IN_LEXICON_THRESHOLD = 0.72
    #: максимальное окно слов для поиска термина
    MAX_WINDOW = 3

    def __init__(
        self,
        terms: Iterable[Term] = (),
        replacements: Iterable[Replacement] = (),
        threshold: float = 0.55,
        numbers: bool = True,
        units: bool = True,
        capitalize_sentences: bool = True,
        final_period: bool = False,
        lexicon: Optional[Callable[[str], bool]] = None,
        enabled: bool = True,
    ) -> None:
        self.terms = [t for t in terms if t.enabled]
        self.replacements = sorted(replacements, key=lambda r: r.n_words, reverse=True)
        self.threshold = threshold
        self.numbers = numbers
        self.units = units
        self.capitalize_sentences = capitalize_sentences
        self.final_period = final_period
        self.lexicon = lexicon or (lambda w: False)
        self.enabled = enabled
        # индекс: первая буква фонетического скелета -> термины (быстрый предфильтр)
        #: точные термины: (число слов, склеенный текст) - их не «спасаем»,
        #: иначе один препарат заменится на другой (цефтриаксон -> цефуроксим)
        self._term_map: dict[str, Term] = {t.text: t for t in self.terms}
        self._exact_keys: set[tuple[int, str]] = {
            (t.n_words, "".join(t.words)) for t in self.terms
        }
        self._index: dict[str, list[Term]] = {}
        # индекс словосочетаний: (число слов, ключ первого слова, ключ последнего)
        self._phrase_index: dict[tuple[int, str, str], list[Term]] = {}
        for term in self.terms:
            skel = phonetic("".join(term.words))
            for key in {skel[:1], skel[1:2]} if len(skel) > 1 else {skel[:1] or "?"}:
                if key:
                    self._index.setdefault(key, []).append(term)
            if term.n_words > 1:
                pkey = (term.n_words, _stem_key(term.words[0]), _stem_key(term.words[-1]))
                self._phrase_index.setdefault(pkey, []).append(term)
        # самые длинные замены проверяем первыми, поэтому держим и общий список
        self._max_rep = max((r.n_words for r in self.replacements), default=0)
        #: правки последнего вызова process() - показываются в окошке
        self.changes: list[Change] = []

    # ------------------------------------------------------------- индексация
    @staticmethod
    def _bucket(term: Term) -> str:
        skel = phonetic("".join(term.words))
        return skel[:2] if skel else "?"

    def _candidates(self, window_norm: str) -> list[Term]:
        skel = phonetic(window_norm)
        # ключ - первая фонема: «стр графе» и «спирография» дают разные 2-е буквы,
        # поэтому индекс по двум символам пропускал бы нужные термины
        keys = {skel[:1]} if skel else {"?"}
        if len(skel) > 1:
            keys.add(skel[1:2])
        out: list[Term] = []
        seen: set[int] = set()
        term_len = len(skel)
        for key in keys:
            for term in self._index.get(key, ()):          # noqa: SIM118
                if id(term) in seen:      # один термин может попасть в две корзины
                    continue
                seen.add(id(term))
                t_len = len(phonetic("".join(term.words)))
                if abs(t_len - term_len) > max(3, int(0.35 * max(t_len, term_len))):
                    continue
                out.append(term)
        return out

    # ---------------------------------------------------------------- главное
    def process(self, text: str, final: bool = True) -> str:
        """Полная обработка фрагмента. final=False — конец фрагмента ещё может измениться."""
        if not text:
            return text
        if not self.enabled:
            return format_text(
                text, numbers=self.numbers, units=self.units,
                capitalize_sentences=self.capitalize_sentences,
                final_period=self.final_period and final,
            )
        tokens = text.split()
        protect_tail = 0 if final else 1     # последнее слово при потоке ещё «сырое»
        self.changes = []
        tokens = self._apply_replacements(tokens, protect_tail)
        tokens = self._apply_terms(tokens, protect_tail)
        result = " ".join(tokens)
        return format_text(
            result, numbers=self.numbers, units=self.units,
            capitalize_sentences=self.capitalize_sentences,
            final_period=self.final_period and final,
        )

    # ------------------------------------------------------- жёсткие замены
    def _apply_replacements(self, tokens: list[str], protect_tail: int) -> list[str]:
        if not self.replacements or not tokens:
            return tokens
        norm = [normalize_word(t) for t in tokens]
        limit = len(tokens) - protect_tail
        out: list[str] = []
        i = 0
        while i < len(tokens):
            best: Replacement | None = None
            if i < limit:
                for rep in self.replacements:
                    n = rep.n_words
                    if n == 0 or i + n > limit:
                        continue
                    if norm[i:i + n] == rep.heard:
                        best = rep
                        break
            if best is None:
                out.append(tokens[i])
                i += 1
                continue
            heard = " ".join(tokens[i:i + best.n_words])
            out.append(best.write)
            self.changes.append(Change(heard=heard, written=best.write, kind="замена"))
            i += best.n_words
        return out

    # ------------------------------------------------------ спасатель терминов
    def _protected_tokens(self, norm: list[str], limit: int) -> set[int]:
        """
        Индексы слов, входящих в ПРАВИЛЬНО продиктованное словосочетание из словаря
        («артериальное давление», «сахарным диабетом»). Такие слова по отдельности
        не трогаем: иначе «артериальное» превратится в «артралгию».
        """
        protected: set[int] = set()
        if not self._phrase_index:
            return protected
        for i in range(limit):
            if not norm[i]:
                continue
            for n in range(2, 5):
                if i + n > limit:
                    break
                words = norm[i:i + n]
                if not all(words):
                    continue
                key = (n, _stem_key(words[0]), _stem_key(words[-1]))
                for term in self._phrase_index.get(key, ()):      # noqa: SIM118
                    if all(same_lexeme(a, b) for a, b in zip(words, term.words)):
                        protected.update(range(i, i + n))
                        break
        return protected

    def _apply_terms(self, tokens: list[str], protect_tail: int) -> list[str]:
        if not self.terms or not tokens:
            return tokens
        norm = [normalize_word(t) for t in tokens]
        limit = len(tokens) - protect_tail
        protected = self._protected_tokens(norm, limit)
        matches: list[Match] = []
        for i in range(limit):
            if not norm[i]:
                continue
            for n in range(1, min(self.MAX_WINDOW, limit - i) + 1):
                if any(k in protected for k in range(i, i + n)):
                    continue
                window = "".join(norm[i:i + n])
                if len(window) < 3:
                    continue
                best_term, best_score = self._best_term(norm[i:i + n], window)
                if best_term is not None:
                    matches.append(Match(i, i + n, best_term, best_score))
        if not matches:
            return tokens
        # сначала самые уверенные совпадения; короткое окно предпочтительнее
        # длинного («стр графе» -> «спирография», а не «стр графе эхо» -> «спирография»)
        matches.sort(key=lambda m: (-(m.score - 0.05 * (m.end - m.start)), -(m.end - m.start)))
        taken = [False] * len(tokens)
        chosen: list[Match] = []
        for m in matches:
            if any(taken[m.start:m.end]):
                continue
            chosen.append(m)
            for k in range(m.start, m.end):
                taken[k] = True
        if not chosen:
            return tokens
        result: list[str] = []
        by_start = {m.start: m for m in chosen}
        i = 0
        while i < len(tokens):
            m = by_start.get(i)
            if m is not None:
                result.append(m.term.text)
                heard = " ".join(tokens[m.start:m.end])
                if heard != m.term.text:
                    self.changes.append(Change(heard=heard, written=m.term.text,
                                               score=m.score, kind="термин"))
                i = m.end
            else:
                result.append(tokens[i])
                i += 1
        return result

    #: минимальная длина фонетического скелета окна (короткие скелеты не различимы)
    MIN_SKEL = 5
    #: минимальное фонетическое сходство
    PH_MIN = 0.60
    #: вторая ступень: либо явное фонетическое сходство, либо побуквенное
    PH_STRONG = 0.70
    FULL_WEAK = 0.42
    #: для склейки/разрыва слов ("в не больничная" -> "внебольничная") строже
    PH_MERGE = 0.66
    #: если два термина похожи почти одинаково - не угадываем (цефтриаксон/цефуроксим)
    MARGIN = 0.05
    #: при равном числе слов каждое слово должно быть похоже на своё
    POS_MIN = 0.55

    def _accept(self, words: list[str], term: Term, window: str) -> tuple[bool, float]:
        """Проверяет пару «окно слов -> термин» (результат кэшируется)."""
        return _accept_cached(tuple(words), term.text, term.in_lexicon, self.threshold,
                              window, self)

    def _accept_impl(self, words: list[str], term: Term, window: str) -> tuple[bool, float]:
        """Все защитные условия: окно -> термин."""
        # 0. окно не должно начинаться/заканчиваться служебным словом:
        #    иначе «на головную» станет «ингаляционно», а «головокружение и» - «головокружение»
        if words[0] in _STOPWORDS or words[-1] in _STOPWORDS:
            return False, 0.0
        # 0a. окно уже является правильным термином словаря - не трогаем
        if (len(words), window) in self._exact_keys:
            return False, 0.0
        if len(words) > 1 and any(w in _STOPWORDS for w in words):
            # «гастрит и дуоденит» не должен превратиться в «гастродуоденит»
            return False, 0.0
        # 0b. внутри окна не должно быть цифр, единиц измерения и знаков
        for w in words:
            if not w or w.isdigit() or w in _PROTECTED_WORDS or "\n" in w:
                return False, 0.0
        # 0c. термин, который модель знает целиком, не «спасаем»: если модель умеет
        #     все его слова, разница - скорее другая формулировка, а не ошибка слуха
        if term.in_lexicon:
            return False, 0.0
        term_join = "".join(term.words)
        if len(term_join) < 6:
            return False, 0.0
        score, full = pair_score(window, term_join)
        skel_w, skel_t = phonetic(window), phonetic(term_join)
        # 1. слишком короткие скелеты - сравнивать нечего
        if len(skel_w) < self.MIN_SKEL or len(skel_t) < 4:
            return False, 0.0
        ph = _ratio(skel_w, skel_t)
        if ph < self.PH_MIN:
            return False, 0.0
        # 2. первая фонема должна совпадать
        if skel_w[:1] != skel_t[:1]:
            return False, 0.0
        # 3. вторая ступень: явное фонетическое ИЛИ побуквенное сходство
        if ph < self.PH_STRONG and full < self.FULL_WEAK:
            return False, 0.0
        # 3b. одиночное слово - самый рискованный случай, планка выше
        if len(words) == 1 and ph < 0.72 and full < 0.55:
            return False, 0.0
        # 4. общий счёт с учётом длины
        if score < self._threshold(term):
            return False, 0.0

        if len(words) == term.n_words:
            # 5. при равном числе слов: каждое слово должно стоять на своём месте
            if all(same_lexeme(a, b) for a, b in zip(words, term.words)):
                return False, 0.0            # это просто другая форма слова - не трогаем
            for a, b in zip(words, term.words):
                if _ratio(phonetic(a), phonetic(b)) < self.POS_MIN:
                    return False, 0.0
            return True, score

        # 6. склейка/разрыв слов: строгие дополнительные условия
        if ph < self.PH_MERGE:
            return False, 0.0
        # 6a. все слова окна - это те же слова термина в других формах? значит,
        #     врач продиктовал верно, просто в окно попал лишний/недостающий кусок
        if all(any(same_lexeme(w, t) for t in term.words) for w in words):
            return False, 0.0
        # 6b. по длине окно должно покрывать почти весь термин
        lw, lt = len(window), len(term_join)
        if lw < 0.8 * lt or lw > 1.35 * lt:
            return False, 0.0
        return True, score

    def _term_by_text(self, text: str) -> Term | None:
        return self._term_map.get(text)

    def _best_term(self, words: list[str], window: str) -> tuple[Term | None, float]:
        """Лучший термин для окна слов или (None, 0)."""
        best: Term | None = None
        best_score = 0.0
        second = 0.0
        for term in self._candidates(window):
            ok, score = self._accept(words, term, window)
            if not ok:
                continue
            if score > best_score:
                second = best_score
                best, best_score = term, score
            elif score > second:
                second = score
        if best is not None and best_score - second < self.MARGIN:
            # два разных термина подходят одинаково хорошо - безопаснее не менять
            return None, 0.0
        return best, best_score

    def _threshold(self, term: Term) -> float:
        if term.in_lexicon:
            return max(self.threshold, self.IN_LEXICON_THRESHOLD)
        return self.threshold

    # --------------------------------------------------------------- сервис
    def mark_lexicon(self, is_word: Callable[[str], bool]) -> None:
        """Отмечает, какие термины модель знает сама (влияет на порог)."""
        for term in self.terms:
            try:
                term.in_lexicon = all(is_word(w) for w in term.words)
            except Exception:
                term.in_lexicon = False

    def explain(self, text: str) -> str:
        """Отладочный разбор: показывает, что и на что заменилось."""
        before = text.split()
        after = self.process(text, final=True).split()
        return f"было: {' '.join(before)}\nстало: {' '.join(after)}"
