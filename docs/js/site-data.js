/**
 * AILANG Parse — Central Data Layer
 *
 * Single source of truth for pricing, formats, and site metadata.
 * All pages load this file before components.js.
 *
 * The plan tiers and the format lists are written from the hosted API
 * (/api/v1/pricing, /api/v1/formats) by docs/scripts/sync-site-data.py.
 * Do not edit the marked blocks by hand; pages bind to them with data-dp.
 */
var DP_DATA = {
  version: "0.20.0",
  ailangVersion: "v0.54.18",
  pricing: {
    tiers: {
      browser: {
        price_eur: 0,
        daily_rate_limit: 1000000,
        requests_per_month: 1000000,
        ai_requests_per_month: 1000000,
        max_file_size_mb: 20,
        ai_file_size_limits: { video_mb: 20, audio_mb: 20, pdf_mb: 20, image_mb: 20 },

        support: 'Community'
      },
      /* api:tiers */
      free: {
        "price_eur": 0,
        "daily_rate_limit": 50,
        "requests_per_month": 1000,
        "ai_requests_per_month": 50,
        "max_file_size_mb": 10,
        "ai_file_size_limits": {
          "pdf_mb": 10,
          "image_mb": 10
        },
        "ai_budget_per_request": 10,
        "history_retention_days": 30,
        "history_replay": true,
        "gcs_upload": false,
        "support": "Community"
      },
      pro: {
        "price_eur": 29,
        "daily_rate_limit": 5000,
        "requests_per_month": 100000,
        "ai_requests_per_month": 500,
        "max_file_size_mb": 25,
        "ai_file_size_limits": {
          "pdf_mb": 25,
          "image_mb": 25
        },
        "ai_budget_per_request": 50,
        "history_retention_days": 180,
        "history_replay": true,
        "gcs_upload": false,
        "support": "Email"
      },
      business: {
        "price_eur": 99,
        "daily_rate_limit": 20000,
        "requests_per_month": 500000,
        "ai_requests_per_month": 2000,
        "max_file_size_mb": 50,
        "ai_file_size_limits": {
          "pdf_mb": 50,
          "image_mb": 50
        },
        "ai_budget_per_request": 200,
        "history_retention_days": 365,
        "history_replay": true,
        "gcs_upload": true,
        "max_direct_upload_mb": 32,
        "support": "Dedicated"
      }
      /* /api:tiers */
    }
  },
  /* api:formats */
  formats: {
    "input": [
      "DOCX",
      "PPTX",
      "XLSX",
      "ODT",
      "ODP",
      "ODS",
      "HTML",
      "MD",
      "CSV",
      "EPUB",
      "EML",
      "MBOX",
      "TEX",
      "RTF",
      "PDF",
      "PNG",
      "JPG"
    ],
    "generate": [
      "DOCX",
      "PPTX",
      "XLSX",
      "ODT",
      "ODP",
      "ODS",
      "HTML",
      "MD",
      "QMD"
    ],
    "parse_output": [
      "blocks",
      "markdown",
      "html",
      "a2ui"
    ],
    "ai_required": [
      "PNG",
      "JPG",
      "GIF",
      "BMP",
      "TIFF"
    ],
    "ai_on_request": [
      "PDF"
    ],
    "input_count": 17,
    "generate_count": 9,
    "parse_output_count": 4,
    "output": [
      "DOCX",
      "PPTX",
      "XLSX",
      "ODT",
      "ODP",
      "ODS",
      "HTML",
      "MD",
      "QMD"
    ],
    "output_count": 9
  },/* /api:formats */
  page_estimates: {
    avg_page_size_kb: { office: 50, pdf: 100 },
    methodology: 'Office: ~50 KB/page average (compressed XML with typical formatting). PDF: ~100 KB/page average (text-based with mixed content). Actual pages vary by content — text-heavy documents yield more pages, image-heavy fewer.'
  },
  site: {
    name: 'AILANG Parse',
    tagline: 'Universal Document Parsing',
    base_url: 'https://www.sunholo.com/ailang-parse',
    api_url: 'https://docparse.ailang.sunholo.com',
    og_image: 'img/docparse-og.png'
  }
};

/**
 * Helper: resolve a dotted path like "pricing.tiers.free.daily_rate_limit"
 * against DP_DATA. Returns undefined if any segment is missing.
 */
function dpResolve(path) {
  var parts = path.split('.');
  var val = DP_DATA;
  for (var i = 0; i < parts.length; i++) {
    if (val == null) return undefined;
    val = val[parts[i]];
  }
  return val;
}

/**
 * Format a DP_DATA value for display.
 * -1 → "Unlimited", large numbers get toLocaleString().
 */
function dpFormat(val) {
  if (val === -1 || val >= 1000000) return 'Unlimited';
  if (typeof val === 'number' && val >= 1000) return val.toLocaleString();
  return String(val);
}
