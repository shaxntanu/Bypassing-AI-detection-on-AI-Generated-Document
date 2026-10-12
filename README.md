# Unicode-Aware Text Sanitizer

This repository contains a small, dependency-free Python utility for conservatively cleaning prose. It normalizes selected Unicode and whitespace characters, applies optional exact text replacements, and reports both the changes it made and cases that need human review.

The repository name reflects its original project context. The included code does not identify AI-generated writing, attempt to evade AI detectors, or guarantee grammar or detector outcomes.

## What it does

`text_sanitizer.py` exposes `sanitize_text(text, ...)`, which returns a `CleanupResult` with three fields:

- `text`: the cleaned string.
- `changes`: counts of the changes made, keyed by change type.
- `review`: deduplicated notes for edits or text that should be checked by a person.

The sanitizer processes prose while preserving common Markdown and URL spans. It leaves fenced code blocks, indented code, inline backtick spans, HTTP(S) URLs, and `www.` URLs unchanged. It is a lightweight span recognizer, not a complete Markdown or HTML parser.

For unprotected prose, it can:

- Apply exact caller-supplied replacements from a `rewrites` mapping.
- Normalize line endings and paragraph separators.
- Remove soft hyphens, byte-order marks, and word joiners while preserving characters such as emoji joiners and variation selectors.
- Remove, replace with a regular space, or keep zero-width spaces.
- Preserve bidirectional text controls by default and report them for review, or remove them when explicitly requested and add a reading-order review note.
- Remove selected control characters and normalize Unicode space separators.
- Apply NFC (the default), NFKC, or no Unicode normalization. If NFKC changes compatibility characters such as superscripts, the result includes a review note.
- Collapse repeated interior whitespace and excessive blank lines without removing leading indentation or Markdown hard-break spaces.
- Convert a conservative, likely paired em-dash aside into parentheses. Other em dashes are retained and flagged for review.

The function validates its options and raises `TypeError` for non-string input or `ValueError` for unsupported options and malformed rewrite mappings. It reads and writes no files. The example at the bottom of the script prints a demonstration and its change/review summaries when run directly.

## Requirements

- Python 3.7 or newer
- Python standard library only

## Use it as a module

```python
from text_sanitizer import sanitize_text

result = sanitize_text(
    "The prototype—tested yesterday—worked.\n"
    "The test failed—the battery was empty.\n"
    "Technical notation: x², 10–20 V, −5 V.\n"
    "Emoji: 👩‍💻",
    normalization="NFC",
    em_dashes="asides",
    zero_width_spaces="remove",
    remove_bidi=False,
    rewrites={
        "The test failed—the battery was empty.":
            "The test failed because the battery was empty."
    },
)

print(result.text)
print(result.changes)
for note in result.review:
    print("Review:", note)
```

All keyword options are optional. Their defaults are shown above. For the precise behavior and limits of each option, see the `sanitize_text` docstring in [`text_sanitizer.py`](text_sanitizer.py).

To run the built-in demonstration:

```console
python text_sanitizer.py
```

## Processing flow

The utility validates its inputs, separates protected Markdown/code/URL spans from prose, and applies the configured cleanup steps only to prose. It returns the resulting text alongside a compact audit trail; review notes identify potentially meaning-sensitive transformations.

[Open the interactive Archify diagram](.archify/architecture-text-sanitizer-20261012-214412/text-sanitizer.html) · [View its editable diagram source](.archify/architecture-text-sanitizer-20261012-214412/candidate.json)

## Limitations

- It is not a grammar checker, style rewriter, plagiarism checker, authorship classifier, or AI-detector bypass tool.
- Markdown protection covers common code fences, indented code, inline backticks, and simple URL patterns; it does not parse every Markdown extension or HTML construct.
- Cleanup can change meaning or word boundaries. Review the returned notes and inspect the text before using it, especially after NFKC normalization, zero-width-space changes, or removal of directional controls.
- A returned change count records what this function changed; it does not certify that the result is correct or appropriate.
