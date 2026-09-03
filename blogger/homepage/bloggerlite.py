#!/usr/bin/env python3
"""A very small Blogger template evaluator.

Just enough of Blogger's "Layouts v3" template language to render the Youdle
homepage locally, so ``preview.py`` can serve the *actual generated theme*
rather than a hand-maintained copy of it. If the preview renders, the same
markup and expressions are what Blogger will run.

Supported, because that is exactly what src/homepage.xml uses:

  elements     b:if / b:elseif / b:else, b:loop, b:with, b:eval, b:comment,
               b:class, b:attr, b:include (resolved from a registry),
               <data:some.path/>
  attributes   expr:anything
  expressions  data: references, string and number literals, + - * /,
               == != lt gt lte gte < >, and / or / not, `in` with {..} and [..],
               ternary a ? b : c, elvis a ?: b, object literals,
               property chains (.first .size .length .any .name .escaped
               .jsonEscaped .iso8601 .canonical .isResizable ...),
               and the operators format(), snippet(), resizeImage().

Anything else raises, loudly, rather than silently rendering wrong.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime

B = "{http://www.google.com/2005/gml/b}"
DATA = "{http://www.google.com/2005/gml/data}"
EXPR = "{http://www.google.com/2005/gml/expr}"

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
RAW_TEXT_ELEMENTS = {"script", "style"}


class TemplateError(RuntimeError):
    pass


# ==========================================================================
# Values
# ==========================================================================


class Str(str):
    """A string carrying Blogger's derived properties (.isResizable etc.)."""

    def __new__(cls, value, **props):
        obj = super().__new__(cls, value)
        obj.props = props
        return obj


class Date:
    """A post date. Renders in the blog's configured format by default."""

    def __init__(self, moment: datetime):
        self.moment = moment

    def __str__(self) -> str:
        return self.format("MMMM d, YYYY")

    def __bool__(self) -> bool:
        return True

    ICU = [
        ("MMMM", "%B"), ("MMM", "%b"), ("MM", "%m"),
        ("YYYY", "%Y"), ("yyyy", "%Y"), ("YY", "%y"),
        ("EEEE", "%A"), ("EEE", "%a"),
        ("dd", "%d"), ("HH", "%H"), ("hh", "%I"), ("mm", "%M"), ("ss", "%S"),
    ]

    def format(self, pattern: str) -> str:
        out, i = [], 0
        while i < len(pattern):
            for token, code in self.ICU:
                if pattern.startswith(token, i):
                    out.append(self.moment.strftime(code))
                    i += len(token)
                    break
            else:
                if pattern[i] == "d":
                    out.append(str(self.moment.day))
                elif pattern[i] == "M":
                    out.append(str(self.moment.month))
                else:
                    out.append(pattern[i])
                i += 1
        # %d / %m keep their leading zero; %-d is not portable to Windows.
        return "".join(out)

    def prop(self, name: str):
        if name == "iso8601":
            return Str(self.moment.isoformat())
        if name == "year":
            return self.moment.year
        if name == "month":
            return self.moment.month
        if name == "day":
            return self.moment.day
        raise TemplateError(f"unsupported date property .{name}")


def truthy(value) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return True


def get_prop(value, name: str):
    if isinstance(value, Date):
        return value.prop(name)

    if isinstance(value, dict):
        if name in value:
            return value[name]
        raise TemplateError(f"no key {name!r} on object with keys {sorted(value)}")

    if isinstance(value, (list, tuple)):
        if name == "any":
            return len(value) > 0
        if name in ("size", "length"):
            return len(value)
        if name == "first":
            return value[0] if value else None
        if name == "last":
            return value[-1] if value else None
        raise TemplateError(f"unsupported list property .{name}")

    if isinstance(value, str):
        extra = getattr(value, "props", {})
        if name in extra:
            return extra[name]
        if name == "escaped":
            return Str(html.escape(value, quote=True))
        if name == "jsonEscaped":
            return Str(json.dumps(value)[1:-1])
        if name in ("jsEscaped", "cssEscaped"):
            return Str(value.replace("\\", "\\\\").replace("'", "\\'"))
        if name in ("size", "length"):
            return len(value)
        raise TemplateError(f"unsupported string property .{name}")

    if value is None:
        return None

    raise TemplateError(f"cannot read .{name} from {type(value).__name__}")


# ==========================================================================
# Expression tokenizer + parser
# ==========================================================================

TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<data>data:[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
    | (?P<string>"[^"]*"|'[^']*')
    | (?P<number>\d+(?:\.\d+)?)
    | (?P<name>[A-Za-z_][A-Za-z0-9_-]*)
    | (?P<op><=|>=|==|!=|\?:|[-+*/(){}\[\],:?<>.])
    """,
    re.VERBOSE,
)

WORD_OPS = {"lt": "<", "gt": ">", "lte": "<=", "gte": ">=", "le": "<=", "ge": ">="}


def tokenize(source: str):
    tokens, pos = [], 0
    while pos < len(source):
        match = TOKEN_RE.match(source, pos)
        if not match:
            raise TemplateError(f"cannot tokenize expression at {source[pos:pos + 30]!r}")
        pos = match.end()
        kind = match.lastgroup
        if kind == "ws":
            continue
        tokens.append((kind, match.group()))
    tokens.append(("end", ""))
    return tokens


class Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def next(self):
        token = self.tokens[self.i]
        self.i += 1
        return token

    def accept(self, kind, text=None) -> bool:
        k, t = self.peek()
        if k == kind and (text is None or t == text):
            self.i += 1
            return True
        return False

    def expect(self, kind, text=None):
        k, t = self.next()
        if k != kind or (text is not None and t != text):
            raise TemplateError(f"expected {text or kind}, got {t!r} in {self.source!r}")
        return t

    # -- precedence climbing -------------------------------------------------

    def parse(self):
        node = self.ternary()
        if self.peek()[0] != "end":
            raise TemplateError(f"trailing input {self.peek()[1]!r} in {self.source!r}")
        return node

    def ternary(self):
        cond = self.or_()
        if self.accept("op", "?:"):
            return ("elvis", cond, self.ternary())
        if self.accept("op", "?"):
            yes = self.ternary()
            self.expect("op", ":")
            return ("ternary", cond, yes, self.ternary())
        return cond

    def or_(self):
        node = self.and_()
        while self.accept("name", "or"):
            node = ("or", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.accept("name", "and"):
            node = ("and", node, self.not_())
        return node

    def not_(self):
        if self.accept("name", "not"):
            return ("not", self.not_())
        return self.comparison()

    def comparison(self):
        node = self.additive()
        while True:
            kind, text = self.peek()
            if kind == "op" and text in ("==", "!=", "<", ">", "<=", ">="):
                self.next()
                node = ("cmp", text, node, self.additive())
            elif kind == "name" and text in WORD_OPS:
                self.next()
                node = ("cmp", WORD_OPS[text], node, self.additive())
            elif kind == "name" and text == "in":
                self.next()
                node = ("in", node, self.additive())
            elif kind == "name" and text == "not" and self.tokens[self.i + 1][1] == "in":
                self.next()
                self.next()
                node = ("not", ("in", node, self.additive()))
            else:
                return node

    def additive(self):
        node = self.multiplicative()
        while True:
            kind, text = self.peek()
            if kind == "op" and text in ("+", "-"):
                self.next()
                node = ("arith", text, node, self.multiplicative())
            else:
                return node

    def multiplicative(self):
        node = self.postfix()
        while True:
            kind, text = self.peek()
            if kind == "op" and text in ("*", "/"):
                self.next()
                node = ("arith", text, node, self.postfix())
            else:
                return node

    def postfix(self):
        node = self.primary()
        while True:
            if self.accept("op", "."):
                node = ("prop", node, self.expect("name"))
            elif self.accept("op", "["):
                index = self.ternary()
                self.expect("op", "]")
                node = ("index", node, index)
            else:
                return node

    def primary(self):
        kind, text = self.next()

        if kind == "data":
            return ("data", text[len("data:"):])
        if kind == "string":
            return ("lit", text[1:-1])
        if kind == "number":
            return ("lit", float(text) if "." in text else int(text))
        if kind == "name":
            if text == "true":
                return ("lit", True)
            if text == "false":
                return ("lit", False)
            if self.accept("op", "("):
                args = []
                if not self.accept("op", ")"):
                    args.append(self.ternary())
                    while self.accept("op", ","):
                        args.append(self.ternary())
                    self.expect("op", ")")
                return ("call", text, args)
            raise TemplateError(f"unexpected identifier {text!r} in {self.source!r}")
        if kind == "op" and text == "(":
            node = self.ternary()
            self.expect("op", ")")
            return node
        if kind == "op" and text == "[":
            items = []
            if not self.accept("op", "]"):
                items.append(self.ternary())
                while self.accept("op", ","):
                    items.append(self.ternary())
                self.expect("op", "]")
            return ("array", items)
        if kind == "op" and text == "{":
            return self.brace()

        raise TemplateError(f"unexpected {text!r} in {self.source!r}")

    def brace(self):
        """`{a: 1}` is an object literal; `{"a", "b"}` is a set literal."""
        if self.accept("op", "}"):
            return ("object", [])
        is_object = self.peek()[0] == "name" and self.tokens[self.i + 1][1] == ":"
        items = []
        while True:
            if is_object:
                key = self.expect("name")
                self.expect("op", ":")
                items.append((key, self.ternary()))
            else:
                items.append(self.ternary())
            if not self.accept("op", ","):
                break
        self.expect("op", "}")
        return ("object", items) if is_object else ("array", items)


_CACHE: dict[str, tuple] = {}


def parse_expression(source: str):
    if source not in _CACHE:
        _CACHE[source] = Parser(source).parse()
    return _CACHE[source]


# ==========================================================================
# Evaluation
# ==========================================================================


def evaluate(node, scope: dict):
    kind = node[0]

    if kind == "lit":
        return node[1]

    if kind == "data":
        path = node[1].split(".")
        if path[0] not in scope:
            raise TemplateError(f"unknown data reference: data:{node[1]}")
        value = scope[path[0]]
        for part in path[1:]:
            value = get_prop(value, part)
        return value

    if kind == "prop":
        return get_prop(evaluate(node[1], scope), node[2])

    if kind == "index":
        return evaluate(node[1], scope)[int(evaluate(node[2], scope))]

    if kind == "array":
        return [evaluate(item, scope) for item in node[1]]

    if kind == "object":
        return {key: evaluate(value, scope) for key, value in node[1]}

    if kind == "not":
        return not truthy(evaluate(node[1], scope))

    if kind == "and":
        return truthy(evaluate(node[1], scope)) and truthy(evaluate(node[2], scope))

    if kind == "or":
        return truthy(evaluate(node[1], scope)) or truthy(evaluate(node[2], scope))

    if kind == "elvis":
        value = evaluate(node[1], scope)
        return value if truthy(value) else evaluate(node[2], scope)

    if kind == "ternary":
        return evaluate(node[2] if truthy(evaluate(node[1], scope)) else node[3], scope)

    if kind == "in":
        return evaluate(node[1], scope) in evaluate(node[2], scope)

    if kind == "cmp":
        op, left, right = node[1], evaluate(node[2], scope), evaluate(node[3], scope)
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if isinstance(left, Date):
            left = left.moment
        if isinstance(right, Date):
            right = right.moment
        return {
            "<": left < right, ">": left > right,
            "<=": left <= right, ">=": left >= right,
        }[op]

    if kind == "arith":
        op, left, right = node[1], evaluate(node[2], scope), evaluate(node[3], scope)
        if op == "+" and (isinstance(left, str) or isinstance(right, str)):
            return Str(render_value(left) + render_value(right))
        return {"+": lambda: left + right, "-": lambda: left - right,
                "*": lambda: left * right, "/": lambda: left / right}[op]()

    if kind == "call":
        name, args = node[1], [evaluate(a, scope) for a in node[2]]
        return call_operator(name, args)

    raise TemplateError(f"cannot evaluate node {kind}")


def call_operator(name: str, args: list):
    if name == "format":
        value, pattern = args[0], args[1]
        if isinstance(value, Date):
            return Str(value.format(pattern))
        return Str(str(value))

    if name == "snippet":
        text = render_value(args[0])
        options = args[1] if len(args) > 1 else {}
        if options.get("links") is False:
            text = re.sub(r"</?a\b[^>]*>", "", text)
        if options.get("linebreaks") is False:
            text = re.sub(r"<br\s*/?>|\s*\n\s*", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        limit = int(options.get("length", 50))
        if len(text) > limit:
            text = text[:limit].rstrip()
            if options.get("ellipsis", True):
                text += "…"
        return Str(text)

    if name == "resizeImage":
        url = render_value(args[0])
        width = int(args[1]) if len(args) > 1 else 0
        ratio = args[2] if len(args) > 2 else None
        # Mirror Google's /sN-c-wW-hH/ path segment closely enough to preview.
        if not width:
            return Str(url)
        height = width
        if ratio and ":" in str(ratio):
            w, h = str(ratio).split(":")
            height = int(round(width * int(h) / int(w)))
        marker = f"/w{width}-h{height}-p-k-no-nu/"
        return Str(re.sub(r"/(s\d+|w\d+-h\d+)[^/]*/", marker, url) if "/s" in url or "/w" in url
                   else url)

    raise TemplateError(f"unsupported operator {name}()")


def render_value(value) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    if isinstance(value, Date):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ==========================================================================
# Element rendering
# ==========================================================================


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


class Renderer:
    def __init__(self, scope: dict, includes: dict | None = None):
        self.scope = scope
        self.includes = includes or {}

    # -- children, with b:if / b:elseif / b:else grouping ---------------------

    def children(self, element, scope: dict, raw: bool) -> str:
        out = []
        if element.text:
            out.append(element.text if raw else esc_text(element.text))
        for child in element:
            out.append(self.node(child, scope, raw))
            if child.tail:
                out.append(child.tail if raw else esc_text(child.tail))
        return "".join(out)

    def node(self, element, scope: dict, raw: bool) -> str:
        tag = element.tag
        if not isinstance(tag, str):  # comment / PI
            return ""

        if tag.startswith(B):
            return self.b_element(local_name(tag), element, scope, raw)

        if tag.startswith(DATA):
            value = self.lookup(local_name(tag), scope)
            text = render_value(value)
            return text if raw else esc_text(text)

        return self.html_element(element, scope, raw)

    def lookup(self, path: str, scope: dict):
        return evaluate(parse_expression("data:" + path), scope)

    # -- b: elements ---------------------------------------------------------

    def b_element(self, name: str, element, scope: dict, raw: bool) -> str:
        if name == "comment":
            return ""

        if name == "if":
            return self.b_if(element, scope, raw)

        if name == "loop":
            values = evaluate(parse_expression(element.get("values")), scope)
            var = element.get("var")
            index = element.get("index")
            out = []
            for i, item in enumerate(values or []):
                child = dict(scope)
                child[var] = item
                if index:
                    child[index] = i
                out.append(self.children(element, child, raw))
            return "".join(out)

        if name == "with":
            child = dict(scope)
            child[element.get("var")] = evaluate(parse_expression(element.get("value")), scope)
            return self.children(element, child, raw)

        if name == "eval":
            text = render_value(evaluate(parse_expression(element.get("expr")), scope))
            return text if raw else esc_text(text)

        if name == "include":
            target = element.get("name")
            if target not in self.includes:
                return f"<!-- b:include {target} not available in preview -->"
            return self.children(self.includes[target], scope, raw)

        if name in ("class", "attr", "elseif", "else"):
            return ""  # handled by the parent / by b_if

        raise TemplateError(f"unsupported element b:{name}")

    def b_if(self, element, scope: dict, raw: bool) -> str:
        """b:elseif and b:else are self-closing markers, not wrappers: content
        belongs to whichever branch marker most recently preceded it."""
        branches = [(element.get("cond"), [])]
        pending_text = element.text or ""
        branches[0][1].append(("text", pending_text))

        for child in element:
            name = local_name(child.tag) if isinstance(child.tag, str) else ""
            if child.tag == B + "elseif":
                branches.append((child.get("cond"), []))
            elif child.tag == B + "else":
                branches.append((None, []))
            else:
                branches[-1][1].append(("node", child))
            if child.tail:
                branches[-1][1].append(("text", child.tail))

        for cond, body in branches:
            if cond is None or truthy(evaluate(parse_expression(cond), scope)):
                out = []
                for kind, item in body:
                    if kind == "text":
                        out.append(item if raw else esc_text(item))
                    else:
                        out.append(self.node(item, scope, raw))
                return "".join(out)
        return ""

    # -- ordinary HTML -------------------------------------------------------

    def html_element(self, element, scope: dict, raw: bool) -> str:
        tag = local_name(element.tag)
        attrs: dict[str, str] = {}

        for key, value in element.attrib.items():
            if key.startswith(EXPR):
                attrs[local_name(key)] = render_value(
                    evaluate(parse_expression(value), scope)
                )
            elif key.startswith(B) or key.startswith(DATA):
                continue
            else:
                attrs[local_name(key)] = value

        # b:class / b:attr are direct children that modify this element.
        for child in element:
            if child.tag == B + "class":
                cond = child.get("cond")
                if cond and not truthy(evaluate(parse_expression(cond), scope)):
                    continue
                name = child.get("name")
                if child.get(EXPR + "name"):
                    name = render_value(
                        evaluate(parse_expression(child.get(EXPR + "name")), scope)
                    )
                attrs["class"] = (attrs.get("class", "") + " " + name).strip()
            elif child.tag == B + "attr":
                cond = child.get("cond")
                if cond and not truthy(evaluate(parse_expression(cond), scope)):
                    continue
                value = child.get("value")
                if child.get(EXPR + "value"):
                    value = render_value(
                        evaluate(parse_expression(child.get(EXPR + "value")), scope)
                    )
                attrs[child.get("name")] = value

        opening = tag + "".join(
            f' {k}="{esc_attr(v)}"' for k, v in attrs.items()
        )

        if tag in VOID_ELEMENTS:
            return f"<{opening}/>"

        inner = self.children(element, scope, raw or tag in RAW_TEXT_ELEMENTS)
        return f"<{opening}>{inner}</{tag}>"


def esc_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;")


def esc_attr(text: str) -> str:
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def render_element(element, scope: dict, includes: dict | None = None) -> str:
    """Render one element's *children* (the element itself is a container)."""
    return Renderer(scope, includes).children(element, scope, raw=False)
