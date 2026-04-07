# Voice Agents

AI voice agent demo built on LangGraph with TrustyAI Guardrails integration.

## Project Structure

```
ai-voice-agent/
  backend/          Python WebSocket server (LangGraph agent graph)
  frontend/         React/Next.js UI
  deploy/chart/     Helm chart for OpenShift deployment
  guardrails/       Kustomize resources for Guardrails
```

## Guardrails

The app supports two independent guardrails systems that can be toggled on/off independently via the UI:

- **FMS** (TrustyAI Guardrails Orchestrator) — env var `GUARDRAILS_URL`
- **NeMo** (NeMo Guardrails server) — env var `NEMO_GUARDRAILS_URL`

The `guardrails_mode` is one of `"none"`, `"fms"`, `"nemo"`, or `"both"`. Four pre-compiled graphs are built at startup (one per mode). The frontend sends `set_guardrails_mode` messages and the backend selects the corresponding graph.

### FMS Guardrails

When `GUARDRAILS_URL` is set, the backend creates `ChatOpenAI` instances pointed at the orchestrator via the nginx proxy. Detectors are passed in `extra_body`. A custom `httpx` event hook logs detection results and warnings from every orchestrator response to both stdout and MLFlow traces (via `threading.local()` → `mlflow.get_current_active_span().set_attribute()`).

#### Orchestrator limitations

- **No streaming** — returns empty response for `stream: true`. All guardrails LLMs use `streaming=False`.
- **No `tool` role messages** — rejects with 422. Agent nodes use regular agents (with tools, regular LLM) and screen output separately.

#### FMS Screening flow

1. **`_screen_user_input`** — pre-screens the user's raw message with all four input detectors (`GUARDRAILS_DETECTORS_INPUT_ONLY`) before supervisor routing. Only the single user message is sent to avoid false positives from system prompts.
2. **Supervisor routing** — regular LLM with structured output (no guardrails).
3. **Supervisor direct response** (route=none) — `guardrails_llm` with full input+output detectors (`GUARDRAILS_DETECTORS`).
4. **Agent nodes** (credit_card, loan, investment) — regular agents with tools (regular LLM). Orchestrator can't handle `tool` role messages in the react agent loop.
5. **`_screen_agent_output`** — post-screens the agent's response text with HAP and built-in detectors (`GUARDRAILS_DETECTORS_OUTPUT_SCREEN`). Gibberish excluded (false positives on account detail lists).

#### Detector notes

- **Prompt injection** — `protectai/deberta-v3-base-prompt-injection-v2` (DeBERTa, 184M params, 22 datasets). Replaced `jackhhao/jailbreak-classifier` which was poorly calibrated.
- **False positives on system prompts** — gibberish, built-in, and prompt-injection detectors all trigger on agent system prompts (the SECURITY section contains "ignore previous instructions" which triggers DeBERTa). This is why agents use regular LLMs and screening is done on isolated message text.

### NeMo Guardrails

When `NEMO_GUARDRAILS_URL` is set, a `ChatOpenAI` instance (`nemo_llm`) is created pointed at the NeMo server. NeMo uses an OpenAI-compatible `/v1/chat/completions` endpoint. Blocking is detected by checking for canned response patterns (`"I'm sorry, I can't respond to that"`, `"I can't help with that type of request"`).

The NeMo service runs on port 8000 inside its pod but is fronted by a kube-rbac-proxy (HTTPS/443). A separate internal Service (`nemo-guardrails-internal`) exposes port 8000 directly, bypassing the RBAC proxy.

#### NeMo Screening flow

1. **`_screen_nemo_input`** — sends the user's raw message to `nemo_llm`, checks response for blocked patterns.
2. **Supervisor routing** — regular LLM with structured output (no guardrails).
3. **Supervisor direct response** (route=none) — `nemo_supervisor_agent` (uses `nemo_llm`), response checked for blocked patterns.
4. **Agent nodes** — regular agents with tools (regular LLM).
5. **`_screen_nemo_output`** — sends agent response text to `nemo_llm`, checks for blocked patterns.

### "Both" Mode

When both FMS and NeMo are active, screening layers both systems sequentially — if either blocks, the message is blocked:

1. FMS `_screen_user_input` → NeMo `_screen_nemo_input`
2. Supervisor routing (regular LLM)
3. Direct response via FMS `guardrails_llm` (with detectors)
4. Agent nodes (regular LLM with tools)
5. FMS `_screen_agent_output` → NeMo `_screen_nemo_output`

### Helm chart configuration

```yaml
guardrails:
  enabled: false
  url: "http://guardrails-maas-proxy:8033/v1"

nemoGuardrails:
  enabled: false
  url: "http://nemo-guardrails-internal:8000/v1"
```

## Kagenti Integration

The agent can optionally integrate with the [kagenti](https://github.com/kagenti) platform for agent catalog discovery, AuthBridge sidecar injection (zero-trust auth), and SPIRE workload identity.

### Feature flag

- **Env var**: `KAGENTI_ENABLED=true` — starts an A2A HTTP server on port 8000 alongside the WebSocket server on 8765. When unset or false, only the WebSocket server runs (existing behavior).
- **Helm**: `--set kagenti.enabled=true` — adds kagenti labels/annotations to the backend Deployment and pod template, creates a ServiceAccount for SPIRE identity, exposes port 8000, mounts SPIRE SVIDs, and sets the `KAGENTI_ENABLED` env var.

### A2A protocol endpoint

When enabled, the backend exposes:
- `GET /.well-known/agent-card.json` — agent metadata for kagenti catalog discovery
- `POST /` — A2A message endpoint (text-only, no voice/audio)

The A2A layer (`backend/src/a2a_server.py`) wraps the same LangGraph graph used by the WebSocket server. Multi-turn conversations are supported via `MemorySaver` keyed by A2A task context ID. Interrupt-based flows (agent asking for more info) map to `TaskState.input_required`.

### AuthBridge and WebSocket coexistence

The kagenti webhook injects an AuthBridge envoy sidecar that intercepts all inbound traffic for JWT validation. WebSocket traffic (port 8765) must bypass envoy since the frontend nginx proxy connects without a JWT. This is handled via the pod annotation `kagenti.io/inbound-ports-exclude: "8765"`, which tells the webhook's `proxy-init` init container to add iptables RETURN rules excluding port 8765 from envoy interception. A2A traffic (port 8000) goes through envoy for JWT validation as intended.

### SPIRE workload identity

When kagenti is enabled, the `spiffe-helper` sidecar writes SVID files to the `svid-output` emptyDir volume. The backend container mounts this at `/spiffe` (not `/opt` — the container image uses `/opt/app-root` for Python). The `SPIFFE_SVID_DIR` env var can override this path (defaults to `/spiffe`).

At startup, `ws_server.py` reads the JWT and X.509 SVIDs and extracts identity claims (`spiffe.id`, `spiffe.audience`, `spiffe.issuer`, `spiffe.expiry`). These are attached to MLflow traces as span attributes on a `voice_agent_invoke` (WebSocket) or `a2a_agent_invoke` (A2A) parent span that wraps each LangGraph invocation.

### Helm chart configuration

```yaml
kagenti:
  enabled: false
  a2aPort: 8000
```

### Kagenti labels and annotations

When `kagenti.enabled=true`, the Helm chart adds:

**Deployment metadata labels** (for kagenti catalog discovery):
- `kagenti.io/type: "agent"`, `kagenti.io/framework: "LangGraph"`, `kagenti.io/workload-type: "deployment"`, `protocol.kagenti.io/a2a: ""`

**Pod template labels** (for webhook sidecar injection):
- `kagenti.io/inject: "enabled"`, `kagenti.io/spire: "enabled"`, `kagenti.io/type: "agent"`, `protocol.kagenti.io/a2a: ""`

**Pod template annotations**:
- `kagenti.io/inbound-ports-exclude: "8765"` — excludes WebSocket port from envoy interception

### Deploying into kagenti

1. Deploy into a kagenti agent namespace (e.g., `team1`) that already has AuthBridge ConfigMaps and SPIRE registration.
2. Install with `helm install bank-agent ./chart --set kagenti.enabled=true -n team1`.
3. The kagenti webhook automatically injects AuthBridge sidecars (envoy-proxy, spiffe-helper, client-registration, proxy-init).
4. The agent appears in the kagenti catalog via its A2A agent card.
5. The backend pod runs 3 containers: `backend`, `envoy-proxy`, `spiffe-helper`.
