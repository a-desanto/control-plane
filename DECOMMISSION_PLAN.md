
## Flowise Status

Flowise is RETAINED as a client-facing UI only.

Rules:
- Flowise SHALL NOT orchestrate automation
- Flowise SHALL NOT call LLMs or tools directly
- Flowise SHALL act only as a client app submitting intents
- All AI execution flows through api-gateway → paperclipai

Any Flowise logic beyond UI input/output is deprecated.
