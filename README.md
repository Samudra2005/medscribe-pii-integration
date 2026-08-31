# PII Masking Middleware — prototype

A reversible PII-masking layer that sits between any application and any
LLM. No third-party anonymization framework (e.g. Presidio), no cloud
API calls — detection, masking, and the trained NER model are all
custom-built and run entirely locally.

## Files, in dependency order

| File | What it does |
|---|---|
| `span_types.py` | Shared `Span` type every detector produces. |
| `ner_model.py` | A trained-from-scratch NER model (scikit-learn) for PERSON and ORG. |
| `detectors.py` | Combines regex (phone/email/PAN/Aadhaar/dates/age), a gender term list, and the NER model into one `detect(text)` function. |
| `mask_pii.py` | The `Vault` — turns detected spans into reversible tokens and back. |
| `api.py` | REST API (FastAPI) — `/v1/mask` and `/v1/unmask`, JSON in/out. |
| `server.py` | The same REST API, zero dependencies (Python's built-in `http.server`) instead of FastAPI. |
| `master_app.py` | A reference "master program" — simulates STT output, calls the middleware, calls a (mocked) LLM, unmasks the result. This is the demo to show end-to-end. |
| `Dockerfile` / `requirements.txt` | Package `api.py` into a container any machine can run. |

All the `.py` files must stay in the same folder — they import each
other by filename.

## Quickest way to test: no server, just the logic

```bash
python3 mask_pii.py
```

Prints a masked sentence, then the same sentence correctly restored.

## Running the full end-to-end demo

This is the one to show your manager — it plays out the whole story:
speech-to-text output -> mask -> LLM -> unmask -> final answer.

```bash
# terminal 1: start the middleware
python3 server.py

# terminal 2: run the demo
python3 master_app.py

# or with your own example text:
python3 master_app.py --text "Hi, I'm Arjun Kapoor, calling from Bajaj Allianz."
```

The speech-to-text step and the LLM call are both mocked (no network
access to real cloud services in this environment), but clearly marked
as such in the code — swapping either for a real service is a small,
contained change. See the comment block at the bottom of `master_app.py`
for a ready-to-use example of swapping in a real Anthropic API call.

## Testing the actual REST API

Pick ONE of these two (they're the same API contract):

```bash
# zero-dependency version
python3 server.py

# OR the FastAPI version (needs: pip install fastapi uvicorn)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Then, from a second terminal:

```bash
curl -X POST http://127.0.0.1:8000/v1/mask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-only-key" \
  -d '{"payload": {"transcript": "Hi, I am Kabir Malhotra, male, 29, phone 98765-43210."}, "fields": ["transcript"]}'
```

Copy the `session_id` from the response, then:

```bash
curl -X POST http://127.0.0.1:8000/v1/unmask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-only-key" \
  -d '{"payload": {"response": "PASTE_MASKED_TEXT_HERE"}, "fields": ["response"], "session_id": "PASTE_SESSION_ID_HERE"}'
```

`X-API-Key` defaults to `dev-only-key` unless you set the
`MASKING_API_KEY` environment variable before starting the server.

## Known limitations (be upfront about these)

- **NER model accuracy**: trained on ~40 hand-labeled sentences. It
  genuinely generalizes to unseen names/orgs (proven in testing), but
  ambiguous multi-word phrases can still be mislabeled. The fix is
  more labeled data — synthetic (templates + name/org lists) or real
  domain examples — not more feature engineering.
- **Session store is in-memory**: fine for one process/demo. For
  multiple replicas or restarts, swap `_sessions` in `api.py`/`server.py`
  for Redis, keyed by `session_id` with the same TTL.
- **`server.log` gets created** when you run `server.py` — safe to
  delete, it's just stdout/stderr redirected to a file.

## Running via Docker instead

```bash
docker build -t pii-middleware .
docker run -p 8000:8000 -e MASKING_API_KEY=some-real-secret pii-middleware
```
