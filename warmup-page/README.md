# TrailMind warm-up page

Standalone static page for judges/reviewers to land on instead of Render's own
"waking up" splash screen. It polls the live app's `/health` endpoint every 2s
and auto-redirects once the Render free-tier instance is awake.

Deploy on Vercel (no build step needed):

```bash
cd warmup-page
npx vercel --prod
```

Or via the Vercel dashboard: "Add New Project" → import this repo → set the
**Root Directory** to `warmup-page` → deploy (framework preset: "Other").

Give judges the Vercel URL instead of the `onrender.com` URL.

If the Render app's URL ever changes, update `APP_URL` in `index.html`.
