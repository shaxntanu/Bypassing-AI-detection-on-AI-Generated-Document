import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass
class CleanupResult:
    text: str
    changes: dict = field(default_factory=dict)
    review: list = field(default_factory=list)


# Preserve joiners, variation selectors, and invisible mathematical operators.
REMOVABLE = "\u00ad\ufeff\u2060"

BIDI = re.compile(
    r"[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)

CONTROLS = re.compile(
    r"[\x00-\x08\x0e-\x1f\x7f-\x84\x86-\x9f]"
)

FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")

INLINE = re.compile(
    r"(?<!`)(?P<ticks>`+)(?!`)[^\n]*?(?<!`)(?P=ticks)(?!`)"
    r"|https?://[^\s<>]+"
    r"|(?<!\w)www\.[^\s<>]+"
)


def protected_blocks(text):
    """Yield (text, protected) for common Markdown code blocks."""
    pending = []
    fence = None

    for line in text.splitlines(keepends=True):
        match = FENCE.fullmatch(line.rstrip("\r\n"))

        if fence is not None:
            yield line, True

            if (
                match
                and match[1][0] == fence[0]
                and len(match[1]) >= fence[1]
                and not match[2].strip()
            ):
                fence = None

        elif match:
            if pending:
                yield "".join(pending), False
                pending.clear()

            fence = (match[1][0], len(match[1]))
            yield line, True

        elif line.startswith(("    ", "\t")):
            if pending:
                yield "".join(pending), False
                pending.clear()

            yield line, True

        else:
            pending.append(line)

    if pending:
        yield "".join(pending), False


def sanitize_text(
    text: str,
    *,
    normalization: str = "NFC",
    em_dashes: str = "asides",
    zero_width_spaces: str = "remove",
    remove_bidi: bool = False,
    rewrites: Optional[Mapping[str, str]] = None,
) -> CleanupResult:
    """
    Clean prose without guaranteeing grammar or an AI-detector result.

    Options:
        normalization:
            "NFC"  -> preserve compatibility distinctions, e.g. x².
            "NFKC" -> compatibility normalization; can change x² to x2.
            "none" -> skip Unicode normalization.

        em_dashes:
            "asides" -> convert likely paired asides to parentheses.
            "keep"   -> preserve em dashes.

        zero_width_spaces:
            "remove", "space", or "keep".
            Check word boundaries after removal or replacement.

        remove_bidi:
            False by default because directional controls can matter
            in Arabic, Hebrew, and mixed-direction text.

        rewrites:
            Exact, manually reviewed prose replacements.

    Protects common code fences, indented code, inline backticks, and URLs.
    This is not a complete Markdown/HTML parser or a grammar checker.
    No files are read or written.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    if normalization not in {"NFC", "NFKC", "none"}:
        raise ValueError("normalization must be NFC, NFKC, or none")

    if em_dashes not in {"asides", "keep"}:
        raise ValueError("em_dashes must be asides or keep")

    if zero_width_spaces not in {"remove", "space", "keep"}:
        raise ValueError(
            "zero_width_spaces must be remove, space, or keep"
        )

    rewrites = dict(rewrites or {})

    if any(
        not isinstance(before, str)
        or not before
        or not isinstance(after, str)
        for before, after in rewrites.items()
    ):
        raise ValueError(
            "rewrites must map nonempty strings to strings"
        )

    changes = Counter()
    review = []

    def fix_dashes(value):
        # Conservative: abbreviations can prevent an automatic conversion.
        pieces = re.split(r"([.!?\n])", value)

        for index in range(0, len(pieces), 2):
            part = pieces[index]

            if em_dashes == "asides" and part.count("\u2014") == 2:
                left, aside, right = (
                    section.strip()
                    for section in part.split("\u2014")
                )

                words = re.findall(r"[^\W\d_]+", aside)

                if (
                    left
                    and right
                    and len(words) >= 2
                    and left[-1].isalnum()
                    and right[0].isalpha()
                ):
                    leading = part[:len(part) - len(part.lstrip())]
                    trailing = part[len(part.rstrip()):]

                    replacement = f"{left} ({aside}) {right}"
                    pieces[index] = leading + replacement + trailing

                    changes["paired_asides_converted"] += 1
                    review.append(
                        f"Check inferred aside: {part.strip()!r}"
                        f" -> {replacement!r}"
                    )
                    continue

            if "\u2014" in part:
                review.append(
                    "Em dash retained; choose an explicit rewrite: "
                    f"{part.strip()!r}"
                )

        return "".join(pieces)

    def clean_prose(value):
        # Apply the caller's exact, reviewed sentence edits.
        for before, after in rewrites.items():
            count = value.count(before)

            if count:
                value = value.replace(before, after)
                changes["explicit_rewrites"] += count

        # Normalize line and paragraph separators.
        value, count = re.subn(
            r"\r\n?|\x85|\u2028|\x0b", "\n", value
        )
        changes["line_endings_normalized"] += count

        value, count = re.subn(
            r"[\u2029\x0c]", "\n\n", value
        )
        changes["paragraph_separators_normalized"] += count

        # Target specific formatting characters, not every Unicode Cf.
        for char in REMOVABLE:
            count = value.count(char)

            if count:
                value = value.replace(char, "")
                changes[f"removed_U+{ord(char):04X}"] += count

        count = value.count("\u200b")

        if count and zero_width_spaces != "keep":
            replacement = (
                " " if zero_width_spaces == "space" else ""
            )
            value = value.replace("\u200b", replacement)

            changes["zero_width_spaces_changed"] += count
            review.append(
                "Check word boundaries where zero-width spaces changed."
            )

        if BIDI.search(value):
            if remove_bidi:
                value, count = BIDI.subn("", value)
                changes["directional_controls_removed"] += count
                review.append(
                    "Check the reading order of mixed-direction text."
                )
            else:
                review.append(
                    "Directional controls preserved; "
                    "they can be meaningful."
                )

        value, count = CONTROLS.subn("", value)

        if count:
            changes["control_characters_removed"] += count
            review.append(
                "Check text around removed control characters."
            )

        # Removal may bring combining marks together, so normalize after it.
        # NFKC does NOT fold every cross-script homoglyph.
        if normalization != "none":
            normalized = unicodedata.normalize(normalization, value)

            if normalized != value:
                changes["unicode_spans_normalized"] += 1

                if normalization == "NFKC":
                    review.append(
                        "NFKC used: check superscripts, units, "
                        "and mathematical symbols."
                    )

            value = normalized

        # Convert Unicode space separators to ordinary spaces.
        chars = []

        for char in value:
            if char != " " and unicodedata.category(char) == "Zs":
                chars.append(" ")
                changes["unicode_spaces_normalized"] += 1
            else:
                chars.append(char)

        value = "".join(chars)

        # Preserve leading indentation and trailing Markdown hard breaks.
        value, count = re.subn(
            r"(?<=\S)(?:[ \t]{2,}|\t)(?=\S)",
            " ",
            value,
        )
        changes["interior_whitespace_runs_collapsed"] += count

        # Preserve paragraph breaks.
        value, count = re.subn(
            r"\n(?:[ \t]*\n){2,}",
            "\n\n",
            value,
        )
        changes["excess_blank_line_groups_collapsed"] += count

        return fix_dashes(value)

    output = []

    for block, protected in protected_blocks(text):
        if protected:
            output.append(block)
            continue

        cursor = 0

        for match in INLINE.finditer(block):
            output.append(clean_prose(block[cursor:match.start()]))
            output.append(match[0])
            cursor = match.end()

        output.append(clean_prose(block[cursor:]))

    return CleanupResult(
        text="".join(output),
        changes={
            key: count
            for key, count in changes.items()
            if count
        },
        review=list(dict.fromkeys(review)),
    )


if __name__ == "__main__":
    # Replace this example with your text.
    original = (
        "The prototype—tested yesterday—worked.\n"
        "The test failed—the battery was empty.\n"
        "Technical notation: x², 10–20 V, −5 V.\n"
        "Emoji: 👩‍💻"
    )

    result = sanitize_text(
        original,
        rewrites={
            # Single em dashes can require actual sentence rewrites.
            "The test failed—the battery was empty.":
                "The test failed because the battery was empty."
        },
    )

    print(result.text)
    print("\nChanges:", result.changes)

    if result.review:
        print("\nReview:")
        for item in result.review:
            print("*", item)