# LLM Grammar Correction Multi-Provider Plan

Date: 2026-03-18

## Goal

Extend LLM-based grammar correction in the post-processing pipeline so the user can:

- enable the feature with the existing checkbox,
- get `ollama` selected by default,
- switch the provider to `Gemini`, `OpenAI`, `Claude`, or `Groq`,
- choose a model based on the selected provider,
- keep `Force CPU / free GPU VRAM` visible only for `ollama`.

The existing Ollama model default should remain unchanged.

## Architecture Fit

This feature fits the current desktop dictation flow documented in [docs/architecture.md](/home/ricelso/git/dictee/docs/architecture.md):

1. `dictee` captures audio and gets raw ASR text.
2. `dictee-postprocess` optionally applies grammar correction.
3. The corrected text is typed into the focused application.

That means the work belongs in two places:

- setup and config UI in [dictee-setup.py](/home/ricelso/git/dictee/dictee-setup.py),
- provider execution in [dictee-postprocess.py](/home/ricelso/git/dictee/dictee-postprocess.py).

## Current State

### Setup UI

The current UI is Ollama-only:

- checkbox label is `LLM grammar correction (ollama)` in [dictee-setup.py](/home/ricelso/git/dictee/dictee-setup.py#L3056),
- only a model combo is shown,
- only the Ollama CPU toggle is supported.

### Saved Configuration

The saved config currently writes:

- `DICTEE_LLM_POSTPROCESS=true`
- `DICTEE_LLM_MODEL=...`
- `DICTEE_LLM_TIMEOUT=...`
- `DICTEE_LLM_CPU=true` when enabled

This happens in [dictee-setup.py](/home/ricelso/git/dictee/dictee-setup.py#L267).

There is no provider setting yet.

### Runtime Behavior

The runtime correction path is hardcoded to Ollama:

- `llm_postprocess()` in [dictee-postprocess.py](/home/ricelso/git/dictee/dictee-postprocess.py#L424)
- subprocess call: `ollama run <model> <prompt>`

So a multi-provider UI alone would not be sufficient.

## Proposed Config Contract

Add a provider-neutral LLM configuration layer:

- `DICTEE_LLM_POSTPROCESS=true|false`
- `DICTEE_LLM_PROVIDER=ollama|openai|gemini|anthropic|groq`
- `DICTEE_LLM_MODEL=<model-id>`
- `DICTEE_LLM_TIMEOUT=<seconds>`
- `DICTEE_LLM_CPU=true|false` only for `ollama`

For authentication, prefer environment variables over writing secrets to `dictee.conf`:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

If needed later, provider-specific override variables can be added, but this is enough for the first implementation.

## UI Plan

Update the post-processing section in [dictee-setup.py](/home/ricelso/git/dictee/dictee-setup.py#L3056):

1. Rename the checkbox to provider-neutral wording.
2. Add a `Provider` combo box under the checkbox.
3. Default the provider to `ollama` when the option is first enabled.
4. Keep the `Model` field, but repopulate it when the provider changes.
5. Show `Force CPU (free GPU VRAM)` only when provider is `ollama`.
6. Keep the current Ollama default model as-is.
7. Keep the model combo editable so users can type a custom model ID.

### Provider Options

- `ollama`
- `OpenAI`
- `Gemini`
- `Claude`
- `Groq`

Internally, `Claude` should map to `anthropic` for config and runtime naming consistency.

## Runtime Plan

Refactor [dictee-postprocess.py](/home/ricelso/git/dictee/dictee-postprocess.py#L424) so grammar correction dispatches by provider:

- `ollama_postprocess(text, prompt, model, timeout)`
- `openai_postprocess(text, prompt, model, timeout)`
- `gemini_postprocess(text, prompt, model, timeout)`
- `anthropic_postprocess(text, prompt, model, timeout)`
- `groq_postprocess(text, prompt, model, timeout)`

Then keep a small dispatcher:

- read `DICTEE_LLM_PROVIDER`,
- call the matching provider function,
- fall back to the original text on timeout, missing binary, missing key, or HTTP failure.

## Networking Approach

Do not add heavyweight SDK dependencies for the first version.

Use standard HTTP requests from Python:

- OpenAI: `POST /v1/responses` or `POST /v1/chat/completions`
- Gemini: `POST :generateContent`
- Anthropic: `POST /v1/messages`
- Groq: `POST /openai/v1/chat/completions`

This keeps the runtime small and consistent with the current script-based architecture.

## Model Selection Plan

Use a curated built-in model list per provider, while keeping the combo editable.

This avoids two problems:

- provider catalogs change often,
- some providers expose many models that are not suitable for text correction.

### Recommended Initial Model Lists

As of 2026-03-18, based on official provider documentation:

#### Ollama

- keep current defaults:
  - `ministral:3b`
  - `gemma3:4b`
  - `gemma3:1b`
- append locally installed models from `ollama list`

#### OpenAI

- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.4-nano`

#### Gemini

- `gemini-2.5-pro`
- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`

#### Claude

- `claude-opus-4-6`
- `claude-sonnet-4-6`
- `claude-haiku-4-5`

#### Groq

- `llama-3.1-8b-instant`
- `llama-3.3-70b-versatile`
- `openai/gpt-oss-120b`
- `openai/gpt-oss-20b`

### Important Note

Do not treat this list as a permanent source of truth. It is a curated snapshot for the UI defaults. The editable combo box is required so the user can still type newer model IDs.

## Validation and UX Feedback

Add provider-aware validation in the setup UI:

- for `ollama`, detect whether `ollama` is installed,
- for remote providers, detect whether the relevant API key is present in the environment.

Suggested status messages:

- `ollama is not installed`
- `missing OPENAI_API_KEY`
- `missing GEMINI_API_KEY`
- `missing ANTHROPIC_API_KEY`
- `missing GROQ_API_KEY`

Do not block saving the config. Show the status and let runtime fall back safely.

## Backward Compatibility

Support existing configs without a provider field:

- if `DICTEE_LLM_POSTPROCESS=true` and no `DICTEE_LLM_PROVIDER` exists,
- assume `ollama`.

This preserves the current behavior for existing users.

## Documentation and Translation Work

Update:

- setup labels in [dictee-setup.py](/home/ricelso/git/dictee/dictee-setup.py),
- script header and env var docs in [dictee-postprocess.py](/home/ricelso/git/dictee/dictee-postprocess.py#L1),
- translation catalogs in `po/`,
- user-facing docs if there is a post-processing or setup section referencing Ollama-only behavior.

## Testing Plan

### Config

- verify old config loads as `ollama`,
- verify provider/model selections persist correctly,
- verify `DICTEE_LLM_CPU` is saved only for `ollama`.

### UI

- enabling the checkbox shows provider and model controls,
- provider defaults to `ollama`,
- changing provider refreshes the model list,
- CPU toggle is shown only for `ollama`.

### Runtime

- Ollama flow still works unchanged,
- remote providers return corrected text when key and network are available,
- missing key or timeout returns the original text unchanged.

## Implementation Order

1. Add config support for `DICTEE_LLM_PROVIDER`.
2. Refactor the setup UI to add provider selection and conditional controls.
3. Refactor `dictee-postprocess.py` into provider-specific execution paths.
4. Add UI validation and status messages.
5. Update docs and translation strings.
6. Run manual verification with Ollama first, then one remote provider.

## Risks

- Secret handling is the main product risk. Environment-based API keys are safer than storing them in `dictee.conf`.
- Provider response formats differ, so response parsing needs to stay explicit and minimal.
- Model lists are time-sensitive, so the editable model field is not optional.

## Sources

- Architecture: https://github.com/rcspam/dictee/blob/main/docs/architecture.md
- OpenAI models: https://developers.openai.com/api/docs/models
- Gemini models: https://ai.google.dev/gemini-api/docs/models
- Claude models: https://platform.claude.com/docs/en/about-claude/models/overview
- Groq models: https://console.groq.com/docs/models
