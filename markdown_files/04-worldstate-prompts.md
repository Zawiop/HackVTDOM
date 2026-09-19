# Function: getWorldStatePrompt

## Purpose
Map a UI selection to the actual text prompt sent to image generation (step 05). No external service — this is pure backend logic — but it's specified separately because it's the piece that makes output consistent across every building and every user, and because it's what technically satisfies the spec line "describe desired changes with an AI prompt."

## Cost / auth
None. No external call.

## Contract
Frontend sends an enum:
```
"reclaimed" | "flooded" | "scorched" | "buried" | "petrified"
```
Backend maps each to a full, pre-written scene description tuned to Scorched Nebraska's reference art — moss/ivy overgrowth, cracked concrete, god rays, a muted amber-green palette, written out as a complete descriptive paragraph, not a short tag. Keep these five strings server-side so output stays consistent regardless of which building or user triggers them; do not let the frontend send raw prompt text for the preset path.

## Override path (the part that actually satisfies the spec)
One optional freeform text field lets the user type their own description, which **replaces** the locked string for that single generation rather than appending to it. This is the literal fulfillment of "describe desired changes with an AI prompt" — the five locked buttons alone are a UI convenience, not technically that spec line, since the user isn't the one describing anything when using them.

## Framing note (copy/UI decision, not a code change)
Present this as a "World State" spectrum — Present ↔ Collapsed — rather than "pick a filter." Same five backend strings, same code path, but it reframes the feature as world-building rather than image-filtering, which matters for how a Procedura judge reads it.

## Output of this function
A single string: either the matched preset description or the user's freeform override. That string is what gets passed into step 05 as the edit instruction, together with the source photo from step 03.
