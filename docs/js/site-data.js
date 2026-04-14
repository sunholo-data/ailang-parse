/**
 * AILANG Parse — Central Data Layer
 *
 * Single source of truth for pricing, formats, and site metadata.
 * All pages load this file before components.js.
 *
 * Source: v0.9.0 design doc (/api/v1/pricing endpoint spec).
 * To update pricing, change values here — they propagate via data-dp attributes.
 */
var DP_DATA = {
  version: "0.8.2",
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
      free: {
        price_eur: 0,
        daily_rate_limit: 50,
        requests_per_month: 1000,
        ai_requests_per_month: 50,
        max_file_size_mb: 10,
        ai_file_size_limits: { pdf_mb: 10, image_mb: 10 },
        gcs_upload: false,
        support: 'Community'
      },
      pro: {
        price_eur: 29,
        daily_rate_limit: 5000,
        requests_per_month: 100000,
        ai_requests_per_month: 500,
        max_file_size_mb: 25,
        ai_file_size_limits: { pdf_mb: 25, image_mb: 25 },
        gcs_upload: false,
        support: 'Email'
      },
      business: {
        price_eur: 99,
        daily_rate_limit: 20000,
        requests_per_month: 500000,
        ai_requests_per_month: 2000,
        max_file_size_mb: 50,
        ai_file_size_limits: { pdf_mb: 50, image_mb: 50 },
        gcs_upload: true,
        support: 'Dedicated'
      }
    }
  },
  formats: {
    input: ['DOCX', 'PPTX', 'XLSX', 'ODT', 'ODP', 'ODS', 'CSV', 'MD', 'HTML', 'EPUB', 'EML', 'TEX', 'PDF', 'PNG', 'JPG'],
    output: ['JSON', 'Markdown', 'HTML', 'Text', 'Quarto', 'A2UI', 'Unstructured', 'DOCX', 'PPTX'],
    input_count: 15,
    output_count: 9
  },
  page_estimates: {
    avg_page_size_kb: { office: 50, pdf: 100 },
    methodology: 'Office: ~50 KB/page average (compressed XML with typical formatting). PDF: ~100 KB/page average (text-based with mixed content). Actual pages vary by content — text-heavy documents yield more pages, image-heavy fewer.'
  },
  site: {
    name: 'AILANG Parse',
    tagline: 'Universal Document Parsing',
    base_url: 'https://www.sunholo.com/docparse',
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
