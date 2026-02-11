"""
Script Engine — AI script generation with embedded pitch drop markers.

Pitch drops are decided at script-writing time and baked into the JSON output,
eliminating the need for a separate Claude API call after voice generation.
"""

import json
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class PitchDrop(BaseModel):
    """A single pitch drop marker — a phrase to be pitch-shifted in the final audio."""
    phrase: str = Field(description="The exact phrase (1-3 words) to pitch-shift, must appear verbatim in full_script")
    semitones: int = Field(description="Pitch shift in semitones, negative = deeper (-3 to -6 typical)")


class ScriptBeat(BaseModel):
    """A single beat/moment in the script."""
    line: str = Field(description="The spoken line for this beat")
    type: str = Field(description="One of: hook, observation, joke, punchline, callback, wrap")
    estimated_seconds: float = Field(description="Estimated read time in seconds for this line")
    energy: str = Field(description="One of: high, medium, low — delivery energy level")


class GeneratedScript(BaseModel):
    """Full structured script for a short-form video, with pitch drop markers."""
    title: str = Field(description="Internal title/label for this script")
    topic: str = Field(description="The core topic or premise")
    hook: str = Field(description="The opening hook line (first 1-2 seconds)")
    beats: list[ScriptBeat] = Field(description="Ordered list of script beats")
    final_punchline: str = Field(description="The closing punchline or wrap line")
    full_script: str = Field(description="The complete script as one block of text")
    word_count: int = Field(description="Total word count of full_script")
    estimated_duration_seconds: float = Field(description="Estimated total read time")
    tone: str = Field(description="The overall tone, e.g. 'sarcastic', 'unhinged', 'deadpan'")
    target_audience: str = Field(description="Primary audience demographic")
    hashtag_suggestions: list[str] = Field(description="3-5 suggested hashtags")
    pitch_drops: list[PitchDrop] = Field(
        default=[],
        description="3-6 phrases to pitch-shift for comedic emphasis (punchlines, shocking words)"
    )


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SCRIPT_SYSTEM_PROMPT = """\
You are a viral short-form video scriptwriter specializing in \
TikTok and YouTube Shorts rant-style content. You write scripts that feel like \
someone ranting to their friend — raw, unfiltered, and painfully relatable.

## YOUR STYLE RULES:
- First line MUST be an irresistible hook that stops the scroll. Use patterns like:
  "Why does nobody talk about...", "I need to address something...",
  "Can we agree that...", "The fact that...", "I'm sorry but..."
- Every 2-3 lines, deliver a NEW mini-punchline, observation, or escalation
- Use Gen Z language naturally (not forced): "lowkey", "no because", "the way that",
  "literally", "I cannot", "it's giving", "tell me why", "like???"
- Write how people TALK, not how they write. Use fragments. Interruptions. Tangents.
- Build energy — start strong, escalate in the middle, land the punchline
- Final line should be a mic-drop moment OR a relatable callback
- NEVER be preachy, educational, or corporate-sounding
- Scripts should be 100-170 words (the final video plays at 1.2x speed, so aim for
  ≤40 seconds of final video duration — roughly 48 seconds of normal-speed read time)
- Every single line should make someone think "LITERALLY" or "wait that's so true"

## STRUCTURE (mandatory):
1. HOOK (1 line) — stops the scroll, creates curiosity or instant agreement
2. SETUP (1-2 lines) — establishes the premise, builds context
3. ESCALATION (3-5 lines) — rapid-fire observations, each one funnier/more relatable
4. PUNCHLINE (1 line) — the peak moment, biggest laugh or hardest-hitting truth
5. WRAP (0-1 lines) — optional callback or "anyway..." style exit

## PITCH DROPS (mandatory):
Pick 3-6 phrases from your script that should be pitch-dropped for comedic emphasis.
These are words/phrases that will be made deeper in the final audio for dramatic effect.

Rules for picking pitch drops:
- Choose punchline words, shocking claims, or absurd exaggerations
- Each phrase should be 1-3 words that appear EXACTLY in full_script
- Space them at least 2 seconds apart (don't cluster them)
- Use semitones between -3 and -6 (-4 is standard, -5/-6 for extra dramatic)
- The LAST punchline should usually get the deepest drop
- Good candidates: profanity, hyperbole, brand names used comedically, callback words

Examples of good pitch drops:
  {"phrase": "war crime", "semitones": -4}
  {"phrase": "emotional damage", "semitones": -5}
  {"phrase": "federal offense", "semitones": -4}
  {"phrase": "uninstalled life", "semitones": -6}

## WHAT MAKES CONTENT VIRAL:
- Specificity beats generality ("the 11:47pm homework panic" > "doing homework late")
- Shared experiences nobody has named yet
- Hyperbole that feels true
- The rhythm of stand-up comedy — setup, twist, payoff
- Making the viewer feel SEEN

## OUTPUT FORMAT:
Always return a structured JSON matching the provided schema exactly.
Include the pitch_drops array with 3-6 entries.\
"""


# ---------------------------------------------------------------------------
# Script Generation (Claude)
# ---------------------------------------------------------------------------

def generate_script_claude(
    topic: str,
    style_notes: str = "",
    past_performance_context: str = "",
    temperature: float = 0.85,
) -> GeneratedScript:
    """
    Generate a script using the Anthropic Claude API with structured outputs.
    Returns a GeneratedScript with embedded pitch_drops.
    """
    import anthropic

    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var

    user_prompt = f"Write a viral short-form video script about: {topic}"
    if style_notes:
        user_prompt += f"\n\nStyle notes: {style_notes}"
    if past_performance_context:
        user_prompt += f"\n\nContext from past performance data:\n{past_performance_context}"

    response = client.beta.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        temperature=temperature,
        betas=["structured-outputs-2025-11-13"],
        system=SCRIPT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format={
            "type": "json_schema",
            "json_schema": {
                "name": "generated_script",
                "strict": True,
                "schema": GeneratedScript.model_json_schema(),
            },
        },
    )
    result = json.loads(response.content[0].text)
    return GeneratedScript(**result)


def generate_script_openai(
    topic: str,
    style_notes: str = "",
    past_performance_context: str = "",
    temperature: float = 0.85,
) -> GeneratedScript:
    """
    Generate a script using the OpenAI API with structured outputs.
    Returns a GeneratedScript with embedded pitch_drops.
    """
    from openai import OpenAI

    client = OpenAI()  # Uses OPENAI_API_KEY env var

    user_prompt = f"Write a viral short-form video script about: {topic}"
    if style_notes:
        user_prompt += f"\n\nStyle notes: {style_notes}"
    if past_performance_context:
        user_prompt += f"\n\nContext from past performance data:\n{past_performance_context}"

    response = client.responses.parse(
        model="gpt-4o-2024-08-06",
        temperature=temperature,
        input=[
            {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        text_format=GeneratedScript,
    )
    return response.output_parsed
