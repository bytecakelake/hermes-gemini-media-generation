# Changelog

## 0.1.0 (unreleased)

* Image generation (`gemini-nano-banana-2.1` and other Gemini image models) with up to 14
  reference images, 1K/2K/4K, aspect mapping.
* Video generation (`gemini-omni-1.1-flash`): text, image and reference-to-video, 3-10 s,
  16:9 / 9:16, 360p-4K, native audio.
* Live model catalog from `models.list` with disk cache and offline fallback.
* API-key authentication. OAuth is planned after this release.
