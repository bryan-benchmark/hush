"""Regression: VL-style uncertain+sports why must rescue to program."""

from .farm_draft import apply_common_sense


def test_vl_uncertain_basketball_why_rescues_program() -> None:
    draft = {
        "bucket": "uncertain",
        "kind": "unknown",
        "confidence": "high",
        "why": (
            "The video shows a basketball game with players on the court "
            "and a scoreboard, indicating it is a sports broadcast."
        ),
    }
    # ASR like the Pluto CBS Sports HQ clip — no literal "basketball" word.
    text = (
        "Lakers up 9. Luca with 8 assists in the first half. Mid third. "
        "Step back triple. Finished with the game high 32."
    )
    out = apply_common_sense(draft, text, "")
    assert out["bucket"] == "program", out
    assert "rescued" in str(out.get("why") or ""), out


def test_nba_asr_alone_rescues_program() -> None:
    draft = {
        "bucket": "uncertain",
        "kind": "unknown",
        "confidence": "low",
        "why": "unclear",
    }
    text = "Lakers up 9. Luca with 8 assists in the first half. Mid third."
    out = apply_common_sense(draft, text, "")
    assert out["bucket"] == "program", out


if __name__ == "__main__":
    test_vl_uncertain_basketball_why_rescues_program()
    test_nba_asr_alone_rescues_program()
    print("ok")
