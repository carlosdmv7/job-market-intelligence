"""Keyboard labelling pass over the golden set.

    uv run python -m jmi_evals.label --target english

The golden set is only worth what the labels in it are worth, and the labels
cost a human's reading time. This removes the friction around that reading —
it does not remove the reading.

``--target`` picks which question you are answering (see
:mod:`jmi_evals.targets`). One question per pass on purpose: answering two
things about the same posting is slower and more error-prone than reading the
same posting twice with one question in mind.

Two deliberate refusals, both from
:doc:`ADR 0006 </docs/adr/0006-llm-evaluation>`:

* **No suggested label.** Not from a model, not from the IND register, not from
  what production predicted. A suggestion you can accept with one keystroke is
  a suggestion you will accept, and the labels would drift toward whatever
  produced them — measuring agreement instead of accuracy.
  ``--show-prediction`` exists for reviewing labels you have already made, not
  for making them.
* **No auto-labelling.** There is no flag for it and there should not be.

What it *does* do is order the queue, and highlight the vocabulary that decides
the question you picked. A proportional walk through this corpus is mostly
postings that say nothing relevant at all, and you would spend an hour to label
almost entirely ``unclear``. Same reason the sampler stratifies.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from jmi_core.schema import VisaSponsorshipStatus
from jmi_evals.dataset import (
    GOLDEN_SET_PATH,
    GoldenRecord,
    load_golden_set,
    load_responses,
    save_golden_set,
)
from jmi_evals.targets import DEFAULT_TARGET, TARGETS, EnglishSufficiency, Target

#: Vocabulary that means the posting is *discussing* the right to work at all.
_VISA_SIGNAL = re.compile(
    r"\b("
    r"visa|visas|sponsor\w*|work permit|working permit|residence permit|"
    r"right to work|work authoriz\w+|work authoris\w+|relocat\w+|"
    r"highly skilled migrant|kennismigrant|blue card|blaue karte|"
    r"eu citizen|eea|work eligibility|immigration|tier 2|skilled worker"
    r")\b",
    re.IGNORECASE,
)

#: Vocabulary that means the posting is *saying something about language*. Both
#: the requirement and its absence matter, so this includes the local-language
#: names, the fluency ladder, and the CEFR levels boards love to quote.
_ENGLISH_SIGNAL = re.compile(
    r"\b("
    r"english|engels|englisch|inglés|ingles|"
    r"dutch|nederlands|nederlandse|german|deutsch|duits|french|français|"
    r"spanish|español|swedish|svenska|zweeds|portuguese|português|italian|"
    r"fluent\w*|fluency|native|mother tongue|muttersprache|moedertaal|"
    r"vloeiend|verhandlungssicher|bilingual|proficien\w+|"
    r"language|languages|taal|talen|sprache|idioma|"
    r"[abc][12]\s*level|level\s*[abc][12]|\b[abc][12]\b"
    r")\b",
    re.IGNORECASE,
)

#: Per target: the key bindings, the highlight vocabulary, and the one question
#: the labeller is being asked. The question text is the rubric — it is the only
#: thing standing between a label and a vibe.
_CHOICES: dict[str, list[str]] = {
    "visa": [s.value for s in VisaSponsorshipStatus],
    "english": [e.value for e in EnglishSufficiency],
}
_SIGNALS: dict[str, re.Pattern[str]] = {"visa": _VISA_SIGNAL, "english": _ENGLISH_SIGNAL}
_QUESTIONS: dict[str, str] = {
    "visa": (
        "Does this posting's TEXT state or imply sponsorship? "
        "Not whether the employer could sponsor."
    ),
    "english": (
        "Could someone who speaks English (and Spanish) but NOT the local language "
        "do this job? 'unclear' if the text never says."
    ),
}
_TERM_LABELS: dict[str, str] = {
    "visa": "right-to-work terms",
    "english": "language terms",
}


def signal_hits(text: str, target: str = "visa") -> list[str]:
    """Distinct decision-relevant terms the posting uses, for the given target."""
    pattern = _SIGNALS[target]
    return sorted({m.group(0).lower() for m in pattern.finditer(text or "")})


def triage_order(
    records: list[GoldenRecord],
    *,
    target: Target,
    scoreable: set[str] | None = None,
) -> list[GoldenRecord]:
    """Unlabelled first; within those, the ones a label actually buys a score.

    Two keys, in this order:

    1. **Has a recorded model response.** Only postings the pipeline has already
       enriched can be scored, and the enrichment is quota-bound — most of the
       golden set has no response yet. Ordering by signal alone sent the first
       sitting entirely into unenriched rows: nine labels, nothing scoreable.
    2. **Richest relevant vocabulary** — among equally scoreable postings, the
       ones that actually discuss the question teach the eval more than an ad
       that never raises it.

    Stable on ties so a re-run resumes in the same order.
    """
    unlabelled = [r for r in records if not r.is_labelled_for(target)]
    have_response = scoreable or set()
    return sorted(
        unlabelled,
        key=lambda r: (
            r.content_hash not in have_response,
            -len(signal_hits(r.prompt_input, target.name)),
        ),
    )


def highlight(text: str, target: str = "visa") -> str:
    """Bold every decision-relevant term so the eye lands on the deciding sentence."""
    return _SIGNALS[target].sub(lambda m: f"\033[1;33m{m.group(0)}\033[0m", text)


def _excerpt(text: str, *, full: bool, target: str, width: int = 2000) -> str:
    body = highlight(text, target)
    if full or len(text) <= width:
        return body
    # Long ad, no full-text request: keep the head, where the pitch and any
    # language or sponsorship line almost always sit.
    return (
        highlight(text[:width], target)
        + f"\n\033[2m… (+{len(text) - width} chars, press 'f')\033[0m"
    )


def _progress(records: list[GoldenRecord], target: Target) -> str:
    done = [r for r in records if r.is_labelled_for(target)]
    choices = _CHOICES[target.name]
    by_class = {c: sum(1 for r in done if r.label_for(target) == c) for c in choices}
    spread = "  ".join(f"{k.replace('_', ' ')}:{v}" for k, v in by_class.items())
    return f"[{target.name}] {len(done)}/{len(records)} labelled   [{spread}]"


def _render(
    rec: GoldenRecord,
    records: list[GoldenRecord],
    *,
    target: Target,
    full: bool,
    show_pred: bool,
    scoreable: set[str],
) -> None:
    print("\033[2J\033[H", end="")  # clear
    print(f"\033[1m{_progress(records, target)}\033[0m\n")
    print(f"\033[1m{rec.title or '(no title)'}\033[0m")
    meta = f"{rec.company_name or '(unknown company)'} · {rec.country_code or '—'} · {rec.source}"
    print(f"\033[2m{meta}\033[0m")
    if rec.source_url:
        print(f"\033[2m{rec.source_url}\033[0m")
    hits = signal_hits(rec.prompt_input, target.name)
    label = _TERM_LABELS[target.name]
    print(f"\033[2m{label}: {', '.join(hits) if hits else 'none'}\033[0m")
    # Whether labelling this one actually buys a score today.
    if rec.content_hash in scoreable:
        print("\033[2;32mscoreable now — the classifier has already read this one\033[0m")
    else:
        print("\033[2;33mnot scoreable yet — the pipeline has not enriched this one\033[0m")
    if show_pred:
        print(f"\033[2mproduction predicted (visa): {rec.llm_status_at_sampling}\033[0m")
    print("\n" + "─" * 78)
    print(_excerpt(rec.prompt_input, full=full, target=target.name))
    print("─" * 78)
    keys = "  ".join(f"\033[1m{i + 1}\033[0m {c}" for i, c in enumerate(_CHOICES[target.name]))
    print(
        keys + "     \033[1ms\033[0mkip  \033[1mn\033[0mote  \033[1mf\033[0mull  \033[1mq\033[0muit"
    )
    print(f"\n\033[2m{_QUESTIONS[target.name]}\033[0m")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=GOLDEN_SET_PATH)
    parser.add_argument(
        "--target",
        choices=sorted(TARGETS),
        default=DEFAULT_TARGET,
        help="which question to answer this pass (default: %(default)s)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after N labels this session.")
    parser.add_argument(
        "--show-prediction",
        action="store_true",
        help="Reveal what production predicted. For reviewing labels, not making them.",
    )
    args = parser.parse_args()

    target = TARGETS[args.target]
    choices = _CHOICES[target.name]
    accepted = {str(i + 1) for i in range(len(choices))}

    records = load_golden_set(args.path)
    scoreable = set(load_responses())
    queue = triage_order(records, target=target, scoreable=scoreable)
    if not queue:
        print(f"nothing to label: all {len(records)} rows already have {target.truth_field}.")
        return

    print(f"{len(queue)} unlabelled of {len(records)} for '{target.name}'. 'q' saves and exits.\n")
    labelled_here = 0
    full = False

    try:
        for rec in queue:
            if args.limit is not None and labelled_here >= args.limit:
                break
            while True:
                _render(
                    rec,
                    records,
                    target=target,
                    full=full,
                    show_pred=args.show_prediction,
                    scoreable=scoreable,
                )
                try:
                    key = input("> ").strip().lower()
                except EOFError:
                    key = "q"

                if key == "q":
                    raise KeyboardInterrupt
                if key == "f":
                    full = True
                    continue
                if key == "s":
                    full = False
                    break
                if key == "n":
                    rec.notes = input("note: ").strip()
                    save_golden_set(records, args.path)
                    continue
                if key in accepted:
                    setattr(rec, target.truth_field, choices[int(key) - 1])
                    # Save every label: an hour of reading must never be lost
                    # to a closed terminal.
                    save_golden_set(records, args.path)
                    labelled_here += 1
                    full = False
                    break
    except KeyboardInterrupt:
        pass

    save_golden_set(records, args.path)
    print(f"\n\nsaved {args.path}")
    print(_progress(records, target))
    if any(r.is_labelled_for(target) for r in records):
        print(
            "\nscore it:  uv run python -m jmi_evals.runner "
            f"--provider replay --target {target.name}"
        )


if __name__ == "__main__":
    main()
