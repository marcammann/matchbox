# Matchbox Frontend

SvelteKit 5 with runes, TypeScript, static adapter. Built output goes to `web/build/` and is served by the FastAPI backend.

## Commands

```
npm install
npm run build    # production build → build/
npm run dev      # dev server on port 5173 (proxy API to localhost:8000)
```

Always run `npm run build` after changes — the backend serves the static build, not a dev server.

## Structure

- `src/lib/api.ts` — All API client functions and TypeScript interfaces (`Job`, `SearchStatus`, `RemoteCompany`). Every backend endpoint has a corresponding function here.
- `src/routes/+layout.svelte` — App shell with nav bar, logo, version badge.
- `src/routes/+page.svelte` — Landing/redirect page.
- `src/routes/jobs/+page.svelte` — Main dashboard. Job list grouped by date, search controls, add job modal, tailor/regenerate buttons, dismissed/rejected sections.
- `src/routes/settings/+page.svelte` — Config page. API keys, resume, profile, search queries, role keywords, target companies (with discovery, Remote In Tech browser, inline URL editing), source toggles, prompts, PDF CSS.
- `src/app.css` — Global styles with CSS custom properties. Light/dark mode via `prefers-color-scheme`. Teal accent in dark mode, blue in light.

## Conventions

- **Svelte 5 runes**: Use `$state()`, `$derived()`, `$derived.by()`. No stores, no `$:` reactivity.
- **Event handlers**: Use `onclick`, `onblur`, `oninput` (lowercase, Svelte 5 style), not `on:click`.
- **API calls**: Always go through `src/lib/api.ts`, never raw `fetch`.
- **Interfaces**: When adding a backend field, update both the TypeScript interface in `api.ts` AND the component state initialization (e.g., `SearchStatus` needs `errors: []` in both the interface and the default state).
- **No component library**: Plain HTML + CSS custom properties. Keep it minimal.
- **CSS scoping**: Each page has a `<style>` block. Shared styles go in `app.css`. Use `var(--name)` for all colors.
