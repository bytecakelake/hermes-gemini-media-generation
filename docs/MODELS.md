## Models and limits

The catalog comes from the Gemini `models.list` endpoint for your key; curated labels below are
only used for ordering and descriptions. Limits marked *measured* were checked against the live
API in October 2026 and may change.

### Image (`image_generate`)

| Model id | Notes |
|---|---|
| `gemini-nano-banana-2.1` (default) | Current workhorse, 1K/2K/4K, multi-reference |
| `gemini-3.1-flash-lite-image` | Fastest/cheapest, 1K only |
| `gemini-3.1-flash-image` | Previous generation |
| `gemini-3-pro-image` | Premium quality |
| `gemini-2.5-flash-image` | Legacy |

* Aspect: Hermes's `landscape` / `square` / `portrait` map to `16:9` / `1:1` / `9:16`.
* Size: set `image_gen.gemini.image_size` (`1K`, `2K`, `4K`); unsupported sizes for the chosen model
  are lowered to the smallest supported one and `image_size_adjusted: true` is reported.
* References: `image_url` plus `reference_image_urls`, up to 14 images, PNG/JPEG/WebP/HEIC/HEIF,
  15 MB each and 18 MB in total (sent inline). The API may return JPEG even for PNG input.

### Video (`video_generate`)

| Model id | Notes |
|---|---|
| `gemini-omni-1.1-flash` (default) | Text, image and reference-to-video, native audio |

* The call is synchronous (typically 15-25 s at 360p) and returns the MP4 inline; nothing to poll.
* *Measured:* duration **3-10 s** (default 10 s when unset), aspect **16:9 or 9:16** only,
  resolution **360p / 720p / 1080p / 4k** (1080p and 4k are upscaled). Other values are rounded
  into range and reported as `*_adjusted`.
* Routing: no image -> `text_to_video`; only `image_url` -> `image_to_video` (first frame);
  `reference_image_urls` (with or without `image_url`) -> `reference_to_video`.
* *Measured:* up to 6 reference images work. The plugin caps at 6.
* Audio is always generated and cannot be turned off; `negative_prompt` and `seed` are not
  supported and are reported under `ignored_parameters`.
* Video input (editing / extending / "make it like this video") is intentionally not supported.
  A video passed as a reference is rejected with `invalid_request`.

## Where the files go

Generated media is written by Hermes's own helpers to
`$HERMES_HOME/cache/generated/images/` and `.../videos/` as `gemini_<timestamp>_<id>.<ext>`,
and the absolute path is returned in the tool result. Nothing is uploaded anywhere except your
prompt and reference images, which are sent to the Gemini API. Generated images carry Google's
SynthID watermark.

## Errors

`error_type` is one of `missing_credentials`, `missing_dependency`, `invalid_request`,
`auth_error`, `rate_limited`, `content_blocked`, `no_model`, `timeout`, `provider_error`.
API keys are scrubbed from every error message.
