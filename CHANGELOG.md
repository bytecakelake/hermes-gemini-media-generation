# Changelog

## 0.1.1 - 2026-10-26

* **Fix: dependency could not be installed alongside Hermes.** 0.1.0 required
  `google-genai>=2.33`, which needs `google-auth>=2.56`, while Hermes pins `google-auth==2.55.1`.
  The requirement is now `google-genai>=2.12,<3`; with Hermes's pins pip resolves 2.12.1.
* **Fix: video `resolution` was silently dropped on google-genai 2.12.x**, which does not model
  that field. `response_format` is now also sent through `extra_body`, which makes the request
  body identical on 2.12.1 and 2.33.0 (verified on the wire for both).

## 0.1.0 - 2026-10-26 (MVP)

* Image generation (`gemini-nano-banana-2.1` and other Gemini image models) with up to 14
  reference images, 1K/2K/4K, aspect mapping.
* Video generation (`gemini-omni-1.1-flash`): text, image and reference-to-video, 3-10 s,
  16:9 / 9:16, 360p-4K, native audio.
* Live model catalog from `models.list` with disk cache and offline fallback.
* API-key authentication. OAuth is planned after this release.
