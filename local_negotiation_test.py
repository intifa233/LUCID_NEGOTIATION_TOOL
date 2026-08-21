# -*- coding: utf-8 -*-
"""
Standalone local test harness for the LUCID laptop-buyback prompts (prompts.yaml).

Lets you chat with the Prosocial or Proself buyback agent AI directly from the terminal,
without needing Flask, Vercel, or Qualtrics running. Reuses the exact same round-number
injection and Prosocial round-1 "offer + ask about priorities" enforcement (detect +
regenerate-until-compliant) as lucid.py's real /lucid endpoint, so behavior here is
faithful to production. Skips everything that's only for data collection - no offer
extraction, no Embedded Data. This is purely for eyeballing "does the prompt actually
behave the way we designed it" - nothing here is saved anywhere.

Single-issue specifics (this is the difference from the multi-issue project's version of
this script): Prosocial's prompt has a [ROUND 1 - INFORMATION EXCHANGE] section requiring
its very first reply to state its opening offer AND ask the customer what matters most to
them in the sale, together in the same message. There's no per-issue hold-firm/first-
concession logic here (that's a multi-issue concept) - just a single one-time compliance
gate on round 1: if the model's first draft is missing the offer, the question, or both,
this script (like lucid.py) regenerates it (up to PROSOCIAL_ROUND1_MAX_ATTEMPTS times)
rather than ever showing you a non-compliant round-1 reply. From round 2 onward, a
reminder note tells the model not to ask again - matching lucid.py exactly.

Setup:
    1. Put your OpenAI API key in .env (already gitignored):
           OPENAI_API_KEY=sk-...
    2. Run:
           python3 local_negotiation_test.py
    3. Pick a condition, then type customer messages. Type "quit" to stop.

Optional env vars (set in .env or the shell):
    LUCID_TEST_MODEL         - defaults to gpt-4o (matches lucid.py's default)
    LUCID_TEST_TEMPERATURE   - defaults to 1.0 (matches lucid.py's default)
"""
import os
import sys

# lucid_core has all the reusable business logic (prompt loading, OpenAI calls, the
# round-1 detector) with no Flask dependency, unlike lucid.py itself (which is the Flask
# app and would require Flask to be installed just to import). Aliased to `lucid` so the
# rest of this script reads identically to lucid.py's own internals.
import lucid_core as lucid


def _load_dotenv(path='.env'):
    """Minimal .env loader (KEY=VALUE per line) - avoids adding python-dotenv as a
    dependency just for this local test script. Does not override already-set env vars."""
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def main():
    _load_dotenv()
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("No OPENAI_API_KEY found. Put it in .env as OPENAI_API_KEY=sk-... and try again.")
        sys.exit(1)

    model = os.getenv('LUCID_TEST_MODEL', 'gpt-4o')
    temperature = float(os.getenv('LUCID_TEST_TEMPERATURE', '1.0'))

    conditions = sorted(lucid.CONDITION_PROMPTS.keys())
    if not conditions:
        print("prompts.yaml didn't load any conditions - check the file and try again.")
        sys.exit(1)

    print(f"Available conditions: {', '.join(conditions)}")
    condition_key = ''
    while condition_key not in conditions:
        condition_key = input("Which condition? ").strip().lower()

    system_prompt = lucid.CONDITION_PROMPTS[condition_key].get('initial_prompt', '')
    messages = [{'role': 'system', 'content': system_prompt}]

    turn_number = 0

    print(f"\n--- Testing '{condition_key}' (model={model}, temperature={temperature}) ---")
    print("Type a customer message and press Enter. Type 'quit' to stop.\n")

    while True:
        try:
            user_message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEnding session.")
            break
        if user_message.lower() in ('quit', 'exit'):
            break
        if not user_message:
            continue

        messages.append({'role': 'user', 'content': user_message})
        turn_number += 1

        # --- Same round-number note as lucid.py's /lucid endpoint ---
        round_context = f"[SYSTEM CONTEXT: This is round {turn_number} of this negotiation.]"

        # --- Same "has round 1 already happened" check as lucid.py's /lucid endpoint:
        # derived from message history (is there already an assistant reply?), not a
        # local variable, so this stays faithful to how production has to do it (no
        # server-side session state persists across requests there). ---
        has_prior_assistant_reply = any(m.get('role') == 'assistant' for m in messages)
        extra_system_notes = []
        if condition_key == 'prosocial' and has_prior_assistant_reply:
            extra_system_notes.append(
                "You already stated your opening offer and asked the customer about "
                "their priorities together in your first message earlier in this "
                "negotiation - do not ask them to restate it again. Move the "
                "negotiation forward on the actual price instead, unless they bring "
                "up something new themselves."
            )

        messages_for_api = messages + [{'role': 'system', 'content': round_context}] + [
            {'role': 'system', 'content': note} for note in extra_system_notes
        ]

        try:
            resp = lucid._call_openai_chat(messages_for_api, model, temperature, api_key=api_key, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
            reply = resp.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"  [error calling OpenAI: {e}]")
            continue

        # --- Same Prosocial round-1 compliance enforcement as lucid.py's /lucid endpoint:
        # the first reply MUST state the opening offer AND ask about the customer's
        # priorities, together, or it never reaches you - regenerate (up to
        # PROSOCIAL_ROUND1_MAX_ATTEMPTS times) until it does. ---
        if condition_key == 'prosocial' and not has_prior_assistant_reply:
            attempts = 1
            complied = lucid._detect_round1_compliance_llm(reply, api_key)
            print(f"  [round-1 compliance check: {'offer + question both present' if complied else 'missing offer and/or question - regenerating'}]")
            while not complied and attempts < lucid.PROSOCIAL_ROUND1_MAX_ATTEMPTS:
                attempts += 1
                nudge = {
                    'role': 'system',
                    'content': (
                        "Your previous draft reply did not clearly state your opening offer AND "
                        "ask the customer what matters most to them in this sale, together in the "
                        "same message. Rewrite your reply so it does both, per your "
                        "[ROUND 1 - INFORMATION EXCHANGE] instructions, before anything else."
                    )
                }
                retry_text = lucid._call_openai_completion_text(
                    messages_for_api + [nudge], model, temperature, None, api_key
                )
                if retry_text:
                    reply = retry_text
                    complied = lucid._detect_round1_compliance_llm(reply, api_key)
                    print(f"  [retry {attempts}/{lucid.PROSOCIAL_ROUND1_MAX_ATTEMPTS}: {'offer + question both present' if complied else 'still missing offer and/or question'}]")
                else:
                    print("  [retry call failed - keeping previous draft]")
                    break
            if not complied:
                print(f"  [gave up after {attempts} attempt(s) - sending best available reply anyway]")

        messages.append({'role': 'assistant', 'content': reply})
        print(f"\nAI (round {turn_number}): {reply}\n")


if __name__ == '__main__':
    main()
