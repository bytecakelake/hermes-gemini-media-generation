# hermes-gemini-media-generation

Google Gemini **image** (Nano Banana) and **video** (Gemini Omni) backends for
[Hermes Agent](https://github.com/NousResearch/hermes-agent) `image_generate` and `video_generate`,
in a single plugin built on the `google-genai` SDK.

> Status: **v0.1.0 in development.** Image and video generation work against the live Gemini API
> with an API key. OAuth sign-in is planned after the first release.

## Features

* `image_generate`: Nano Banana models, text-to-image and reference-guided editing (up to 14
  reference images), 1K/2K/4K.
* `video_generate`: Gemini Omni, text-to-video, image-to-video and reference-to-video with native
  audio, 3-10 s, 16:9 / 9:16, 360p-4K.
* Model picker built from your key's live `models.list` (cached, with an offline fallback).
* One plugin, one API key, built on the official `google-genai` SDK.

See [docs/MODELS.md](docs/MODELS.md) for models, measured limits, parameter handling and where
generated files are stored.

## Install (once released)

```bash
hermes plugins install bytecakaleke/hermes-gemini-media-generation
hermes plugins enable gemini-media
hermes tools        # Image Generation / Video Generation -> Google Gemini
```

`GEMINI_API_KEY` (from <https://aistudio.google.com/apikey>) goes in `~/.hermes/.env`.
If you set it as a Windows system environment variable, restart Hermes so it is picked up.
`GOOGLE_API_KEY` is accepted as a fallback.

## Model selection

The agent never picks a model. Order of precedence:

1. `GEMINI_IMAGE_MODEL` / `GEMINI_VIDEO_MODEL` environment variable
2. `image_gen.gemini.model` / `video_gen.gemini.model` in `config.yaml`
3. `image_gen.model` / `video_gen.model` (only if it is a Gemini model id)
4. built-in default (`gemini-nano-banana-2.1`, `gemini-omni-1.1-flash`)

The model picker is built from the Gemini `models.list` endpoint for **your** key, cached for 24 h
in `$HERMES_HOME/cache/gemini_media/models.json`, with a built-in fallback list when the endpoint
is unreachable. The cache stores a hash of the key, never the key.

## Development

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest                 # offline unit tests
GEMINI_API_KEY=... .venv/Scripts/python -m pytest -m live   # real API calls
hermes plugins validate .
```

Provider tests subclass Hermes's ABCs, so a Hermes source tree must be importable. The tests look
in `%LOCALAPPDATA%\hermes\hermes-agent` or the directory in `HERMES_AGENT_DIR`.

Source lives in `src/hermes_gemini_media/`; the root `__init__.py` is a three-line shim because
Hermes loads plugins from the repository root.

## Relationship to other plugins

[`semirkabir/hermes-plugin-gemini-image`](https://github.com/semirkabir/hermes-plugin-gemini-image)
also provides Gemini image generation. This project is an independent implementation (no code
shared) that adds video generation and a live model catalog in one plugin. Both register the
provider name `gemini`; enable only one of them.

## License

Apache License 2.0. See `LICENSE` and `NOTICE`.
