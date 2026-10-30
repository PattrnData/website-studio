# Website Studio plugin

Private, skills-only website workflow for ChatGPT and Codex. Invoke Website Studio to create, analyse, refine or redesign a website. Guidance selectively uses pinned Impeccable, Taste, React Bits, GSAP, Lenis and Apple Design references.

Install through the private repository marketplace; see the repository README. The plugin root has both a portable Agent Plugins manifest and a Codex compatibility manifest. It requires no MCP server, API key, daemon, scheduler or runtime animation packages. Actual website builds/browser checks depend on tools available in the host client.

Optional offline source verification, from this directory:
```bash
python3 scripts/website_upstreams.py inspect
```

See `skills/website-studio/references/maintenance.md` for read-only online checks and explicit workspace staging. Raw upstream reference SKILL files are outside `skills/`, not auto-activated. The bundled CLI refuses to update its installed source store. Follow `THIRD_PARTY_NOTICES.md`; original Pattrn Data coordination is private, and upstream material retains its own terms.