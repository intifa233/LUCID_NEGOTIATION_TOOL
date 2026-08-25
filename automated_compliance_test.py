# -*- coding: utf-8 -*-
"""
Automated compliance test: runs full 10-round negotiations against a real OpenAI model
(no human typing) for both Prosocial and Proself, several instances each, and checks
whether the AI negotiator's behavior actually followed prompts.yaml's rules:

  - Round 1: states its opening offer AND asks about the customer's priorities together
             (enforced live via lucid_core's retry loop, same as production - this test
             just reports how many attempts it took).
  - Holds its $300 anchor through round 3 (no concession before round 4).
  - Never exceeds its ceiling ($450 Prosocial / $400 Proself).
  - Offers move monotonically once it starts conceding (no random drops).
  - Doesn't jump straight from $300 to the ceiling in one step.

The "customer" side is played by a separate, cheap model (gpt-4o-mini) with a simple
persona so each instance plays out a little differently. This makes real OpenAI API
calls and costs a small amount of money - not free.

Usage:
    python3 automated_compliance_test.py
    python3 automated_compliance_test.py --instances 5
    python3 automated_compliance_test.py --model gpt-5.6 --instances 3 --rounds 10
"""
import argparse
import json
import os
import re
import sys

import lucid_core as lucid

CUSTOMER_MODEL = 'gpt-4o-mini'  # cheap model plays the human customer side

CUSTOMER_SYSTEM_PROMPT = """You are a customer selling a used laptop (128GB Apple MacBook Air, M1 chip, bought last April for $799, excellent condition, one year of warranty remaining, no water damage) to a buyback agent via chat. You want to get as much money as possible, but you also want to actually close a deal before the conversation ends.

Behave like a real, somewhat impatient negotiator:
- Start by asking for a high price (somewhere around $550-650) or reacting skeptically to a low opening offer.
- Push back on low offers, but gradually move toward the agent's numbers across the conversation.
- Occasionally mention urgency, other reasons for selling, or ask questions about the process.
- By the final couple of rounds, be willing to accept a reasonable offer to close the deal rather than dragging it out forever.
- Keep each message short (1-3 sentences), like a real chat message, not a formal letter.
- Never mention that you are an AI or that this is a simulation."""


def _load_dotenv(path='.env'):
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


def _detect_repeats_priority_question_llm(assistant_reply, api_key):
    """
    Test-only diagnostic (not part of production): does this round-2+ message ask the
    customer a NEW question about what they value most in the sale - the same kind of
    question [ROUND 1 - INFORMATION EXCHANGE] requires exactly once? Deliberately does
    NOT require an offer to also be present (unlike lucid_core's round-1 detector, which
    checks both together) - restating a price is completely normal every round and isn't
    itself a repeat-question signal, so folding that requirement in here previously
    caused false positives (a message merely re-mentioning a price, or acknowledging
    something the customer already said, was getting misclassified as "asking again").

    Fails safe: any error is treated as "did not repeat" (False), so a detector outage
    doesn't manufacture violations that aren't there.
    """
    if not assistant_reply or not assistant_reply.strip():
        return False

    system_prompt = """You are checking whether a message from an AI negotiator asks the customer a NEW question about what they value most in this sale - i.e. explicitly asks whether they care most about getting the highest possible price, a quick/easy sale, or something else (similar to "what matters most to you in this sale?").

The following do NOT count, even if related:
- Restating or mentioning a price (its own or the customer's) - prices come up almost every round and that alone is not a repeat.
- Acknowledging or referencing something the customer already told it (e.g. "I hear that a quick close matters to you") - that's using information already given, not asking again.
- Asking about the laptop's condition, specs, or documentation.
- General closing questions like "does that work for you?" or "shall we finalize?"

Respond in JSON format with:
{
    "asks_about_priorities_again": true/false
}"""

    try:
        resp = lucid._call_openai_chat(
            [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': assistant_reply}],
            'gpt-4o-mini', 0.0, None, api_key, timeout=10, max_tokens=50,
            response_format={'type': 'json_object'}
        )
        if resp.status_code == 200:
            data = json.loads(resp.json()['choices'][0]['message']['content'])
            return bool(data.get('asks_about_priorities_again'))
        print(f"[WARN] repeat-question detector failed ({resp.status_code}): {resp.text[:300]}")
    except (Exception,) as e:
        print(f"[WARN] repeat-question detector error ({type(e).__name__}): {e}")
    return False


def _parse_dollar_amount(offer_value_str):
    """Parses lucid_core.get_turn_offers()'s offer_value strings (e.g. '$300') into an int."""
    if not offer_value_str:
        return None
    match = re.search(r'([\d,]+)', offer_value_str)
    return int(match.group(1).replace(',', '')) if match else None


def run_negotiation(condition_key, model, temperature, max_rounds, instance_label):
    system_prompt = lucid.CONDITION_PROMPTS[condition_key]['initial_prompt']
    ai_messages = [{'role': 'system', 'content': system_prompt}]
    customer_messages = [{'role': 'system', 'content': CUSTOMER_SYSTEM_PROMPT}]

    round1_attempts = None
    round1_complied = None
    ai_offers_by_round = []  # list of (round_number, offer_int_or_None) - None means no NEW offer stated that round
    transcript = []
    rounds_completed = 0  # bumped only after a round's AI reply is successfully generated
    aborted_reason = None  # set if the loop breaks early due to an API failure
    repeat_question_rounds = []  # prosocial only: round numbers (>=2) that re-asked about priorities

    # Customer opens with a vague greeting so round 1 is genuinely the AI's first move
    # (matches how the real chat interface always has the AI speak first via LUCIDIntroMessage,
    # then the customer replies - here we just let the customer send round 1's user turn).
    customer_opening = "Hi, I have a laptop I'd like to sell."
    customer_messages.append({'role': 'assistant', 'content': customer_opening})
    ai_messages.append({'role': 'user', 'content': customer_opening})
    transcript.append(('customer', customer_opening))

    for round_number in range(1, max_rounds + 1):
        has_prior_assistant_reply = any(m.get('role') == 'assistant' for m in ai_messages)
        # The customer message that triggers THIS round's AI reply - always the most
        # recent 'user' entry in ai_messages at this point (the opening line for round 1,
        # otherwise the customer's reply from the end of the previous round).
        latest_customer_text = next(m['content'] for m in reversed(ai_messages) if m['role'] == 'user')

        round_context = f"[SYSTEM CONTEXT: This is round {round_number} out of {max_rounds} in this negotiation.]"
        extra_notes = []
        if condition_key == 'prosocial' and has_prior_assistant_reply:
            extra_notes.append(
                "You already stated your opening offer and asked the customer about "
                "their priorities together in your first message earlier in this "
                "negotiation - do not ask them to restate it again. Move the "
                "negotiation forward on the actual price instead, unless they bring "
                "up something new themselves."
            )
        messages_for_api = ai_messages + [{'role': 'system', 'content': round_context}] + [
            {'role': 'system', 'content': n} for n in extra_notes
        ]

        resp = lucid._call_openai_chat(messages_for_api, model, temperature, api_key=os.environ['OPENAI_API_KEY'], timeout=60)
        if resp.status_code != 200:
            print(f"  [{instance_label}] round {round_number}: OpenAI error {resp.status_code}: {resp.text[:300]}")
            aborted_reason = f"AI call failed at round {round_number} ({resp.status_code})"
            break
        ai_reply = resp.json()['choices'][0]['message']['content']

        if condition_key == 'prosocial' and not has_prior_assistant_reply:
            attempts = 1
            complied = lucid._detect_round1_compliance_llm(ai_reply, os.environ['OPENAI_API_KEY'])
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
                    messages_for_api + [nudge], model, temperature, None, os.environ['OPENAI_API_KEY']
                )
                if retry_text:
                    ai_reply = retry_text
                    complied = lucid._detect_round1_compliance_llm(ai_reply, os.environ['OPENAI_API_KEY'])
                else:
                    break
            round1_attempts = attempts
            round1_complied = complied
        elif condition_key == 'prosocial' and has_prior_assistant_reply:
            # Extra check beyond production's own enforcement: did the "don't ask again"
            # reminder actually work, or did the model re-ask about priorities anyway?
            # Uses a dedicated detector scoped just to "did it ask again" - NOT the round-1
            # detector (which also requires an offer to be present, and restating a price
            # is normal every round; folding that in here previously caused false positives).
            if _detect_repeats_priority_question_llm(ai_reply, os.environ['OPENAI_API_KEY']):
                repeat_question_rounds.append(round_number)

        ai_messages.append({'role': 'assistant', 'content': ai_reply})
        customer_messages.append({'role': 'user', 'content': ai_reply})
        transcript.append(('ai', ai_reply))
        rounds_completed = round_number

        # Same LLM-based extraction production uses (lucid_core.get_turn_offers) - correctly
        # ignores numbers the AI is only quoting back from the customer (e.g. "I understand
        # you want $600, but I have to hold at $300" correctly extracts $300, not $600).
        turn_offers = lucid.get_turn_offers(latest_customer_text, ai_reply)
        assistant_offer = turn_offers['assistant_latest_offer']
        new_price = _parse_dollar_amount(assistant_offer['offer_value']) if assistant_offer['has_offer'] else None
        # Carry forward the last known genuine offer if this round didn't restate one
        # (mirrors the "sticky" display behavior the real chat UI uses), so continuity
        # checks (holds-through-round-3, monotonic, ceiling) still make sense.
        if new_price is None and ai_offers_by_round:
            new_price = ai_offers_by_round[-1][1]
        ai_offers_by_round.append((round_number, new_price))

        if round_number == max_rounds:
            break

        # --- Customer's turn ---
        cust_resp = lucid._call_openai_chat(customer_messages, CUSTOMER_MODEL, 1.0, api_key=os.environ['OPENAI_API_KEY'], timeout=60)
        if cust_resp.status_code != 200:
            print(f"  [{instance_label}] round {round_number}: customer OpenAI error {cust_resp.status_code}")
            aborted_reason = f"customer call failed at round {round_number} ({cust_resp.status_code})"
            break
        customer_reply = cust_resp.json()['choices'][0]['message']['content']
        customer_messages.append({'role': 'assistant', 'content': customer_reply})
        ai_messages.append({'role': 'user', 'content': customer_reply})
        transcript.append(('customer', customer_reply))

    return {
        'condition': condition_key,
        'round1_attempts': round1_attempts,
        'round1_complied': round1_complied,
        'repeat_question_rounds': repeat_question_rounds,
        'rounds_completed': rounds_completed,
        'aborted_reason': aborted_reason,
        'ai_offers_by_round': ai_offers_by_round,
        'transcript': transcript,
    }


def check_compliance(result):
    """Rule-based checks against prompts.yaml's stated behavior. Returns a list of
    (rule_name, passed_bool_or_None, detail_str). passed=None means "inconclusive /
    not applicable" - NOT the same as a pass, and must be excluded from tallies."""
    condition = result['condition']
    ceiling = 450 if condition == 'prosocial' else 400
    anchor = 300
    checks = []

    # Did the run abort early (API failure)? Surfaced as its own check so a broken run
    # can never silently masquerade as "no violations found" in the checks below.
    if result['aborted_reason']:
        checks.append(('completed_without_api_errors', False, result['aborted_reason']))
    else:
        checks.append(('completed_without_api_errors', True, f"OK ({result['rounds_completed']} rounds)"))

    # Round 1: only applicable to Prosocial. Distinguish "proself, doesn't apply" from
    # "prosocial, but we never even got a round-1 reply to check" (e.g. round-1 API call
    # itself failed) - those are different situations and shouldn't share one vague message.
    if condition != 'prosocial':
        checks.append(('round1_offer_and_question', None, 'not applicable (proself has no round-1 requirement)'))
    elif result['round1_complied'] is None:
        checks.append(('round1_offer_and_question', None, f"inconclusive - {result['aborted_reason'] or 'round 1 never completed'}"))
    else:
        checks.append((
            'round1_offer_and_question',
            bool(result['round1_complied']),
            f"complied after {result['round1_attempts']} attempt(s)" if result['round1_complied']
            else f"NEVER complied within {lucid.PROSOCIAL_ROUND1_MAX_ATTEMPTS} attempts"
        ))

    # Round 2+: did Prosocial actually honor "don't ask again"? Not applicable to Proself
    # (no such rule) or to a run that never reached round 2.
    if condition != 'prosocial':
        checks.append(('no_repeat_question', None, 'not applicable (proself has no round-1 requirement)'))
    elif result['rounds_completed'] < 2:
        checks.append(('no_repeat_question', None, 'inconclusive - fewer than 2 rounds completed'))
    else:
        repeats = result['repeat_question_rounds']
        checks.append((
            'no_repeat_question',
            len(repeats) == 0,
            'OK' if not repeats else f"VIOLATED: re-asked about priorities in round(s) {repeats}"
        ))

    # (round_number, price_or_None) pairs, already carry-forward-filled in run_negotiation()
    offers = result['ai_offers_by_round']
    known_prices = [p for _, p in offers if p is not None]

    if not known_prices:
        # No price data at all (e.g. every round's extraction failed, or the run aborted
        # before any AI reply was recorded) - report inconclusive, NOT a pass. all()/any()
        # on an empty list would otherwise vacuously report every check below as "PASS"
        # despite there being nothing to verify - that's the bug this branch exists to avoid.
        reason = f"no price data - {result['aborted_reason'] or 'offer extraction never returned a value'}"
        checks.append(('never_exceeds_ceiling', None, reason))
        checks.append(('holds_anchor_through_round_3', None, reason))
        checks.append(('no_early_jump_to_ceiling', None, reason))
        checks.append(('monotonic_non_decreasing', None, reason))
        return checks

    # Ceiling check
    over_ceiling = [(r, p) for r, p in offers if p is not None and p > ceiling]
    checks.append((
        'never_exceeds_ceiling',
        len(over_ceiling) == 0,
        f"OK (max offer ${max(known_prices)})" if not over_ceiling
        else f"VIOLATED at round(s) {[r for r, _ in over_ceiling]}: {over_ceiling}"
    ))

    # Hold through round 3
    early_offers = [(r, p) for r, p in offers if r <= 3 and p is not None]
    held = all(p == anchor for _, p in early_offers)
    checks.append((
        'holds_anchor_through_round_3',
        held,
        f"OK (rounds 1-3 all at ${anchor})" if held
        else f"VIOLATED: moved off ${anchor} before round 4: {early_offers}"
    ))

    # No direct jump from anchor straight to ceiling
    jumped_to_ceiling_early = any(p == ceiling for r, p in offers if r <= 5 and p is not None)
    checks.append((
        'no_early_jump_to_ceiling',
        not jumped_to_ceiling_early,
        'OK' if not jumped_to_ceiling_early else f"VIOLATED: hit ceiling (${ceiling}) by round 5"
    ))

    # Monotonic non-decreasing once conceding
    monotonic = all(b >= a for a, b in zip(known_prices, known_prices[1:]))
    checks.append((
        'monotonic_non_decreasing',
        monotonic,
        'OK' if monotonic else f"VIOLATED: offers went backwards: {known_prices}"
    ))

    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='gpt-5.6', help='Model under test (the negotiator). Default: gpt-5.6')
    parser.add_argument('--temperature', type=float, default=1.0)
    parser.add_argument('--instances', type=int, default=3, help='Instances per condition. Default: 3')
    parser.add_argument('--rounds', type=int, default=10, help='Round limit. Default: 10')
    parser.add_argument('--conditions', nargs='+', default=['prosocial', 'proself'])
    parser.add_argument('--transcripts', action='store_true', help='Print full transcripts, not just the compliance summary')
    args = parser.parse_args()

    _load_dotenv()
    if not os.getenv('OPENAI_API_KEY'):
        print("No OPENAI_API_KEY found. Put it in .env as OPENAI_API_KEY=sk-... and try again.")
        sys.exit(1)

    print(f"Model under test: {args.model} | temperature={args.temperature} | rounds={args.rounds} | instances/condition={args.instances}\n")

    all_results = []
    for condition in args.conditions:
        for i in range(1, args.instances + 1):
            label = f"{condition} #{i}"
            print(f"=== Running {label} ===")
            result = run_negotiation(condition, args.model, args.temperature, args.rounds, label)
            all_results.append((label, result))

            if args.transcripts:
                for speaker, text in result['transcript']:
                    tag = 'Customer' if speaker == 'customer' else 'AI'
                    print(f"  {tag}: {text}")
                print()

            checks = check_compliance(result)
            for rule, passed, detail in checks:
                status = 'N/A ' if passed is None else ('PASS' if passed else 'FAIL')
                print(f"  [{status}] {rule}: {detail}")
            print()

    # --- Aggregate summary ---
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    tally = {}
    for label, result in all_results:
        for rule, passed, _ in check_compliance(result):
            if passed is None:
                continue
            tally.setdefault(rule, [0, 0])
            tally[rule][1] += 1
            if passed:
                tally[rule][0] += 1
    for rule, (passed_count, total) in tally.items():
        print(f"  {rule}: {passed_count}/{total} instances passed")


if __name__ == '__main__':
    main()
