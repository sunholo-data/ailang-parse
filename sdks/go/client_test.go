package docparse

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// ── Helpers ──

// mockServer creates an httptest.Server that returns the given status and body for all requests.
func mockServer(status int, body any) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		json.NewEncoder(w).Encode(body)
	}))
}

// envelope wraps a JSON-serializable value in the serve-api response envelope.
func envelope(inner any) map[string]any {
	data, _ := json.Marshal(inner)
	return map[string]any{"result": string(data)}
}

// ── Client construction ──

func TestNew_ExplicitKey(t *testing.T) {
	c := New("dp_test123")
	if c.APIKey != "dp_test123" {
		t.Fatalf("expected dp_test123, got %s", c.APIKey)
	}
}

func TestNew_EnvVarKey(t *testing.T) {
	t.Setenv("DOCPARSE_API_KEY", "dp_fromenv")
	c := New("")
	if c.APIKey != "dp_fromenv" {
		t.Fatalf("expected dp_fromenv, got %s", c.APIKey)
	}
}

func TestNew_ExplicitOverridesEnv(t *testing.T) {
	t.Setenv("DOCPARSE_API_KEY", "dp_fromenv")
	c := New("dp_explicit")
	if c.APIKey != "dp_explicit" {
		t.Fatalf("expected dp_explicit, got %s", c.APIKey)
	}
}

func TestNew_CustomBaseURL(t *testing.T) {
	c := New("dp_x", WithBaseURL("http://localhost:9999"))
	if c.BaseURL != "http://localhost:9999" {
		t.Fatalf("expected custom URL, got %s", c.BaseURL)
	}
}

// ── Unwrap ──

func TestUnwrap_Success(t *testing.T) {
	c := New("dp_x")
	env := envelope(map[string]string{"status": "ok"})
	data, _ := json.Marshal(env)
	result, err := c.unwrap(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var parsed map[string]string
	json.Unmarshal(result, &parsed)
	if parsed["status"] != "ok" {
		t.Fatalf("expected status ok, got %s", parsed["status"])
	}
}

func TestUnwrap_Error(t *testing.T) {
	c := New("dp_x")
	data := `{"error":"something broke"}`
	_, err := c.unwrap([]byte(data))
	if err == nil {
		t.Fatal("expected error")
	}
}

// ── Health ──

func TestHealth_OK(t *testing.T) {
	ts := mockServer(200, envelope(map[string]any{
		"status":          "ok",
		"version":         "1.2.3",
		"service":         "docparse",
		"formats_parse":   12,
		"formats_generate": 9,
	}))
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	h, err := c.Health(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if h.Status != "ok" {
		t.Fatalf("expected ok, got %s", h.Status)
	}
	if h.Version != "1.2.3" {
		t.Fatalf("expected 1.2.3, got %s", h.Version)
	}
}

// ── Formats ──

func TestFormats_OK(t *testing.T) {
	ts := mockServer(200, envelope(map[string]any{
		"parse":       []string{"docx", "pdf", "html"},
		"generate":    []string{"docx", "html"},
		"ai_required": []string{"pdf"},
	}))
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	f, err := c.Formats(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(f.Parse) != 3 {
		t.Fatalf("expected 3 parse formats, got %d", len(f.Parse))
	}
	if f.AIRequired[0] != "pdf" {
		t.Fatalf("expected pdf in ai_required, got %v", f.AIRequired)
	}
}

// ── Parse ──

func TestParse_OK(t *testing.T) {
	ts := mockServer(200, envelope(map[string]any{
		"status":   "ok",
		"filename": "sample.docx",
		"format":   "docx",
		"blocks": []map[string]any{
			{"type": "heading", "text": "Title", "level": 1},
			{"type": "text", "text": "Body paragraph"},
		},
		"metadata": map[string]any{"title": "Sample", "author": "Test"},
		"summary":  map[string]any{"totalBlocks": 2, "headings": 1},
	}))
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	r, err := c.Parse(context.Background(), "sample.docx")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if r.Status != "ok" {
		t.Fatalf("expected ok, got %s", r.Status)
	}
	if len(r.Blocks) != 2 {
		t.Fatalf("expected 2 blocks, got %d", len(r.Blocks))
	}
	if r.Blocks[0].Type != "heading" {
		t.Fatalf("expected heading, got %s", r.Blocks[0].Type)
	}
	if r.Metadata.Title != "Sample" {
		t.Fatalf("expected Sample, got %s", r.Metadata.Title)
	}
}

// ── Error handling ──

func TestError_401(t *testing.T) {
	ts := mockServer(401, map[string]any{"error": "unauthorized"})
	defer ts.Close()

	c := New("dp_bad", WithBaseURL(ts.URL))
	_, err := c.Health(context.Background())
	if err == nil {
		t.Fatal("expected error on 401")
	}
}

func TestError_429(t *testing.T) {
	ts := mockServer(429, map[string]any{"error": "quota exceeded"})
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	_, err := c.Health(context.Background())
	if err == nil {
		t.Fatal("expected error on 429")
	}
}

func TestError_Envelope(t *testing.T) {
	ts := mockServer(200, map[string]any{"error": "parse failed"})
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	_, err := c.Parse(context.Background(), "bad.docx")
	if err == nil {
		t.Fatal("expected error from envelope")
	}
}

func TestError_500(t *testing.T) {
	ts := mockServer(500, map[string]any{"error": "internal"})
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	_, err := c.Health(context.Background())
	if err == nil {
		t.Fatal("expected error on 500")
	}
}

// ── Unstructured compat ──

func TestUnstructuredPartition(t *testing.T) {
	ts := mockServer(200, envelope([]map[string]any{
		{"type": "NarrativeText", "element_id": "abc", "text": "Hello", "metadata": map[string]any{"filename": "test.docx"}},
		{"type": "Title", "element_id": "def", "text": "Heading", "metadata": map[string]any{}},
	}))
	defer ts.Close()

	uc := NewUnstructuredClient(ts.URL, "dp_test")
	elements, err := uc.Partition(context.Background(), "sample.docx")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(elements) != 2 {
		t.Fatalf("expected 2 elements, got %d", len(elements))
	}
	if elements[0].Type != "NarrativeText" {
		t.Fatalf("expected NarrativeText, got %s", elements[0].Type)
	}
}

// ── Type JSON round-trip ──

func TestBlockJSON(t *testing.T) {
	raw := `{"type":"table","headers":[{"text":"A"},{"text":"B"}],"rows":[[{"text":"1"},{"text":"2","colSpan":2,"merged":true}]]}`
	var b Block
	if err := json.Unmarshal([]byte(raw), &b); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if b.Type != "table" {
		t.Fatalf("expected table, got %s", b.Type)
	}
	if len(b.Headers) != 2 {
		t.Fatalf("expected 2 headers, got %d", len(b.Headers))
	}
	if b.Rows[0][1].ColSpan != 2 {
		t.Fatalf("expected colSpan 2, got %d", b.Rows[0][1].ColSpan)
	}
}

func TestParseResultJSON(t *testing.T) {
	raw := `{"status":"ok","filename":"test.docx","format":"docx","blocks":[{"type":"text","text":"hi"}],"metadata":{"title":"T"},"summary":{"totalBlocks":1}}`
	var r ParseResult
	if err := json.Unmarshal([]byte(raw), &r); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if r.Status != "ok" {
		t.Fatalf("expected ok, got %s", r.Status)
	}
	if len(r.Blocks) != 1 {
		t.Fatalf("expected 1 block, got %d", len(r.Blocks))
	}
	if r.Metadata.Title != "T" {
		t.Fatalf("expected T, got %s", r.Metadata.Title)
	}
}

func TestKeyInfoJSON(t *testing.T) {
	raw := `{"status":"active","key":"dp_abc","keyId":"k1","label":"test","tier":"free","quota":{"requestsPerDay":50}}`
	var k KeyInfo
	if err := json.Unmarshal([]byte(raw), &k); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if k.Key != "dp_abc" {
		t.Fatalf("expected dp_abc, got %s", k.Key)
	}
	if k.Quota.RequestsPerDay != 50 {
		t.Fatalf("expected 50, got %d", k.Quota.RequestsPerDay)
	}
}
