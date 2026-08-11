"""Keyboard labelling pass over the golden set.

    uv run python -m jmi_evals.label

The golden set is only worth what the labels in it are worth, and the labels
cost a human's reading time. This removes the friction around that reading —
it does not remove the reading.

Two deliberate refusals, both from
:doc:`ADR 0006 </docs/adr/0006-llm-evaluation>`:

* **No suggested label.** Not from a model, not from the IND register, not from
  what production predicted. A suggestion you can accept with one keystroke is
  a suggestion you will accept, and the labels would drift toward whatever
  produced them — measuring agreement instead of accuracy. ``llm_status_at_
  sampling`` is hidden unless you pass ``--show-prediction``, which is for
  reviewing labels you have already made, not for making them.
* **No auto-labelling.** There is no flag for it and there should not be.

What it *does* do is order the queue. Postings whose text actually discusses
the right to work are the ones that carry signal; a proportional walk through
this corpus is mostly postings that say nothing about visas at all, and you
would spend an hour to label almost entirely ``unclear``. Same reason the
sampler stratifies.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from jmi_core.schema import VisaSponsorshipStatus
from jmi_evals.dataset import GOLDEN_SET_PATH, GoldenRecord, load_golden_set, save_golden_set

#: The enum, in rubric order (most positive → most negative), bound to 1-5.
CHOICES: list[VisaSponsorshipStatus] = [
    VisaSponsorshipStatus.EXPLICIT_YES,
    VisaSponsorshipStatus.LIKELY_YES,
    VisaSponsorshipStatus.UNCLEAR,
    VisaSponsorshipStatus.LIKELY_NO,
    VisaSponsorshipStatus.EXPLICIT_NO,
]

#: Vocabulary that means the posting is *discussing* the right to work at all.
#: Used only to order the queue and to highlight — never to infer a label.
_SIGNAL = re.compile(
    r"\b("
    r"visa|visas|sponsor\w*|work permit|working permit|residence permit|"
    r"right to work|work authoriz\w+|work authoris\w+|relocat\w+|"
    r"highly skilled migrant|kennismigrant|blue card|blaue karte|"
    r"eu citizen|eea|work eligibility|immigration|tier 2|skilled worker"
    r")\b",
    re.IGNORECASE,
)


def signal_hits(text: str) -> list[str]:
    """Distinct right-to-work terms the posting uses."""
    return sorted({m.group(0).lower() for m in _SIGNAL.finditer(text or "")})


def triage_order(records: list[GoldenRecord]) -> list[GoldenRecord]:
    """Unlabelled first, richest right-to-work vocabulary first within that.

    Stable on ties so a re-run resumes in the same order.
    """
    unlabelled = [r for r in records if not r.is_labelled]
    return sorted(unlabelled, key=lambda r: -len(signal_hits(r.prompt_input)))


def highlight(text: str) -> str:
    """Bold every right-to-work term so the eye lands on the deciding sentence."""
    return _SIGNAL.sub(lambda m: f"\033[1;33m{m.group(0)}\033[0m", text)


def _excerpt(text: str, *, full: bool, width: int = 2000) -> str:
    body = highlight(text)
    if full or len(text) <= width:
        return body
    # Long ad, no full-text request: keep the head, where the pitch and any
    # "we sponsor" line almost always sit.
    return highlight(text[:width]) + f"\n\033[2m… (+{len(text) - width} chars, press 'f')\033[0m"


def _progress(records: list[GoldenRecord]) -> str:
    done = [r for r in records if r.is_labelled]
    by_class = {c.value: sum(1 for r in done if r.visa_status_true == c) for c in CHOICES}
    spread = "  ".join(f"{k.replace('_', ' ')}:{v}" for k, v in by_class.items())
    return f"{len(done)}/{len(records)} labelled   [{spread}]"


def _render(rec: GoldenRecord, records: list[GoldenRecord], *, full: bool, show_pred: bool) -> None:
    print("\033[2J\033[H", end="")  # clear
    print(f"\033[1m{_progress(records)}\033[0m\n")
    print(f"\033[1m{rec.title or '(no title)'}\033[0m")
    meta = f"{rec.company_name or '(unknown company)'} · {rec.country_code or '—'} · {rec.source}"
    print(f"\033[2m{meta}\033[0m")
    if rec.source_url:
        print(f"\033[2m{rec.source_url}\033[0m")
    hits = signal_hits(rec.prompt_input)
    print(f"\033[2mright-to-work terms: {', '.join(hits) if hits else 'none'}\033[0m")
    if show_pred:
        print(f"\033[2mproduction predicted: {rec.llm_status_at_sampling}\033[0m")
    print("\n" + "─" * 78)
    print(_excerpt(rec.prompt_input, full=full))
    print("─" * 78)
    print(
        "  ".join(f"\033[1m{i + 1}\033[0m {c.value}" for i, c in enumerate(CHOICES))
        + "     \033[1ms\033[0mkip  \033[1mn\033[0mote  \033[1mf\033[0mull  \033[1mq\033[0muit"
    )
    print(
        "\n\033[2mDoes this posting's TEXT state or imply sponsorship? "
        "Not whether the employer could sponsor.\033[0m"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=GOLDEN_SET_PATH)
    parser.add_argument("--limit", type=int, default=None, help="Stop after N labels this session.")
    parser.add_argument(
        "--show-prediction",
        action="store_true",
        help="Reveal what production predicted. For reviewing labels, not making them.",
    )
    args = parser.parse_args()

    records = load_golden_set(args.path)
    queue = triage_order(records)
    if not queue:
        print(f"nothing to label: all {len(records)} rows already have visa_status_true.")
        return

    print(f"{len(queue)} unlabelled of {len(records)}. Ctrl-C or 'q' saves and exits.\n")
    labelled_here = 0
    full = False

    try:
        for rec in queue:
            if args.limit is not None and labelled_here >= args.limit:
                break
            while True:
                _render(rec, records, full=full, show_pred=args.show_prediction)
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
                if key in {"1", "2", "3", "4", "5"}:
                    rec.visa_status_true = CHOICES[int(key) - 1]
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
    print(_progress(records))
    if any(r.is_labelled for r in records):
        print("\nscore it:  uv run python -m jmi_evals.runner --provider replay")


if __name__ == "__main__":
    main()
