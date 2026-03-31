---
name: Landing Page
description: Create a new AILANG Parse documentation/landing page targeting a specific keyword or topic. Use when user says 'new landing page', 'new page for X', 'create a page about X', 'landing page for keyword X', or wants to add a documentation page to the docs/ site. Also use when the user references long-tail keywords, SEO pages, or competitor comparison pages.
---

# Create Landing Page

Generate a new AILANG Parse documentation/landing page that follows the established site conventions, uses shared infrastructure, and targets a specific keyword or topic.

## Before You Start

1. **Identify the target keyword** — ask the user if not provided. Good long-tail keywords for AILANG Parse include:
   - Feature-specific: "extract track changes from docx", "parse excel merged cells"
   - Competitor comparison: "ailang vs unstructured", "llamaparse alternative"
   - Use-case: "document parsing for legal review", "automated contract analysis"
   - Format-specific: "parse odt files programmatically", "extract pptx speaker notes"

2. **Check existing pages** — avoid duplicating content already covered:
   ```bash
   ls docs/*.html
   ```

3. **Read the shared infrastructure** to understand current conventions:
   ```bash
   cat docs/js/site-data.js     # Pricing, formats, site metadata (DP_DATA)
   cat docs/js/components.js    # Header, footer, data-dp, data-src, ensureHead
   ```

## Page Template

Every new page MUST follow this structure. Use [`resources/template.html`](resources/template.html) as the starting point.

### Required Elements

1. **`<head>` section** — must include:
   - `<meta charset="UTF-8">` and viewport meta
   - `<title>` — format: `{Page Title} — AILANG Parse`
   - `<link rel="icon">` pointing to `img/docparse-logo.svg`
   - `<meta name="description">` — 140-160 chars, include the target keyword naturally
   - **OG tags** in raw HTML (not JS-injected — crawlers need them):
     - `og:title`, `og:description`, `og:type` (website), `og:url`
   - Google Fonts preconnect + Montserrat/JetBrains Mono
   - **All 5 CSS files**: `design-system.css`, `docparse.css`, `prism.css`, `docs-layout.css`, `components.css`

2. **`<body>` structure**:
   ```html
   <div id="header-mount"></div>     <!-- components.js injects header -->
   <div class="page">
     <section class="hero">          <!-- Title + subtitle -->
     <div class="dp-docs-layout">    <!-- Sidebar + content -->
       <aside class="dp-docs-sidebar">  <!-- Table of contents -->
       <main class="dp-docs-content">   <!-- Page content -->
     </div>
   </div>
   <div id="footer-mount"></div>     <!-- components.js injects footer -->
   ```

3. **Scripts at bottom** — in this exact order:
   ```html
   <script src="js/site-data.js"></script>
   <script src="js/components.js"></script>
   <script src="js/prism.min.js"></script>
   <script src="js/prism-ailang.js"></script>
   ```

4. **Sidebar scroll tracking** — add this script after the main scripts:
   ```html
   <script>
   (function() {
     var links = document.querySelectorAll('.dp-docs-sidebar a');
     var sections = [];
     links.forEach(function(link) {
       var id = link.getAttribute('href').replace('#', '');
       var sec = document.getElementById(id);
       if (sec) sections.push({ el: sec, link: link });
     });
     function update() {
       var y = window.scrollY + 100;
       var current = null;
       sections.forEach(function(s) { if (s.el.offsetTop <= y) current = s; });
       links.forEach(function(l) { l.classList.remove('active'); });
       if (current) current.link.classList.add('active');
     }
     window.addEventListener('scroll', update, { passive: true });
     update();
   })();
   </script>
   ```

### Using Shared Data

**Pricing/features** — never hardcode. Use `data-dp` attributes:
```html
<span data-dp="pricing.tiers.free.requests_per_month">500</span> requests/month
<span data-dp="formats.input_count">13</span> input formats
```

The inline text is the no-JS fallback. `components.js` replaces it from `DP_DATA`.

Available paths (check `site-data.js` for full list):
- `pricing.tiers.{free,pro,business}.{price_eur,requests_per_day,requests_per_month,ai_requests_per_month,max_file_size_mb}`
- `formats.{input_count,output_count}`

**Code examples** — use external files via `data-src`:
```html
<pre><code class="language-python" data-src="examples/sdk/quickstart.py">
# Inline fallback for no-JS
from ailang_parse import DocParse
</code></pre>
```

If the page needs a NEW code example, create the file in `docs/examples/` and reference it. Existing examples:
- `examples/sdk/quickstart.{py,js,go}` — SDK usage
- `examples/cli/install.sh` — CLI installation
- `examples/cli/parse.sh` — Basic parsing
- `examples/cli/convert.sh` — Format conversion
- `examples/cli/ai-parse.sh` — AI generation
- `examples/api/curl-parse.sh` — curl quick start
- `examples/mcp/claude-desktop-config.json` — MCP config

### SEO Checklist

- [ ] Target keyword appears in: `<title>`, `<meta description>`, `<h1>`, first `<p>`, at least one `<h2>`
- [ ] Meta description is 140-160 characters
- [ ] Page includes FAQ section with `FAQPage` JSON-LD structured data
- [ ] FAQ questions use natural language people actually search for
- [ ] Internal links to related pages (benchmarks, API, track-changes, etc.)
- [ ] Competitor comparison table if relevant (use `dp-config-table` class with `dp-preserved`/`dp-lost` spans)
- [ ] "Try It" CTA section near the bottom linking to the WASM demo and API
- [ ] Page-specific `<style>` block for any custom CSS (use design system variables)
- [ ] Mobile responsive — test with 768px breakpoint

### Content Patterns That Work

Study these existing pages for inspiration:
- **Feature deep-dive**: `comments.html`, `track-changes.html`, `tables.html` — problem/solution/how-it-works/example-output/use-cases/try-it/FAQ
- **Competitor comparison**: `vs-pdf-conversion.html`, `migrate-from-unstructured.html` — side-by-side tables, specific data loss examples
- **Integration guide**: `mcp.html`, `claude-code.html`, `integrations.html` — step-by-step setup with code blocks

### Common CSS Classes

Use these from the design system rather than inline styles:
- `.dp-docs-layout`, `.dp-docs-sidebar`, `.dp-docs-content` — page layout
- `.dp-callout` — info callout box with SVG icon
- `.dp-config-table` — comparison table
- `.dp-preserved` / `.dp-lost` — green/red status badges in tables
- `.dp-btn`, `.dp-btn--primary`, `.dp-btn--secondary` — CTA buttons
- `.dp-faq`, `.dp-faq-answer` — FAQ section
- `.reveal`, `.reveal-delay-1` — scroll-reveal animation
- `.hero`, `.subtitle` — page hero section
- `language-bash`, `language-python`, `language-json`, etc. — Prism syntax classes

## After Creating the Page

1. **Verify locally**:
   ```bash
   cd docs && python3 -m http.server 8765
   # Open http://localhost:8765/your-page.html
   ```

2. **Check mobile** — resize to 768px, verify sidebar collapses and content is readable.

3. **Validate structured data** — paste the JSON-LD into Google's Rich Results Test.

4. **Do NOT add the page to the nav** in `components.js` unless it's a top-level section. Landing pages are discovered via search, not navigation.
