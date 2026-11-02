"""Survey forms from a plain definition: skip logic, validation and tabulation.

Conditions such as "age >= 18 and sex == 'F'" are parsed by a small expression language of
our own. Form definitions may come from anyone, so Python's eval is never used on them.
"""
import json
import re
from collections import Counter
from datetime import date

TYPES = ("text", "integer", "decimal", "date", "select_one", "select_multiple", "note")
TOKEN = re.compile(r"\s*(?:(?P<num>\d+\.?\d*)|(?P<str>'[^']*'|\"[^\"]*\")|(?P<id>[A-Za-z_]\w*)|(?P<op>==|!=|<=|>=|[<>()\[\],+\-*/.]))")


class FormError(Exception):
    pass


class Expr:
    """A recursive-descent parser that evaluates as it reads. A missing answer is None, and
    comparisons with None are false, so a condition on an unanswered question stays quiet."""

    def __init__(self, text):
        self.text = text
        self.t = []
        pos = 0
        while pos < len(text):
            if not text[pos:].strip():
                break
            m = TOKEN.match(text, pos)
            if not m:
                raise FormError(f"cannot read the condition at: {text[pos:]}")
            pos = m.end()
            self.t.append((m.lastgroup, m.group(m.lastgroup)))
        self.t.append(("end", ""))

    def run(self, answers, value=None):
        self.i = 0
        self.a = answers
        self.value = value
        out = self.or_()
        if self.t[self.i][0] != "end":
            raise FormError(f"unexpected {self.t[self.i][1]} in {self.text}")
        return out

    def peek(self):
        return self.t[self.i][1] if self.t[self.i][0] in ("op", "id") else None

    def take(self):
        self.i += 1
        return self.t[self.i - 1]

    def or_(self):
        v = self.and_()
        while self.peek() == "or":
            self.take()
            r = self.and_()
            v = bool(v) or bool(r)
        return v

    def and_(self):
        v = self.not_()
        while self.peek() == "and":
            self.take()
            r = self.not_()
            v = bool(v) and bool(r)
        return v

    def not_(self):
        if self.peek() == "not":
            self.take()
            return not self.not_()
        return self.cmp()

    def cmp(self):
        v = self.add()
        while self.peek() in ("==", "!=", "<", ">", "<=", ">="):
            op = self.take()[1]
            r = self.add()
            if v is None or r is None:
                v = False
                continue
            try:
                v = {"==": v == r, "!=": v != r, "<": v < r, ">": v > r, "<=": v <= r, ">=": v >= r}[op]
            except TypeError:
                v = False
        return v

    def add(self):
        v = self.mul()
        while self.peek() in ("+", "-"):
            op = self.take()[1]
            r = self.mul()
            v = None if v is None or r is None else v + r if op == "+" else v - r
        return v

    def mul(self):
        v = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()[1]
            r = self.unary()
            if v is None or r is None or (op == "/" and r == 0):
                v = None
            else:
                v = v * r if op == "*" else v / r
        return v

    def unary(self):
        if self.peek() == "-":
            self.take()
            v = self.unary()
            return None if v is None else -v
        return self.atom()

    def atom(self):
        kind, text = self.take()
        if kind == "num":
            return float(text) if "." in text else int(text)
        if kind == "str":
            return text[1:-1]
        if text == "(":
            v = self.or_()
            if self.take()[1] != ")":
                raise FormError(f"missing ) in {self.text}")
            return v
        if text == ".":
            return self.value
        if kind == "id":
            if text == "true":
                return True
            if text == "false":
                return False
            if self.peek() == "(":
                self.take()
                args = []
                if self.peek() != ")":
                    args.append(self.or_())
                    while self.peek() == ",":
                        self.take()
                        args.append(self.or_())
                if self.take()[1] != ")":
                    raise FormError(f"missing ) in {self.text}")
                return self.call(text, args)
            return self.a.get(text)
        raise FormError(f"unexpected {text!r} in {self.text}")

    @staticmethod
    def call(name, args):
        if name == "selected":
            return args[1] in (args[0] or [])
        if name == "count":
            return len(args[0] or [])
        if name == "answered":
            return args[0] not in (None, "", [])
        if name == "length":
            return len(str(args[0] or ""))
        raise FormError(f"unknown function {name}")


def evaluate(text, answers, value=None):
    return Expr(text).run(answers, value)


class Survey:
    def __init__(self, data):
        self.title = data.get("title", "Survey")
        self.questions = data["questions"]
        names = set()
        for q in self.questions:
            n = q.get("name", "")
            if not re.fullmatch(r"[A-Za-z_]\w*", n):
                raise FormError(f"bad question name: {n!r}")
            if n in names:
                raise FormError(f"question {n} appears twice")
            names.add(n)
            if q.get("type") not in TYPES:
                raise FormError(f"{n}: unknown type {q.get('type')}")
            if q["type"].startswith("select") and not q.get("choices"):
                raise FormError(f"{n}: needs choices")
            for key in ("relevant", "constraint"):
                if q.get(key):
                    used = {v for k, v in Expr(q[key]).t if k == "id"} - {"and", "or", "not", "true", "false", "selected", "count", "answered", "length"}
                    if used - names - {q["name"]}:
                        raise FormError(f"{n}: {key} uses {sorted(used - names)[0]}, which is not an earlier question")

    def visible(self, answers):
        """Questions that apply, given the answers so far. Hidden questions do not count as answered."""
        out = []
        known = {}
        for q in self.questions:
            if not q.get("relevant") or evaluate(q["relevant"], known):
                out.append(q)
                known[q["name"]] = answers.get(q["name"])
        return out

    def convert(self, q, raw):
        """Turn submitted text into a typed value, or raise ValueError with a message for the enumerator."""
        t = q["type"]
        if t == "select_multiple":
            items = raw if isinstance(raw, list) else [x for x in str(raw or "").split(",") if x]
            valid = {c[0] for c in q["choices"]}
            for x in items:
                if x not in valid:
                    raise ValueError(f"{x} is not a choice")
            return items or None
        text = str(raw if raw is not None else "").strip()
        if text == "":
            return None
        if t == "integer":
            if not re.fullmatch(r"-?\d+", text):
                raise ValueError("enter a whole number")
            return int(text)
        if t == "decimal":
            try:
                return float(text)
            except ValueError:
                raise ValueError("enter a number") from None
        if t == "date":
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                raise ValueError("enter a date like 2026-11-02") from None
        if t == "select_one" and text not in {c[0] for c in q["choices"]}:
            raise ValueError(f"{text} is not a choice")
        return text

    def check(self, raw):
        """Validate a submission. Returns (clean answers, {question: problem})."""
        clean, errors = {}, {}
        for q in self.visible({k: self._peek(k, v) for k, v in raw.items()}):
            if q["type"] == "note":
                continue
            n = q["name"]
            try:
                v = self.convert(q, raw.get(n))
            except ValueError as exc:
                errors[n] = str(exc)
                continue
            if v is None:
                if q.get("required"):
                    errors[n] = "this question is required"
                continue
            if q.get("constraint") and not evaluate(q["constraint"], clean, v):
                errors[n] = q.get("constraint_message", "this answer is outside the allowed range")
                continue
            clean[n] = v
        return clean, errors

    def _peek(self, name, raw):
        q = next((x for x in self.questions if x["name"] == name), None)
        if q is None:
            return raw
        try:
            return self.convert(q, raw)
        except ValueError:
            return None

    def tabulate(self, rows):
        """Summaries per question. rows: clean answers. Skipped questions are left out of each base."""
        out = []
        for q in self.questions:
            if q["type"] == "note":
                continue
            values = [r[q["name"]] for r in rows if q["name"] in r]
            item = {"name": q["name"], "label": q.get("label", q["name"]), "type": q["type"], "answered": len(values), "skipped": len(rows) - len(values)}
            if q["type"] in ("select_one", "select_multiple"):
                counts = Counter()
                for v in values:
                    counts.update(v if isinstance(v, list) else [v])
                base = len(values) or 1
                item["choices"] = [(label, counts[code], counts[code] / base) for code, label in q["choices"]]
            elif q["type"] in ("integer", "decimal") and values:
                s = sorted(values)
                n = len(s)
                item.update(mean=sum(s) / n, median=s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2, low=s[0], high=s[-1])
            out.append(item)
        return out

    def crosstab(self, rows, a, b):
        """Counts of one single-choice question by another."""
        qa = next(q for q in self.questions if q["name"] == a)
        qb = next(q for q in self.questions if q["name"] == b)
        table = {x[0]: {y[0]: 0 for y in qb["choices"]} for x in qa["choices"]}
        for r in rows:
            if a in r and b in r:
                table[r[a]][r[b]] += 1
        return table


EXAMPLE = json.dumps({"title": "Household needs check", "questions": [
    {"name": "block", "label": "Block", "type": "text", "required": True},
    {"name": "members", "label": "People in the household", "type": "integer", "required": True, "constraint": ". >= 1 and . <= 40", "constraint_message": "must be 1 to 40"},
    {"name": "children", "label": "Children under five", "type": "integer", "constraint": ". <= members", "constraint_message": "cannot exceed household size"},
    {"name": "water", "label": "Main water source", "type": "select_one", "required": True, "choices": [["tap", "Tap stand"], ["well", "Tube well"], ["other", "Other"]]},
    {"name": "water_other", "label": "Which other source?", "type": "text", "relevant": "water == 'other'", "required": True},
    {"name": "needs", "label": "Priority needs", "type": "select_multiple", "choices": [["food", "Food"], ["shelter", "Shelter"], ["health", "Health"], ["school", "School"]]},
]}, indent=1)
