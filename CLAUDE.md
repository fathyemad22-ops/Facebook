# Project notes for Claude

Automated Facebook Page publishing. Claude writes posts (Egyptian Arabic by default), they wait
in `content/queue/*.json`, and `.github/workflows/post.yml` publishes the oldest ready one 4 times a day
(or a scheduled Claude session publishes it through the Zapier connector, see below).

## Layout
- `config.yaml`: page name, active niche, Claude model/effort, posting options, brand colours.
- `niches/<id>.yaml`: audience, voice, pillars (content types with weights), hashtags, rules.
- `fbposter/`: `generator.py` (Claude API), `facebook.py` (Graph API), `cards.py` (image cards),
  `store.py` (queue/history/pillar planning), `cli.py` (commands).
- `content/history.jsonl`: one JSON line per published post (topic, pillar, fb_id, permalink).

## Writing posts by hand (e.g. when asked to "write next week's posts" without an API key)
1. Read `config.yaml`, the active `niches/<id>.yaml`, the topics in `content/history.jsonl`, and
   `content/queue/`. Never repeat a topic or a close variant of one.
2. Follow the same rules as the system prompt in `fbposter/generator.py` (hook on the first line,
   60–180 words, short paragraphs, a few emojis, one real closing question, no engagement bait,
   no links, nothing uncertain or time-sensitive like prices or version numbers).
3. Use `python -m fbposter status` to see the queue, and spread pillars roughly by their weights.
4. Write a JSON list (pillar, topic, text, hashtags, card_headline, card_body; optional
   with_image, not_before) to a scratch file and run `python -m fbposter add <file>`.
5. Optionally `python -m fbposter preview` to render card PNGs next to the queue files for review.
6. Run `python -m pytest -q`, then commit `content/` and push.

## Publishing through the Zapier connector (scheduled Claude sessions)
Use this when the Facebook Page is connected through Zapier instead of GitHub secrets:
1. `git pull`, then `python -m fbposter next --render`. It prints the next post as JSON
   (`message`, `image_path`, `image_url`). If `post` is null the queue is empty: write new posts
   (section above) first.
2. If `--render` created a new PNG, commit and push it so `image_url` (raw.githubusercontent.com,
   the repo is public) resolves.
3. Publish with the Zapier Facebook Pages action: **Create Page Photo** with the image URL and the
   message as the caption, or **Create Page Post** with the message when `image_url` is null.
4. `python -m fbposter done <id> --fb-id <id from Zapier> --permalink <url if returned>`,
   then commit `content/` and push.
Only one path may publish: do not run this while `post.yml` has Facebook secrets configured.

## Conventions
- Never commit tokens or `.env`. Secrets live in GitHub Actions secrets:
  `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN`, `ANTHROPIC_API_KEY`.
- Default model `claude-opus-5-5` with `fallbacks: "default"`; structured output via
  `output_config.format`.
- Cards need Pillow with raqm (Arabic shaping); `python -m fbposter check` reports it.
