# Website Studio — private ChatGPT/Codex plugin

Create, analyse, refine and redesign websites using deliberate art direction, accessibility, measured evidence and six selectively loaded reference sources. This is a self-contained plugin export, not the original host installation. It contains no profile configuration, credentials, client projects, audit screenshots or schedules.

## Add to your ChatGPT workspace
Where your workspace exposes marketplace import and you are its admin:
1. Open the OpenAI Admin Console, select your intended ChatGPT workspace, then **Plugins → Add → Import marketplace**.
2. **Source:** `https://github.com/PattrnData/website-studio`
3. **Path:** leave empty (the marketplace is at the repository root). **Branch, tag, or commit:** `main`, or use release tag `v1.0.0` for a fixed version.
4. Authorize a GitHub account with read access to this PRIVATE repository, import, then make **Website Studio** available to your role and install it.

Availability depends on your ChatGPT workspace/client and administrator settings. This repository is a plugin marketplace, not a custom-GPT action/OpenAPI upload. No public directory submission is needed. This skills-only plugin declares no MCP server or connected app. Importing does not provide tools or access your target websites: use the tools and permissions already available in ChatGPT/Codex. The product-account import must be completed in your own account; local validation cannot prove it.

Official instructions: https://help.openai.com/en/articles/20001504-importing-and-syncing-plugin-marketplaces-from-github

## Codex CLI / local desktop source
With GitHub authentication available to Git and a Codex client supporting plugins:
```bash
codex plugin marketplace add PattrnData/website-studio --ref main
codex plugin list --available --json
codex plugin add website-studio@pattrndata-private
```
For a local checkout, replace the first command's source with its directory. Restart the ChatGPT desktop app after adding a local source if its directory does not refresh. Menu availability varies by client; CLI installation is not proof of ChatGPT account installation.

Packaging reference: https://developers.openai.com/plugins/build/plugins

## Use
- “Use Website Studio to create a site from this brief.”
- “Use Website Studio to analyse this URL, read-only.”
- “Refine these pages without changing our brand or stack.”
- “Redesign this site using GSAP and optional Apple Design interaction guidance.”

The plugin chooses only relevant primary references. It does not force React, Apple styling, Motion, smooth scrolling or every animation library. Existing brief/brand/content/stack and target permissions win. Audit mode does not edit or deploy. Do not expect measured scores, browser screenshots or deployed changes unless the host actually exercised those tools.

## Package contents and checks
- `.agents/plugins/marketplace.json`: one private marketplace entry.
- `plugins/website-studio/plugin.json`: portable manifest; `.codex-plugin/plugin.json`: compatibility fallback.
- One discoverable coordinator skill plus workflow/integration/maintenance references.
- One pinned snapshot: six source repositories, 16 inert documentation/metadata/license files; exact byte hashes and upstream revisions preserved. Only the active snapshot is exported; no prior host history.
- Python 3.10+ standard-library helper for optional integrity checks and reference refresh. No Python is needed just to read the skill.

```bash
python3 plugins/website-studio/scripts/website_upstreams.py inspect
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Installed reference mutations are blocked by default; see the skill maintenance reference for explicit workspace refresh/rollback. There is no automatic update job. GitHub-managed marketplace sync follows your workspace's own settings; pin a release tag/commit if you do not want moving-branch updates.

Release archive `website-studio-plugin-v1.0.0.zip` contains the plugin root (not a full project copy). The marketplace lives in the repository; for GitHub import use the repository URL, not the ZIP URL or manifest path. See `PROVENANCE.json` and `THIRD_PARTY_NOTICES.md` in the plugin. Third-party content retains its original terms; in particular React Bits is not plain MIT and GSAP has separate terms. No component/runtime library or stock assets are redistributed as a component pack.