"""Deterministic safety checks for generated HTML before it is rendered."""

from html import unescape
from html.parser import HTMLParser
from typing import List, Optional, Tuple


UNSAFE_TAGS = {
    "script",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "svg",
    "math",
    "meta",
    "link",
}
URL_ATTRIBUTES = {"href", "src", "action", "formaction", "xlink:href"}
UNSAFE_URL_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")


class _GeneratedHTMLSafetyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.issues: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        self._check_element(tag, attrs)

    def handle_startendtag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        self._check_element(tag, attrs)

    def _check_element(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
    ) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in UNSAFE_TAGS:
            self.issues.append(f"Unsafe HTML tag: <{tag}>")

        for name, value in attrs:
            normalized_name = name.casefold()
            decoded_value = unescape(value or "")
            compact_value = "".join(
                character
                for character in decoded_value
                if ord(character) > 32 and ord(character) != 127
            ).casefold()

            if normalized_name.startswith("on") or normalized_name == "srcdoc":
                self.issues.append(f"Unsafe HTML attribute: {name}")
            elif (
                normalized_name in URL_ATTRIBUTES
                and compact_value.startswith(UNSAFE_URL_SCHEMES)
            ):
                self.issues.append(f"Unsafe URL in HTML attribute: {name}")
            elif normalized_name == "style" and (
                "expression(" in compact_value or "url(" in compact_value
            ):
                self.issues.append("Unsafe CSS in style attribute")


def find_unsafe_html_issues(html_content: str) -> List[str]:
    """Return unique unsafe-tag/attribute findings for generated HTML."""
    parser = _GeneratedHTMLSafetyParser()
    try:
        parser.feed(html_content or "")
        parser.close()
    except Exception:
        return ["Generated HTML could not be parsed safely"]

    return list(dict.fromkeys(parser.issues))
