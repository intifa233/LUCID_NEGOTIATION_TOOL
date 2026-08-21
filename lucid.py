# -*- coding: utf-8 -*-
"""
Flask backend server for the LUCID Qualtrics chat interface.

Acts as a proxy between the Qualtrics frontend JavaScript and the OpenAI API.
Handles CORS, fetches configuration from environment variables, makes API calls,
and returns responses. Includes a root endpoint to display deployment status
and the necessary Qualtrics URL.
"""
from flask import Flask, request, jsonify, make_response
import json
import os      # Used for accessing environment variables (API keys, config)
import requests # Used for making HTTP requests to the OpenAI API
import html

# All prompt-loading, OpenAI-calling, and offer/round-1-compliance logic lives in
# lucid_core.py (no Flask dependency), so local_negotiation_test.py can reuse it without
# needing Flask installed. This file is just the HTTP/CORS/routing layer on top.
from lucid_core import (
    CONDITION_PROMPTS,
    PROSOCIAL_ROUND1_MAX_ATTEMPTS,
    _call_openai_chat,
    _call_openai_completion_text,
    _detect_round1_compliance_llm,
    get_turn_offers,
)

# Initialize the Flask application
app = Flask(__name__)

# --- Configuration & CORS ---

def get_allowed_origins_config():
    """
    Reads the ALLOWED_ORIGINS environment variable and parses it into a list.
    Defaults to allowing all origins ('*') if the variable is not set.
    Uses print for logging and visible in Vercel Function Logs.
    """
    origins_str = os.getenv('ALLOWED_ORIGINS')
    print(f"[DEBUG ENV] Raw ALLOWED_ORIGINS: '{origins_str}'") # Vercel Log

    if not origins_str:
        # Default to wildcard if environment variable is missing or empty
        print("[WARN ENV] ALLOWED_ORIGINS not set. Defaulting CORS to allow all ('*').") # Vercel Log
        return ['*']

    # Parse comma-separated list, removing empty strings and stripping whitespace
    allowed_list = [origin.strip() for origin in origins_str.split(',') if origin.strip()]
    print(f"[DEBUG ENV] Parsed ALLOWED_ORIGINS: {allowed_list}") # Vercel Log
    return allowed_list

@app.before_request
def handle_preflight():
    """
    Handles CORS preflight (OPTIONS) requests specifically for the /lucid endpoint.
    Checks the request's Origin header against the ALLOWED_ORIGINS config
    and returns appropriate CORS headers if allowed, or a 403 if denied.
    Echoes back requested headers. Only adds 'Access-Control-Allow-Credentials'
    when needed and with the value 'true'.
    """
    # Intercept only OPTIONS requests targetting the main API endpoint
    # UPDATED: Changed request.method.upper() == 'OPTIONS' to request.method == 'OPTIONS' (Flask normalizes it)
    if request.method == 'OPTIONS' and request.path == '/lucid':
        print(f"[INFO] Intercepting OPTIONS request for {request.path}") # Vercel Log
        origin = request.headers.get('Origin') # Get the origin of the requesting domain
        allowed_origins = get_allowed_origins_config() # Fetch the configured allowed origins

        print(f"[DEBUG PREFLIGHT] Request Origin: '{origin}'") # Vercel Log
        print(f"[DEBUG PREFLIGHT] Checking against Allowed: {allowed_origins}") # Vercel Log

        ac_allow_origin = None # Initialize
        send_credentials = False # Initialize

        # ---- decide origin & credentials ------------------------
        if '*' in allowed_origins:
            ac_allow_origin = '*'
            send_credentials = False        # wildcard ⇒ no creds
            print("[DEBUG PREFLIGHT] Policy: Allowed Wildcard (*), Credentials False") # Vercel Log
        elif origin and origin in allowed_origins: # Added check for origin existence
            ac_allow_origin = origin
            send_credentials = True
            print(f"[DEBUG PREFLIGHT] Policy: Allowed Specific Origin ({origin}), Credentials True") # Vercel Log
        else:
            # Origin not allowed by configuration
            print(f"[WARN] Preflight origin '{origin}' denied by policy for /lucid.") # Vercel Log
            return make_response('Origin not permitted for CORS preflight', 403)

        # ---- echo back ALL requested headers --------------------
        # Retrieve the headers the browser wants to send in the actual request
        req_hdrs = request.headers.get(
            'Access-Control-Request-Headers', ''
        )  # e.g. "X-Requested-With,Content-Type" or just "Content-Type" etc.
        print(f"[DEBUG PREFLIGHT] Access-Control-Request-Headers received: '{req_hdrs}'") # Vercel Log

        # Construct the response for the preflight request (204 No Content)
        res = make_response('', 204)

        # Build the core CORS headers
        cors_headers = {
            'Access-Control-Allow-Origin': ac_allow_origin,
            'Access-Control-Allow-Methods': 'POST, OPTIONS', # Allowed methods for the actual request
            # Allow the headers the browser requested, default to Content-Type if none specified
            'Access-Control-Allow-Headers': req_hdrs if req_hdrs else 'Content-Type',
            'Access-Control-Max-Age': '86400' # Cache preflight response for 1 day
        }

        # --- Add Allow-Credentials header ONLY if needed and with value 'true' ---
        if send_credentials:
            cors_headers['Access-Control-Allow-Credentials'] = 'true'
            print("[DEBUG PREFLIGHT] Adding Access-Control-Allow-Credentials: true") # Vercel Log
        else:
             print("[DEBUG PREFLIGHT] Not adding Access-Control-Allow-Credentials header") # Vercel Log

        # Update response headers
        res.headers.update(cors_headers)

        print(f"[INFO] Preflight OK for /lucid. Sending 204 with headers: {dict(res.headers)}") # Vercel Log
        return res

    # If not an OPTIONS request for /lucid, proceed to the actual route function
    pass

# --- Application Routes ---

@app.route('/')
def hello_world():
    """
    Root endpoint (/). Primarily serves as a status check and provides a helpful
    HTML page displaying the correct URL needed for the Qualtrics setup,
    if deployed on Vercel (detects via VERCEL_URL env var).
    Also handles basic CORS headers for GET requests to the root.
    """
    print("[INFO] Root route '/' accessed.") # Vercel Log
    origin = request.headers.get('Origin')
    allowed_origins = get_allowed_origins_config()

    # Attempt to get the Vercel deployment URL from environment variables
    # --- Determine the correct backend URL using the incoming request context ---
    backend_url_for_qualtrics = "[Error determining backend URL from request]" # Default/fallback
    backend_url_base = "Unknown"
    try:
        # request.url_root gives "scheme://host:port/" - reflects how user accessed page
        # Strip the trailing '/' and append our specific endpoint path.
        backend_url_base = request.url_root.rstrip('/')
        backend_url_for_qualtrics = f"{backend_url_base}/lucid"
        backend_url_for_qualtrics = html.escape(backend_url_for_qualtrics) # Escape for safety
        print(f"[DEBUG URL] Derived base from request.url_root: {backend_url_base}")
        print(f"[DEBUG URL] Constructed Backend URL for Qualtrics: {backend_url_for_qualtrics}")
    except Exception as e:
        print(f"[ERROR URL] Failed to derive URL from request.url_root: {e}")

    # --- Format the displayed allowed origins ---
    # (Ensure allowed_origins is defined earlier in the function)
    escaped_origins_list = [html.escape(o) for o in allowed_origins]
    if escaped_origins_list == ['*']:
        allowed_origins_display = "<code>*</code> (Any origin - less secure)"
    else:
        allowed_origins_display = ", ".join(f"<code>{o}</code>" for o in escaped_origins_list)
        if not allowed_origins_display:
             allowed_origins_display = "<i>None specified (CORS likely misconfigured/denied)</i>"

    # --- Generate Simplified HTML Page ---
    # Uses only: backend_url_for_qualtrics, allowed_origins_display
    display_html = f"""
    <!DOCTYPE html><html lang="en">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>LUCID Backend Deployed</title>
    <style>
        body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif; padding: 20px; line-height: 1.6; background-color: #f8f9fa; color: #212529; }}
        .container {{ max-width: 750px; margin: 40px auto; padding: 35px; border: 1px solid #dee2e6; border-radius: 8px; background-color: #ffffff; box-shadow: 0 4px 8px rgba(0,0,0,0.05); }}
        h1 {{ color: #0d6efd; border-bottom: 2px solid #0d6efd; padding-bottom: 10px; margin-bottom: 20px; }}
        h2 {{ color: #495057; margin-top: 30px; border-bottom: 1px solid #ced4da; padding-bottom: 8px;}}
        code {{ background-color: #e9ecef; padding: 0.2em 0.5em; border-radius: 4px; font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 0.9em; color: #d63384;}}
        .url-box {{ background-color: #f1f3f5; padding: 12px 18px; border: 1px solid #adb5bd; border-radius: 5px; font-family: "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; word-wrap: break-word; margin-bottom: 15px; font-size: 1.05em; color: #0b5ed7; }}
        button {{ padding: 10px 18px; cursor: pointer; border-radius: 5px; border: none; background-color: #0d6efd; color: white; font-size: 15px; transition: background-color 0.2s ease; }}
        button:hover {{ background-color: #0b5ed7; }}
        .copied-message {{ color: #198754; font-weight: bold; display: none; margin-left: 10px;}}
        .important {{ background-color: #fff3cd; border: 1px solid #ffeeba; color: #664d03; padding: 15px 20px; border-radius: 5px; margin-top: 20px; }}
        .important code {{ background-color: #fde7a0; color: #664d03; }}
        ul {{ margin-top: 10px; padding-left: 20px; }} li {{ margin-bottom: 5px; }}
        p {{ margin-bottom: 1rem; }}
    </style>
    </head>
    <body><div class="container">
        <h1>LUCID Backend Successfully Deployed!</h1>

        <h2>Next Step: Configure Qualtrics</h2>
        <p>To connect your Qualtrics survey to this backend:</p>
        <ol>
            <li><strong>Copy the full Backend URL below.</strong> This URL should reflect the main production domain when accessed via production. Use this URL for the <code>LUCIDBackendURL</code> Embedded Data field in Qualtrics.</li>
            <li>In your Qualtrics Survey Flow, create or update the Embedded Data field named <code>LUCIDBackendURL</code> and paste this URL as its value.</li>
        </ol>
        <p><strong>Backend URL (Value for <code>LUCIDBackendURL</code>):</strong></p>
        <div id="qualtricsUrlBox" class="url-box">{backend_url_for_qualtrics}</div>
        <button onclick="copyUrl()">Copy Backend URL</button>
        <span id="copiedMsg" class="copied-message">Copied!</span>
    </div>
    <script>function copyUrl() {{ const urlText = document.getElementById('qualtricsUrlBox').innerText; navigator.clipboard.writeText(urlText).then(() => {{ const msg = document.getElementById('copiedMsg'); msg.style.display = 'inline'; setTimeout(() => {{ msg.style.display = 'none'; }}, 2500); }}).catch(err => {{ console.error('Failed to copy: ', err); alert('Failed to copy URL.'); }}); }}</script>
    </body></html>
    """

    # Create Flask response object with the HTML
    resp = make_response(display_html)
    resp.headers['Content-Type'] = 'text/html' # Set correct MIME type

    # Apply basic CORS headers for the root route as well (GET requests usually simpler)
    origin_to_send = None
    send_credentials_get = False # Renamed variable to avoid conflict
    if '*' in allowed_origins:
        origin_to_send = '*'
    elif origin and origin in allowed_origins:
        origin_to_send = origin
        send_credentials_get = True # Allow credentials if specific origin matches
    if origin_to_send:
        resp.headers['Access-Control-Allow-Origin'] = origin_to_send
        resp.headers['Vary'] = 'Origin'
        # Only add credentials header if needed and true
        if send_credentials_get:
            resp.headers['Access-Control-Allow-Credentials'] = 'true'
    return resp

@app.route('/lucid', methods=['POST'])
def lucid():
    """
    Main API endpoint (/lucid).
    Receives chat messages and configuration from Qualtrics frontend via POST request.
    Validates request origin using CORS settings.
    Calls the OpenAI Chat Completions API.
    Returns the AI's response or an error message in JSON format.
    Includes necessary CORS headers on the response, including 'Access-Control-Allow-Credentials'
    only when appropriate and with the value 'true'.
    """
    # --- Step 1: CORS Check for POST request ---
    origin = request.headers.get('Origin')
    allowed_origins = get_allowed_origins_config()
    print(f"[DEBUG POST /lucid] Request Origin: '{origin}' vs Allowed: {allowed_origins}") # Vercel Log

    origin_to_send = None # Header value for Access-Control-Allow-Origin
    # 'allow_credentials_post' will determine if the 'Access-Control-Allow-Credentials' header is sent
    allow_credentials_post = False # Default to false, set true only for specific allowed origins
    is_request_allowed = False # Flag to track if request passes CORS check

    # Determine if the request origin is permitted
    if '*' in allowed_origins:
        origin_to_send = '*'
        is_request_allowed = True
        allow_credentials_post = False # Cannot use credentials with wildcard
        print("[DEBUG POST /lucid] Policy: Allowed Wildcard (*), Credentials False") # Vercel Log
    elif origin and origin in allowed_origins:
        origin_to_send = origin
        is_request_allowed = True
        allow_credentials_post = True # Allow credentials for specific origins
        print(f"[DEBUG POST /lucid] Policy: Allowed Specific Origin ({origin}), Credentials True") # Vercel Log
    else:
        # Origin is not in the allowed list (and not wildcard)
        is_request_allowed = False
        print(f"[DEBUG POST /lucid] Policy: Denied Origin ({origin})") # Vercel Log

    # If CORS check fails, return 403 Forbidden immediately
    if not is_request_allowed:
        print(f"[WARN] POST to /lucid denied for origin: {origin}.") # Vercel Log
        error_resp = make_response(jsonify({'error': 'Forbidden', 'message': 'Origin not permitted.'}), 403)
        # Add CORS headers even on error where possible, though browser might ignore on 403
        if origin_to_send:
             error_resp.headers['Access-Control-Allow-Origin'] = origin_to_send
             error_resp.headers['Vary'] = 'Origin'
             # Only add credentials header if needed and true
             if allow_credentials_post:
                 error_resp.headers['Access-Control-Allow-Credentials'] = 'true'
        return error_resp
    # --- End CORS Check ---

    # --- Step 2: Process Request Body ---
    print(f"[INFO] ------ Entered lucid function from allowed origin: {origin} ------") # Vercel Log
    post_data = request.data # Get raw request body
    print(f"[INFO /lucid] Received {len(post_data)} bytes.") # Vercel Log

    response_data = {} # Dictionary to hold the JSON response data
    status_code = 500  # Default to Internal Server Error

    try:
        # Decode body as UTF-8 and parse JSON
        body = json.loads(post_data.decode('utf-8'))

        # --- Step 3: Get and Check for API Key ---
        # UPDATED: Check for both uppercase and lowercase env var names
        openai_api_key = (
            os.getenv('OPENAI_API_KEY') or  # Vercel / production (Screaming Snake Case)
            os.getenv('openai_api_key')     # legacy/local (lower snake case)
        )

        # Basic check/log for the API key (without exposing the key itself)
        if isinstance(openai_api_key, str) and len(openai_api_key) > 7:
            print(f"[DIAGNOSTIC /lucid] API Key Found (Length: {len(openai_api_key)}).") # Vercel Log
        elif not openai_api_key:
            print("[CRITICAL DIAGNOSTIC /lucid] Neither os.getenv('OPENAI_API_KEY') nor os.getenv('openai_api_key') returned a value!") # Vercel Log

        # --- Check if API Key is actually present ---
        if not openai_api_key:
            print('[CRITICAL /lucid] OpenAI API key not found in environment variables (checked OPENAI_API_KEY and openai_api_key).') # Vercel Log
            # Set error response if key is missing
            response_data = {'error': 'Configuration Error', 'message':'OpenAI API key not configured on server.'}
            status_code = 500 # Indicate server configuration error
        else:
            # API Key found, proceed to extract data and call OpenAI

            # Extract parameters sent from Qualtrics frontend
            model = body.get('model', 'gpt-4o') # Use model from request, default to gpt-4o if not sent (JS usually sends its default)
            messages = body.get('messages', []) # Get message history array
            temp_from_frontend = body.get('temperature') # Get optional temperature
            seed_from_frontend = body.get('seed') # Get optional seed

            # Validate messages list (must not be empty)
            if not messages or not isinstance(messages, list):
                print("[WARN /lucid] Invalid or empty 'messages' list received.") # Vercel Log
                response_data = {'error': 'Bad Request', 'message': 'Messages list is missing, empty, or invalid.'}
                status_code = 400 # Bad Request
            else:
                # --- Required: resolve the system prompt from prompts.yaml via condition ---
                # prompts.yaml is now the single source of truth for what the AI says.
                # LUCIDPromptInitial in the .qsf is no longer used - the frontend may still
                # send it, but it's ignored here. This endpoint requires a recognized
                # `condition` field with a matching prompts.yaml entry, and returns an error
                # instead of silently falling back to a stale or missing prompt.
                condition = body.get('condition')
                condition_key = str(condition).strip().lower() if condition else None
                condition_prompt = CONDITION_PROMPTS.get(condition_key) if condition_key else None

                if not condition_prompt:
                    print(f"[ERROR /lucid] No prompt found for condition='{condition}'. Loaded conditions: {sorted(CONDITION_PROMPTS.keys())}") # Vercel Log
                    response_data = {
                        'error': 'Configuration Error',
                        'message': f"No prompt configured for condition '{condition}'. Check that the frontend sends a valid 'condition' and that prompts.yaml has a matching entry."
                    }
                    status_code = 400 # Bad Request
                else:
                    # Use the prompts.yaml text as the system message: replace messages[0] if
                    # it's already a system message, otherwise prepend one.
                    if isinstance(messages[0], dict) and messages[0].get('role') == 'system':
                        messages[0] = dict(messages[0], content=condition_prompt.get('initial_prompt', ''))
                    else:
                        messages = [{'role': 'system', 'content': condition_prompt.get('initial_prompt', '')}] + messages
                    print(f"[INFO /lucid] Using prompts.yaml system prompt for condition='{condition_key}'") # Vercel Log

                    # Process temperature (use value from frontend if valid, otherwise default to 1.0)
                    used_temperature = 1.0 # Default temperature
                    if temp_from_frontend is not None:
                        try:
                            parsed_temp = float(temp_from_frontend)
                            if 0.0 <= parsed_temp <= 2.0: used_temperature = parsed_temp
                            else: print(f"[WARN /lucid] Temp '{parsed_temp}' out of range, using default.") # Vercel Log
                        except (ValueError, TypeError): print(f"[WARN /lucid] Invalid temp format ('{temp_from_frontend}'), using default.") # Vercel Log
                    print(f"[INFO /lucid] Using temperature: {used_temperature}") # Vercel Log

                    # Process seed (use value from frontend if valid, otherwise default to None)
                    used_seed = None # Default: OpenAI handles randomness
                    if seed_from_frontend is not None:
                        try: used_seed = int(seed_from_frontend)
                        except (ValueError, TypeError): print(f"[WARN /lucid] Invalid seed format ('{seed_from_frontend}'), using default (None).") # Vercel Log
                    print(f"[INFO /lucid] Using seed: {used_seed}") # Vercel Log

                    # --- Step 4: Call OpenAI API ---
                    # Tell the model what round of the negotiation this is. Derived from the
                    # message history itself (count of 'user' messages, including the one that
                    # triggered this request) rather than trusting a client-supplied counter, so
                    # it can't drift out of sync. Appended as the LAST message so it's the most
                    # recent/salient context the model sees before generating - after any
                    # frontend-injected reinforcement message.
                    current_round = sum(1 for m in messages if isinstance(m, dict) and m.get('role') == 'user')
                    round_limit = body.get('round_limit')  # optional - only present if the frontend sends it
                    if round_limit:
                        round_context = f"[SYSTEM CONTEXT: This is round {current_round} out of {round_limit} in this negotiation.]"
                    else:
                        round_context = f"[SYSTEM CONTEXT: This is round {current_round} of this negotiation.]"

                    # Prosocial-only: whether the model has already had a turn to state its
                    # opening offer AND ask about the customer's priorities together (the
                    # [ROUND 1 - INFORMATION EXCHANGE] step). There's no server-side session
                    # state across requests, so this is derived from the message history
                    # itself: if an assistant reply already exists, round 1 already happened
                    # (and was enforced compliant - see the retry loop below), so remind the
                    # model not to repeat the question. If not, this is round 1 and the retry
                    # loop after the API call will enforce that THIS reply covers both.
                    has_prior_assistant_reply = any(isinstance(m, dict) and m.get('role') == 'assistant' for m in messages)
                    extra_system_notes = []
                    if condition_key == 'prosocial' and has_prior_assistant_reply:
                        extra_system_notes.append(
                            "You already stated your opening offer and asked the customer about "
                            "their priorities together in your first message earlier in this "
                            "negotiation - do not ask them to restate it again. Move the negotiation "
                            "forward on the actual price instead, unless they bring up something new "
                            "themselves."
                        )

                    messages_for_api = messages + [{'role': 'system', 'content': round_context}] + [
                        {'role': 'system', 'content': note} for note in extra_system_notes
                    ]
                    print(f"[INFO /lucid] Injected round context: {round_context}") # Vercel Log

                    # Construct payload for OpenAI
                    data_payload = {
                        'model': model,
                        'messages': messages_for_api,
                        'temperature': used_temperature
                    }
                    # Only include seed if one was provided and valid
                    if used_seed is not None:
                        data_payload['seed'] = used_seed

                    print(f"[INFO /lucid] Calling OpenAI API (model: {model}). Payload keys: {list(data_payload.keys())}") # Vercel Log

                    # Make the POST request to OpenAI with a timeout
                    response_openai = _call_openai_chat(messages_for_api, model, used_temperature, used_seed, openai_api_key, timeout=30)
                    openai_status = response_openai.status_code
                    openai_response_text = response_openai.text # Get raw text for potential error logging
                    print(f"[INFO /lucid] OpenAI response status: {openai_status}") # Vercel Log

                    # --- Step 5: Process OpenAI Response ---
                    if openai_status == 200:
                        # Successful call
                        print("[INFO /lucid] Successfully processed OpenAI response.") # Vercel Log
                        try:
                            # Parse the JSON response from OpenAI
                            resp_json = response_openai.json()
                            # Extract the generated text content safely
                            generated_text = resp_json['choices'][0]['message']['content']

                            # --- Prosocial round-1 compliance: this reply MUST state the opening
                            # offer AND ask the customer about their priorities, together (see
                            # [ROUND 1 - INFORMATION EXCHANGE] in prompts.yaml). If it's missing
                            # either one, regenerate rather than sending a non-compliant reply to
                            # the chat interface. Bounded by PROSOCIAL_ROUND1_MAX_ATTEMPTS to
                            # protect against a function timeout if the model persistently won't
                            # comply.
                            if condition_key == 'prosocial' and not has_prior_assistant_reply:
                                attempts = 1
                                complied = _detect_round1_compliance_llm(generated_text, openai_api_key)
                                while not complied and attempts < PROSOCIAL_ROUND1_MAX_ATTEMPTS:
                                    attempts += 1
                                    print(f"[WARN /lucid] Prosocial round-1 reply (attempt {attempts - 1}) didn't state its opening offer and ask about customer priorities together; regenerating (attempt {attempts}/{PROSOCIAL_ROUND1_MAX_ATTEMPTS}).") # Vercel Log
                                    nudge = {
                                        'role': 'system',
                                        'content': (
                                            "Your previous draft reply did not clearly state your opening offer "
                                            "AND ask the customer what matters most to them in this sale, "
                                            "together in the same message. Rewrite your reply so it does both, "
                                            "per your [ROUND 1 - INFORMATION EXCHANGE] instructions, before "
                                            "anything else."
                                        )
                                    }
                                    retry_text = _call_openai_completion_text(
                                        messages_for_api + [nudge], model, used_temperature, used_seed, openai_api_key
                                    )
                                    if retry_text:
                                        generated_text = retry_text
                                        complied = _detect_round1_compliance_llm(generated_text, openai_api_key)
                                    else:
                                        print("[WARN /lucid] Round-1 retry call failed; keeping previous draft.") # Vercel Log
                                        break
                                if not complied:
                                    print(f"[WARN /lucid] Prosocial round-1 reply still incomplete after {attempts} attempt(s) (capped at {PROSOCIAL_ROUND1_MAX_ATTEMPTS} to avoid a function timeout); sending best available reply anyway.") # Vercel Log

                            # Extract offers for THIS turn only (NEGOTIATION FEATURE): the user message
                            # that triggered this request, and the assistant's brand-new response.
                            # We intentionally do not rescan the whole history - see get_turn_offers().
                            latest_user_text = ''
                            for m in reversed(messages):
                                if m.get('role') == 'user':
                                    latest_user_text = m.get('content', '')
                                    break
                            offers_data = get_turn_offers(latest_user_text, generated_text)

                            # Prepare the successful response data for Qualtrics frontend
                            response_data = {
                                'generated_text': generated_text,
                                'used_temperature': used_temperature, # Echo back parameters used
                                'offers': offers_data  # Include extracted offer data
                            }
                            if used_seed is not None:
                                response_data['used_seed'] = used_seed # Echo back seed if used

                            status_code = 200 # OK
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                            # Handle cases where OpenAI gives 200 but response format is unexpected
                            print(f"[ERROR /lucid] OpenAI response format unexpected (Status 200): {openai_response_text} - Error: {e}") # Vercel Log
                            response_data = {'error': 'Internal Server Error', 'message': 'Invalid response format from AI service.'}
                            status_code = 500
                    else:
                        # Handle error responses from OpenAI (non-200 status)
                        print(f"[ERROR DIAGNOSTIC /lucid] OpenAI API Error ({openai_status}): {openai_response_text}") # Vercel Log
                        # Try to extract a cleaner error message from OpenAI's response JSON
                        error_details = openai_response_text
                        try:
                           error_json = response_openai.json()
                           if 'error' in error_json and 'message' in error_json['error']:
                               error_details = error_json['error']['message']
                        except json.JSONDecodeError:
                            pass # Use raw text if parsing fails
                        response_data = {'error': f'AI Service Error ({openai_status})', 'message': error_details}
                        # Use OpenAI's status code if it's a standard error, otherwise default to 500
                        status_code = openai_status if openai_status < 600 else 500

    # --- Step 6: Handle Exceptions during Request Processing ---
    except requests.exceptions.Timeout:
        print("[ERROR /lucid] Request to OpenAI timed out.") # Vercel Log
        response_data = {'error': 'Gateway Timeout', 'message': 'Request to AI service timed out.'}
        status_code = 504 # Gateway Timeout
    except requests.exceptions.RequestException as e:
        # Handle network errors connecting to OpenAI
        print(f"[ERROR /lucid] Network error connecting to OpenAI: {e}") # Vercel Log
        response_data = {'error': 'Service Unavailable', 'message': 'Network error connecting to AI service.'}
        status_code = 503 # Service Unavailable
    except json.JSONDecodeError:
        # Handle invalid JSON sent from the frontend
        print(f"[ERROR /lucid] Invalid JSON received from client.") # Vercel Log
        response_data = {'error': 'Bad Request', 'message': 'Invalid JSON format in request body.'}
        status_code = 400 # Bad Request
    except Exception as e:
        # Catch-all for any other unexpected errors
        print(f"[ERROR /lucid] Unexpected server error: {e.__class__.__name__}: {e}") # Vercel Log
        # Consider logging the full traceback here if possible in production
        import traceback
        traceback.print_exc() # Print traceback to logs
        response_data = {'error': 'Internal Server Error', 'message': f'An unexpected error occurred processing the request.'}
        status_code = 500

    # --- Step 7: Create and Return Final Flask Response ---
    final_response = make_response(jsonify(response_data), status_code)

    # Add required CORS headers to the actual response
    final_response.headers['Access-Control-Allow-Origin'] = origin_to_send
    final_response.headers['Vary'] = 'Origin' # Important for caching proxies

    # UPDATED: Only add Access-Control-Allow-Credentials header if it should be 'true'
    if allow_credentials_post: # This boolean reflects the decision made earlier
        final_response.headers['Access-Control-Allow-Credentials'] = 'true'
        print("[DEBUG POST /lucid] Adding Access-Control-Allow-Credentials: true to final response") # Vercel Log
    else:
        print("[DEBUG POST /lucid] Not adding Access-Control-Allow-Credentials header to final response") # Vercel Log


    final_response.headers['Content-Type'] = 'application/json' # Ensure correct content type

    print(f"[INFO /lucid] Responding with status code: {status_code}") # Vercel Log
    return final_response

# --- Main Execution Block (for local development) ---
if __name__ == '__main__':
    # This block only runs when the script is executed directly (e.g., `python lucid_api.py`)
    # It's ignored when run by a WSGI server like Vercel's Python runtime.
    print("[INFO] Starting Flask development server...")

    # Optional: Set environment variables locally for testing
    # os.environ['OPENAI_API_KEY'] = 'YOUR_LOCAL_TEST_KEY_HERE' # Use uppercase for testing
    # os.environ['ALLOWED_ORIGINS'] = '*' # Example: Allow all for local testing
    # os.environ['VERCEL_URL'] = 'localhost:8080' # Example for testing the root page

    # Run the Flask development server
    # Debug=True enables auto-reloading and provides detailed error pages (DO NOT use in production)
    local_port = int(os.getenv('PORT', 8080)) # Use PORT env var if set, otherwise default to 8080
    app.run(debug=True, port=local_port, host='0.0.0.0') # Host 0.0.0.0 makes it accessible on network