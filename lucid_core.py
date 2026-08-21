# -*- coding: utf-8 -*-
"""
Flask-independent negotiation logic shared between lucid.py (the real Flask/Vercel
backend) and local_negotiation_test.py (the terminal test harness).

This exists so local_negotiation_test.py can reuse the exact same prompt-loading,
OpenAI-calling, and Prosocial round-1 compliance logic that production uses - without
needing Flask installed just to run a local chat loop in a terminal. lucid.py imports
everything from here and adds the HTTP/CORS/routing layer on top; nothing in this file
depends on Flask, request, or any web-specific machinery.
"""
import json
import os       # Used for accessing environment variables (API keys) and resolving prompts.yaml's path
import requests # Used for making HTTP requests to the OpenAI API
import yaml     # For loading per-condition negotiation prompts from prompts.yaml

# --- Condition Prompts (prompts.yaml) ---

def _load_condition_prompts():
    """
    Loads prompts.yaml (the per-condition negotiation system prompts) once at import
    time. This lets the Prosocial/Proself prompt text be edited and redeployed
    independently of the Qualtrics .qsf file - no re-import into Qualtrics needed,
    and no risk of breaking anything else in the survey while editing a prompt.

    Returns {} (feature silently disabled, falls back to whatever prompt the
    frontend sends) if the file is missing or malformed, so a bad/missing YAML
    file never takes the whole endpoint down.
    """
    try:
        prompts_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts.yaml')
        with open(prompts_path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        # Normalize condition keys (e.g. "Prosocial" -> "prosocial") for case-insensitive lookup
        return {str(k).strip().lower(): v for k, v in data.items()}
    except Exception as e:
        print(f"[WARN] Could not load prompts.yaml ({type(e).__name__}: {e}). Condition-based prompt override disabled.")
        return {}

CONDITION_PROMPTS = _load_condition_prompts()

# Prosocial-only: cap on how many times we'll regenerate the round-1 reply if it doesn't
# ask the customer about their priorities. Bounded (rather than "retry forever") so a
# persistently non-compliant model can't run the request past Vercel's function timeout -
# each attempt is a real OpenAI call, so 3 attempts is already a few seconds of latency.
PROSOCIAL_ROUND1_MAX_ATTEMPTS = 3

# --- Shared OpenAI call helper ---

def _call_openai_chat(messages, model, temperature, seed=None, api_key=None, timeout=30, max_tokens=None, response_format=None):
    """
    Thin wrapper around a single OpenAI chat-completions call. Returns the raw
    requests.Response (status code + body untouched) so callers keep doing their own
    status/parsing handling exactly as before - this is just here so the request-building
    isn't duplicated between the main /lucid flow and the Prosocial round-1 retry loop
    (and the local test harness, which imports this directly for fidelity with production).
    """
    data_payload = {'model': model, 'messages': messages, 'temperature': temperature}
    if seed is not None:
        data_payload['seed'] = seed
    if max_tokens is not None:
        data_payload['max_tokens'] = max_tokens
    if response_format is not None:
        data_payload['response_format'] = response_format
    return requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        json=data_payload,
        timeout=timeout
    )

def _call_openai_completion_text(messages, model, temperature, seed, api_key):
    """
    Same call as _call_openai_chat, but returns just the generated text (or None if
    anything went wrong: network error, non-200 status, or an unexpected response shape).
    Used for the Prosocial round-1 compliance retry loop, where we only need "did we get
    usable text back" without the full error-response machinery of the main /lucid flow.
    """
    try:
        resp = _call_openai_chat(messages, model, temperature, seed, api_key, timeout=20)
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content']
        print(f"[WARN /lucid] Retry OpenAI call failed ({resp.status_code}): {resp.text[:300]}")
    except (requests.exceptions.RequestException, KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"[WARN /lucid] Retry OpenAI call error ({type(e).__name__}): {e}")
    return None

def _detect_round1_compliance_llm(assistant_reply, api_key):
    """
    Cheap classifier call: does this reply from the Prosocial laptop-buyback agent satisfy
    BOTH requirements of its [ROUND 1 - INFORMATION EXCHANGE] instructions, TOGETHER in
    this one message?
      1. States a concrete opening price offer - a specific dollar amount it's offering.
      2. Actively asks the customer what matters most to them in the sale (highest price
         vs. a quick/easy sale vs. something else). A generic greeting or a question about
         something unrelated (e.g. the laptop's condition) does NOT count as #2.

    Fails safe: any error, or either requirement missing, is treated as non-compliant
    (False), so the retry loop errs toward retrying rather than silently accepting a
    reply that's missing the offer, the question, or both.
    """
    if not assistant_reply or not assistant_reply.strip():
        return False

    system_prompt = """You are checking whether a message from an AI negotiator (a used-laptop buyback agent) satisfies BOTH of the following, together, in this ONE message:
1. States a concrete opening price offer - a specific dollar amount it is offering for the laptop.
2. Actively asks the customer what matters most to them in this sale - e.g. whether they most care about getting the highest possible price, a quick/easy sale, or something else. A generic greeting, or a question about something unrelated (e.g. the laptop's condition or specs), does NOT count as asking about priorities.

Respond in JSON format with:
{
    "states_opening_offer": true/false,
    "asks_about_priorities": true/false
}"""

    try:
        resp = _call_openai_chat(
            [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': assistant_reply}],
            'gpt-4o-mini', 0.0, None, api_key, timeout=10, max_tokens=50,
            response_format={'type': 'json_object'}
        )
        if resp.status_code == 200:
            data = json.loads(resp.json()['choices'][0]['message']['content'])
            return bool(data.get('states_opening_offer')) and bool(data.get('asks_about_priorities'))
        print(f"[WARN /lucid] Round-1 compliance detector failed ({resp.status_code}): {resp.text[:300]}")
    except (requests.exceptions.RequestException, KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"[WARN /lucid] Round-1 compliance detector error ({type(e).__name__}): {e}")
    return False

# --- Offer Extraction ---

def _empty_turn_offer(role, raw_message):
    return {'has_offer': False, 'role': role, 'raw_message': raw_message or '', 'offer_value': ''}

def get_turn_offers(user_message, assistant_message):
    """
    Extracts offers for THIS negotiation turn ONLY, in a single OpenAI call
    that looks at the user message which triggered this request and the
    assistant's brand-new response together. No rule-based fallback and no
    per-side call - one LLM call, one JSON result covering both sides.

    Deliberately ignores the rest of the conversation history, so a round
    where nobody restates a price doesn't "inherit" a stale offer value from
    somewhere earlier in the chat - that side just comes back with
    has_offer=False (and the frontend records 'None' for that turn).
    """
    user_message = user_message or ''
    assistant_message = assistant_message or ''

    result = {
        'user_latest_offer': _empty_turn_offer('user', user_message),
        'assistant_latest_offer': _empty_turn_offer('assistant', assistant_message),
    }

    if not user_message.strip() and not assistant_message.strip():
        return result  # nothing said by either side this turn - skip the call entirely

    openai_api_key = os.getenv('OPENAI_API_KEY') or os.getenv('openai_api_key')
    if not openai_api_key:
        print("[WARN] OpenAI API key not available, cannot extract offers this turn")
        return result

    system_prompt = """You are an expert negotiation analyst. You will be shown the USER's message and the ASSISTANT's message from ONE turn of a negotiation. For each of them independently, determine whether they are proposing a concrete offer/price/counter-offer IN THAT MESSAGE.

Respond in JSON format with:
{
    "user_offer_value": "the single absolute value the USER is proposing in THIS message, formatted like '$450' or '20%'. Use ONLY an amount actually being offered/proposed/countered right now - ignore incidental numbers used only as background context (e.g. an original purchase price, a past cost, a quantity). Empty string if the user's message contains no concrete offer.",
    "assistant_offer_value": "the same, but for the ASSISTANT's message. Empty string if the assistant's message contains no concrete offer."
}

Focus on understanding intent and meaning, not just keyword matching. Consider implicit offers and nuanced language. A message can easily contain no offer at all - don't force a value if none was really proposed."""

    turn_content = (
        f"USER MESSAGE:\n{user_message if user_message.strip() else '(nothing said this turn)'}\n\n"
        f"ASSISTANT MESSAGE:\n{assistant_message if assistant_message.strip() else '(nothing said this turn)'}"
    )

    try:
        response_openai = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {openai_api_key}'
            },
            json={
                'model': 'gpt-4o-mini',  # fast/cheap model for a single lightweight extraction call
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': turn_content}
                ],
                'temperature': 0.0,  # deterministic extraction
                'max_tokens': 150,
                'response_format': {'type': 'json_object'}
            },
            timeout=10
        )

        if response_openai.status_code == 200:
            response_text = response_openai.json()['choices'][0]['message']['content']
            extracted_data = json.loads(response_text)

            user_value = (extracted_data.get('user_offer_value') or '').strip()
            assistant_value = (extracted_data.get('assistant_offer_value') or '').strip()

            result['user_latest_offer'] = {
                'has_offer': bool(user_value), 'role': 'user', 'raw_message': user_message, 'offer_value': user_value
            }
            result['assistant_latest_offer'] = {
                'has_offer': bool(assistant_value), 'role': 'assistant', 'raw_message': assistant_message, 'offer_value': assistant_value
            }
        else:
            print(f"[WARN] OpenAI error extracting offers ({response_openai.status_code}): {response_openai.text}")

    except (json.JSONDecodeError, KeyError, IndexError, requests.exceptions.RequestException) as e:
        print(f"[WARN] Error extracting offers ({type(e).__name__}): {e}")

    return result
