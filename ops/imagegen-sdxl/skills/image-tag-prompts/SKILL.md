---
name: image-tag-prompts
description: How to write prompts for generate_image with the SDXL models. Tag-style (comma-separated booru tags) for illustrious and pony, plain English for juggernaut and realvis, plus sizes, negatives and the retry loop.
when_to_use: Before calling generate_image with model=illustrious or model=pony (they ignore sentences), and whenever you pick between the SDXL models. Load it once per task, not per image.
enabled: true
created_by: user
---

# Prompts for the SDXL image models

`generate_image(prompt, model=..., size=..., seed=..., negative_prompt=...)`. Omit `model` for the default model
(plain English, no tags). Pick **one** model per task: switching reloads the checkpoint (10-30 s).

| model | use it for | prompt style |
|---|---|---|
| `juggernaut` | photoreal, cinematic, general scenes | English phrases |
| `realvis` | photoreal people and portraits | English phrases |
| `illustrious` | anime, illustration, characters | **tags** (Danbooru) |
| `pony` | anime, cartoon, furry, stylized | **tags** (e-621/Danbooru mix) |

The service already adds each model's quality tags (`masterpiece, best quality` or `score_9, score_8_up, score_7_up`)
and a sensible negative prompt. **Do not repeat them.** It applies no content filter, so describe exactly what the
user asked for, no more and no less.

## Tag style (illustrious, pony)

- One comma-separated line of short tags. No sentences, no "a picture of", no filler words. Lowercase.
- Use spaces inside a tag (`blue eyes`), not underscores, unless a tag only makes sense with them.
- Order matters: earlier tags weigh more. Use this order:
  1. subject count and kind: `1girl`, `solo`, `2boys`, `1girl, 1boy`, `no humans`, `scenery`
  2. named character and series, only if the user named one: `hatsune miku, vocaloid`
  3. body and face: `long hair, blue hair, twintails, green eyes, smile`
  4. clothing and held items: `white dress, straw hat, holding umbrella`
  5. pose and action: `standing, looking at viewer, walking`
  6. setting: `outdoors, city street, rain, night, neon lights`
  7. camera and composition: `cowboy shot, from below, close-up, depth of field`
  8. lighting and style: `backlighting, soft lighting, watercolor (medium), flat color`
- Keep it to about 15-40 tags. Every tag must earn its place; do not stack synonyms.
- Never write contradictions (`1girl, 2girls`, `day, night`, `short hair, long hair`).
- Do not use weighting syntax like `(tag:1.3)` or `[tag]`. If something matters more, move it earlier and make it
  more specific.
- Text inside the image does not work in SDXL. Leave it out and tell the user.
- Characters and styles: use the tag the community uses (`character_(series)` as `character, series`). If you are not
  sure a tag exists, describe the look with ordinary tags instead of guessing a name.

### illustrious only
- Rating tag is optional. Add one only if the user's request calls for it: `general`, `sensitive`, `questionable`,
  `explicit`. Without one the model picks by itself, usually safe.
- Helpful extras: `newest`, `absurdres` (high detail). Skip them if the service prefix is enough.

### pony only
- Start the tag part with a source tag, right after the service's score prefix: `source_anime`, `source_cartoon`,
  `source_furry` or `source_pony`. Pick the one that fits the style the user wants.
- Rating tag (optional, same rule as above): `rating_safe`, `rating_questionable`, `rating_explicit`.
- Pony has no artist-name knowledge. Do not use artist tags; describe the style (`flat color, thick outline`).

## English style (juggernaut, realvis)

- Short descriptive phrases or one or two plain sentences: subject, setting, light, camera. About 30-60 words.
- Photo cues work: `35mm photo`, `85mm portrait`, `shallow depth of field`, `golden hour`, `overcast softbox light`,
  `film grain`. Name materials and textures (`worn leather`, `wet asphalt`).
- Skip the tag spam (`masterpiece, 8k, ultra detailed`). It does little for these models.
- Describe what is there, not what is absent. Put unwanted things in `negative_prompt` instead.

## Negative prompt

Defaults are applied per model. Pass `negative_prompt` only for specific problems you can see in the result, in the
same style as the prompt (tags for illustrious/pony): `watermark`, `extra limbs`, `text`, `cropped`, `blurry background`.

## Size

SDXL works best near one megapixel. Use `1024x1024` (square), `832x1216` (portrait, single character),
`1216x832` (landscape, scenes) or `1280x720` (wide). Avoid `512x512`: quality drops.

## Retry loop

Look at the result against the request, then change **one thing at a time** and keep the `seed` to keep the
composition, or change it for a fresh layout.
- Wrong or missing detail: move that tag earlier and make it more specific.
- Bad hands: add `bad hands, extra fingers` to the negative and use a pose that hides hands (`arms behind back`).
- Cluttered: remove tags, add `simple background`.
- Wrong style: switch model once, not repeatedly.
Stop after two refinements and report the best file path.

## Hard limits

- No sexual content involving minors or characters who look or are described as children. Never use tags like
  `child`, `loli`, `shota`, `young`, `school uniform` together with sexual tags. If a request needs that, refuse.
- No sexual or degrading images of real, named people.
