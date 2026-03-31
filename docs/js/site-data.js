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
  pricing: {
    tiers: {
      free: {
        price_eur: 0,
        requests_per_day: 60,
        pages_per_month: 500,
        max_file_mb: 10,
        ai_per_request: 5,
        fs_ops_per_request: 100,
        concurrent: 1,
        rate_limit: '1 req/s',
        support: 'Community'
      },
      pro: {
        price_eur: 29,
        requests_per_day: 5000,
        pages_per_month: 10000,
        max_file_mb: 50,
        ai_per_request: 50,
        fs_ops_per_request: 5000,
        concurrent: 5,
        rate_limit: '10 req/s',
        support: 'Email'
      },
      business: {
        price_eur: 99,
        requests_per_day: -1,
        pages_per_month: 50000,
        max_file_mb: 200,
        ai_per_request: 500,
        fs_ops_per_request: 50000,
        concurrent: 20,
        rate_limit: '100 req/s',
        support: 'Dedicated'
      }
    },
    credits: {
      office_parse: 1,
      pdf_parse: 3,
      image_parse: 3,
      audio_parse: 5,
      video_parse: 10,
      document_generate: 10
    }
  },
  formats: {
    input: ['DOCX', 'PPTX', 'XLSX', 'ODT', 'ODP', 'ODS', 'CSV', 'MD', 'HTML', 'EPUB', 'PDF', 'PNG', 'JPG'],
    output: ['JSON', 'Markdown', 'HTML', 'Text', 'Quarto', 'A2UI', 'Unstructured', 'DOCX', 'PPTX'],
    input_count: 13,
    output_count: 9
  },
  site: {
    name: 'AILANG Parse',
    tagline: 'Universal Document Parsing',
    base_url: 'https://www.sunholo.com/docparse',
    og_image: 'img/docparse-og.png'
  }
};

/**
 * Helper: resolve a dotted path like "pricing.tiers.free.requests_per_day"
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
