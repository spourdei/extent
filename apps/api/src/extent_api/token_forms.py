"""Conservative token inflection helpers for lexical matching."""

from __future__ import annotations


def conservative_token_forms(token: str) -> frozenset[str]:
    """Keep the exact token and add only mechanically plausible singular forms."""

    normalized = token.casefold()
    forms = {normalized}
    if not normalized.isalpha():
        return frozenset(forms)
    if len(normalized) <= 3:
        if (
            len(normalized) == 3
            and normalized.endswith("s")
            and normalized not in {"as", "is", "us"}
            and normalized[-2] not in "aeiou"
        ):
            forms.add(normalized[:-1])
        return frozenset(forms)
    if normalized.endswith("ies") and len(normalized) > 4:
        forms.add(f"{normalized[:-3]}y")
        return frozenset(forms)
    if normalized.endswith("es") and len(normalized) > 4:
        forms.add(normalized[:-1])
        if normalized.endswith(("sses", "xes", "zes", "ches", "shes", "ses")):
            shortened = normalized[:-2]
            if len(shortened) > 2:
                forms.add(shortened)
        return frozenset(forms)
    if normalized.endswith("s") and not normalized.endswith(("ss", "is", "us", "ws")):
        forms.add(normalized[:-1])
    return frozenset(forms)


def inflected_search_forms(token: str) -> tuple[str, ...]:
    """Return exact, singular, and regular plural forms in deterministic order."""

    normalized = token.casefold()
    forms = set(conservative_token_forms(normalized))
    singular_bases = {form for form in forms if len(form) < len(normalized)}
    plural_bases = singular_bases or ({normalized} if not normalized.endswith("ws") else set())
    for base in plural_bases:
        if len(base) < 2 or not base.isalpha() or base in {"as", "is", "us"}:
            continue
        if base.endswith("y") and len(base) > 2 and base[-2] not in "aeiou":
            forms.add(f"{base[:-1]}ies")
        elif base.endswith(("s", "x", "z", "ch", "sh")):
            forms.add(f"{base}es")
        else:
            forms.add(f"{base}s")
    equivalent = {
        form
        for form in forms
        if conservative_token_forms(normalized) & conservative_token_forms(form)
    }
    return (normalized, *sorted(equivalent - {normalized}))


def is_likely_plural(token: str) -> bool:
    """Report morphology only when a distinct conservative singular form exists."""

    return len(conservative_token_forms(token)) > 1


def tokens_equivalent(left: str, right: str) -> bool:
    """Match exact tokens or intersecting conservative inflection forms."""

    return bool(conservative_token_forms(left) & conservative_token_forms(right))
