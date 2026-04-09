package docparse

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
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
	// Non-auth envelope error must NOT match ErrAuth
	if errors.Is(err, ErrAuth) {
		t.Fatalf("non-auth message should not be auth error: %v", err)
	}
}

func TestUnwrap_AuthErrorEnvelope(t *testing.T) {
	c := New("dp_x")
	_, err := c.unwrap([]byte(`{"error":"Invalid or expired API key"}`))
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
	var ae *AuthError
	if !errors.As(err, &ae) {
		t.Fatalf("expected *AuthError, got %T", err)
	}
}

func TestUnwrap_InnerAuthErrorEnvelope(t *testing.T) {
	c := New("dp_x")
	inner := `{"error":{"message":"Invalid or expired API key"}}`
	envBytes, _ := json.Marshal(map[string]string{"result": inner})
	_, err := c.unwrap(envBytes)
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
}

func TestUnwrap_UnauthorizedEnvelope(t *testing.T) {
	c := New("dp_x")
	_, err := c.unwrap([]byte(`{"error":"Unauthorized"}`))
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
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
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
	var ae *AuthError
	if !errors.As(err, &ae) {
		t.Fatalf("expected *AuthError, got %T", err)
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
	if !errors.Is(err, ErrQuota) {
		t.Fatalf("expected ErrQuota, got %v", err)
	}
	var qe *QuotaError
	if !errors.As(err, &qe) {
		t.Fatalf("expected *QuotaError, got %T", err)
	}
}

func TestError_AuthEnvelopeOn200(t *testing.T) {
	// Server returns 200 but with an auth-error string in the envelope —
	// this is the actual production failure mode.
	ts := mockServer(200, map[string]any{"error": "Invalid or expired API key"})
	defer ts.Close()

	c := New("dp_bad", WithBaseURL(ts.URL))
	_, err := c.Parse(context.Background(), "sample.docx")
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
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

// ── KeyManager ──

func TestKeyManager_List(t *testing.T) {
	ts := mockServer(200, envelope(map[string]any{
		"status": "ok",
		"keys":   []map[string]string{{"key_id": "k1"}},
	}))
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	out, err := c.Keys.List(context.Background(), "u1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	var parsed map[string]any
	json.Unmarshal(out, &parsed)
	if parsed["status"] != "ok" {
		t.Fatalf("expected status ok, got %v", parsed["status"])
	}
}

func TestKeyManager_Revoke(t *testing.T) {
	ts := mockServer(200, envelope(map[string]string{"status": "revoked"}))
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	if err := c.Keys.Revoke(context.Background(), "k1", "u1"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestKeyManager_Rotate(t *testing.T) {
	ts := mockServer(200, envelope(map[string]any{
		"status":  "active",
		"key":     "dp_newkey",
		"keyId":   "k2",
		"label":   "rotated",
		"tier":    "free",
		"created": "2026-04-08",
		"quota":   map[string]int{"requestsPerDay": 50},
	}))
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	info, err := c.Keys.Rotate(context.Background(), "k1", "u1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if info.Key != "dp_newkey" {
		t.Fatalf("expected dp_newkey, got %s", info.Key)
	}
	if info.Quota.RequestsPerDay != 50 {
		t.Fatalf("expected 50, got %d", info.Quota.RequestsPerDay)
	}
}

func TestKeyManager_Usage(t *testing.T) {
	ts := mockServer(200, envelope(map[string]any{
		"status": "ok",
		"keyId":  "k1",
		"tier":   "free",
		"usage":  map[string]int{"requestsToday": 3, "requestsThisMonth": 10, "totalRequests": 100},
		"quota":  map[string]int{"requestsPerDay": 50},
	}))
	defer ts.Close()

	c := New("dp_test", WithBaseURL(ts.URL))
	u, err := c.Keys.Usage(context.Background(), "k1", "u1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if u.Usage.RequestsToday != 3 {
		t.Fatalf("expected 3, got %d", u.Usage.RequestsToday)
	}
}

func TestKeyManager_PropagatesAuthErrorFromEnvelope(t *testing.T) {
	ts := mockServer(200, map[string]any{"error": "Invalid or expired API key"})
	defer ts.Close()

	c := New("dp_bad", WithBaseURL(ts.URL))
	_, err := c.Keys.List(context.Background(), "u1")
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
}

// ── ParseFile multipart upload ──

func TestParseFile_UploadsLocalFile(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify it's a multipart upload
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
			t.Errorf("expected multipart Content-Type, got %s", r.Header.Get("Content-Type"))
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		json.NewEncoder(w).Encode(envelope(map[string]any{
			"status":   "ok",
			"filename": "upload.docx",
			"format":   "docx",
			"blocks":   []map[string]any{{"type": "text", "text": "hello"}},
			"metadata": map[string]any{},
			"summary":  map[string]any{"totalBlocks": 1},
		}))
	}))
	defer ts.Close()

	dir := t.TempDir()
	local := filepath.Join(dir, "upload.docx")
	if err := os.WriteFile(local, []byte("PK\x03\x04 fake"), 0644); err != nil {
		t.Fatal(err)
	}

	c := New("dp_test", WithBaseURL(ts.URL))
	r, err := c.ParseFile(context.Background(), local)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if r.Status != "ok" {
		t.Fatalf("expected ok, got %s", r.Status)
	}
	if r.Blocks[0].Text != "hello" {
		t.Fatalf("expected hello, got %s", r.Blocks[0].Text)
	}
}

func TestParseFile_AuthErrorOn401(t *testing.T) {
	ts := mockServer(401, map[string]any{"error": "unauthorized"})
	defer ts.Close()

	dir := t.TempDir()
	local := filepath.Join(dir, "upload.docx")
	os.WriteFile(local, []byte("fake"), 0644)

	c := New("dp_bad", WithBaseURL(ts.URL))
	_, err := c.ParseFile(context.Background(), local)
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
}

func TestParseFile_AuthErrorOnEnvelope200(t *testing.T) {
	ts := mockServer(200, map[string]any{"error": "Invalid or expired API key"})
	defer ts.Close()

	dir := t.TempDir()
	local := filepath.Join(dir, "upload.docx")
	os.WriteFile(local, []byte("fake"), 0644)

	c := New("dp_bad", WithBaseURL(ts.URL))
	_, err := c.ParseFile(context.Background(), local)
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
}

// ── Compat (Unstructured) ──

func TestCompat_Partition_AuthErrorOnEnvelope(t *testing.T) {
	ts := mockServer(200, map[string]any{"error": "Invalid or expired API key"})
	defer ts.Close()

	uc := NewUnstructuredClient(ts.URL, "dp_bad")
	_, err := uc.Partition(context.Background(), "sample.docx")
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
}

func TestCompat_Partition_401(t *testing.T) {
	ts := mockServer(401, map[string]any{"error": "unauthorized"})
	defer ts.Close()

	uc := NewUnstructuredClient(ts.URL, "dp_bad")
	_, err := uc.Partition(context.Background(), "sample.docx")
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
}

// ── Credentials file ──

func TestCredentials_SaveAndLoadRoundTrip(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)

	if err := saveKey("dp_round_trip", "https://example.test", "k1", "pro", "laptop"); err != nil {
		t.Fatalf("save: %v", err)
	}
	loaded := loadSavedKey("https://example.test")
	if loaded == nil {
		t.Fatal("expected to load saved key")
	}
	if loaded.APIKey != "dp_round_trip" || loaded.Tier != "pro" || loaded.Label != "laptop" {
		t.Fatalf("round-trip mismatch: %+v", loaded)
	}
}

func TestCredentials_LoadReturnsNilWhenMissing(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)
	if loadSavedKey("https://example.test") != nil {
		t.Fatal("expected nil for missing credentials")
	}
}

func TestCredentials_LoadFiltersByBaseURL(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)

	saveKey("dp_a", "https://a.test", "", "free", "")
	if loadSavedKey("https://b.test") != nil {
		t.Fatal("expected nil for mismatched base URL")
	}
	if loadSavedKey("https://a.test") == nil {
		t.Fatal("expected hit for matching base URL")
	}
}

func TestCredentials_LoadRejectsNonDPPrefix(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)

	credPath := filepath.Join(tmp, "ailang-parse", "credentials.json")
	os.MkdirAll(filepath.Dir(credPath), 0700)
	os.WriteFile(credPath, []byte(`{"api_key":"garbage_no_prefix","base_url":"https://x.test"}`), 0600)

	if loadSavedKey("https://x.test") != nil {
		t.Fatal("expected nil for non-dp_ prefix")
	}
}

func TestCredentials_LoadRejectsMalformedJSON(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)

	credPath := filepath.Join(tmp, "ailang-parse", "credentials.json")
	os.MkdirAll(filepath.Dir(credPath), 0700)
	os.WriteFile(credPath, []byte("{not json"), 0600)

	if loadSavedKey("https://x.test") != nil {
		t.Fatal("expected nil for malformed JSON")
	}
}

func TestCredentials_ResolveAPIKeyPrefersEnv(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)
	t.Setenv("DOCPARSE_API_KEY", "dp_env_wins")

	saveKey("dp_disk", "https://x.test", "", "free", "")
	if got := ResolveAPIKey(); got != "dp_env_wins" {
		t.Fatalf("expected dp_env_wins, got %s", got)
	}
}

func TestCredentials_ResolveAPIKeyFallsBackToDisk(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)
	os.Unsetenv("DOCPARSE_API_KEY")

	saveKey("dp_disk", "https://x.test", "", "free", "")
	if got := ResolveAPIKey(); got != "dp_disk" {
		t.Fatalf("expected dp_disk, got %s", got)
	}
}

func TestCredentials_ClientPicksUpSavedKey(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", tmp)
	os.Unsetenv("DOCPARSE_API_KEY")

	saveKey("dp_from_disk", "https://disk.test", "", "free", "")
	c := New("", WithBaseURL("https://disk.test"))
	if c.APIKey != "dp_from_disk" {
		t.Fatalf("expected dp_from_disk, got %s", c.APIKey)
	}
}

// ── #2 Markdown raw-string handling ──

func TestParse_MarkdownReturnsText(t *testing.T) {
	srv := mockServer(200, map[string]any{"result": "# Title\n\nBody paragraph\n"})
	defer srv.Close()
	c := New("dp_test", WithBaseURL(srv.URL))
	r, err := c.Parse(context.Background(), "doc.md", ParseOptions{OutputFormat: "markdown"})
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if r.Text != "# Title\n\nBody paragraph\n" {
		t.Fatalf("expected raw markdown in Text, got %q", r.Text)
	}
	if r.Format != "markdown" {
		t.Fatalf("expected format=markdown, got %q", r.Format)
	}
	if len(r.Blocks) != 0 {
		t.Fatalf("expected empty blocks, got %d", len(r.Blocks))
	}
	if r.Status != "ok" {
		t.Fatalf("expected status=ok, got %q", r.Status)
	}
}

func TestParseFile_HTMLReturnsText(t *testing.T) {
	srv := mockServer(200, map[string]any{"result": "<h1>Title</h1>"})
	defer srv.Close()
	dir := t.TempDir()
	local := filepath.Join(dir, "doc.html")
	if err := os.WriteFile(local, []byte("<h1>x</h1>"), 0644); err != nil {
		t.Fatal(err)
	}
	c := New("dp_test", WithBaseURL(srv.URL))
	r, err := c.ParseFile(context.Background(), local, ParseOptions{OutputFormat: "html"})
	if err != nil {
		t.Fatalf("parse_file: %v", err)
	}
	if r.Text != "<h1>Title</h1>" {
		t.Fatalf("expected raw html in Text, got %q", r.Text)
	}
	if r.Format != "html" {
		t.Fatalf("expected format=html, got %q", r.Format)
	}
}

// ── #6 FormatsResult helpers ──

func TestFormatsResult_Supports(t *testing.T) {
	f := &FormatsResult{
		Parse:      []string{"docx", "pdf", "html"},
		Generate:   []string{"docx", "html"},
		AIRequired: []string{"pdf"},
	}
	cases := []struct {
		fmt, op string
		want    bool
	}{
		{"docx", "parse", true},
		{"DOCX", "parse", true},
		{".docx", "parse", true},
		{"xlsx", "parse", false},
		{"pdf", "generate", false},
		{"html", "generate", true},
	}
	for _, tc := range cases {
		if got := f.Supports(tc.fmt, tc.op); got != tc.want {
			t.Errorf("Supports(%q, %q) = %v, want %v", tc.fmt, tc.op, got, tc.want)
		}
	}
}

func TestFormatsResult_IsDeterministic(t *testing.T) {
	f := &FormatsResult{
		Parse:      []string{"docx", "pdf"},
		AIRequired: []string{"pdf"},
	}
	if !f.IsDeterministic("docx") {
		t.Error("docx should be deterministic")
	}
	if f.IsDeterministic("pdf") {
		t.Error("pdf is in ai_required, should not be deterministic")
	}
	if f.IsDeterministic("xlsx") {
		t.Error("xlsx not supported, should not be deterministic")
	}
	if !f.IsDeterministic(".DOCX") {
		t.Error("case + dot tolerance failed")
	}
}

// ── #8 KeyInfo ──

func TestKeyInfo_FallsBackToList(t *testing.T) {
	// Server returns a keys.list response with two keys; the matching one
	// should be picked up. We then stub out Usage by replacing the handler
	// after the first request.
	var calls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/keys/list") {
			body := envelope(map[string]any{
				"status": "ok",
				"keys": []map[string]any{
					{"key_id": "k_other", "key": "dp_other"},
					{"key_id": "k_match", "key": "dp_test"},
				},
			})
			json.NewEncoder(w).Encode(body)
			return
		}
		// usage
		body := envelope(map[string]any{
			"status": "ok",
			"keyId":  "k_match",
			"tier":   "free",
			"usage":  map[string]any{"requestsToday": 5},
		})
		json.NewEncoder(w).Encode(body)
	}))
	defer srv.Close()

	c := New("dp_test", WithBaseURL(srv.URL))
	info, err := c.KeyInfo(context.Background())
	if err != nil {
		t.Fatalf("KeyInfo: %v", err)
	}
	if c.KeyID != "k_match" {
		t.Fatalf("expected cached KeyID=k_match, got %q", c.KeyID)
	}
	if info.Usage.RequestsToday != 5 {
		t.Fatalf("expected requests_today=5, got %d", info.Usage.RequestsToday)
	}
	// Second call: should skip the list lookup (one fewer call than first time)
	prev := calls
	if _, err := c.KeyInfo(context.Background()); err != nil {
		t.Fatalf("second KeyInfo: %v", err)
	}
	if calls-prev != 1 {
		t.Fatalf("second call should hit /keys/usage only (1 request), got %d", calls-prev)
	}
}

func TestKeyInfo_NoAPIKeyErrors(t *testing.T) {
	t.Setenv("DOCPARSE_API_KEY", "")
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	c := New("", WithBaseURL("http://nokey.test"))
	_, err := c.KeyInfo(context.Background())
	if err == nil {
		t.Fatal("expected error when no api key")
	}
	var dpe *DocParseError
	if !errors.As(err, &dpe) {
		t.Fatalf("expected DocParseError, got %T", err)
	}
}

// ── #5 DeviceAuth poll URL ──
//
// We can't easily run the full poll loop in a test, but we can at least
// confirm the result struct exposes the new fields and they get populated
// when the device-poll endpoint reports approved on the first try.
func TestDeviceAuth_ReturnsURLs(t *testing.T) {
	var step int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch step {
		case 0:
			step++
			json.NewEncoder(w).Encode(envelope(map[string]any{
				"device_code":      "DCODE",
				"user_code":        "UCODE",
				"verification_url": "https://example.test/verify",
				"interval":         1,
			}))
		default:
			json.NewEncoder(w).Encode(envelope(map[string]any{
				"status":  "approved",
				"api_key": "dp_new",
				"key_id":  "k_new",
				"tier":    "free",
				"label":   "test",
			}))
		}
	}))
	defer srv.Close()

	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	c := New("", WithBaseURL(srv.URL))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	res, err := c.DeviceAuth(ctx, "test")
	if err != nil {
		t.Fatalf("DeviceAuth: %v", err)
	}
	if res.VerificationURL != "https://example.test/verify" {
		t.Errorf("expected verification_url, got %q", res.VerificationURL)
	}
	if res.PollURL != srv.URL+"/api/v1/auth/device/poll" {
		t.Errorf("expected poll_url, got %q", res.PollURL)
	}
	if c.KeyID != "k_new" {
		t.Errorf("expected client.KeyID=k_new, got %q", c.KeyID)
	}
}

// ── markdown+metadata ──

func TestParse_MarkdownMetadata(t *testing.T) {
	inner := map[string]any{
		"format":   "markdown+metadata",
		"filename": "report.docx",
		"markdown": "# Title\n\nBody paragraph",
		"metadata": map[string]any{"title": "Report", "author": "Alice"},
		"summary":  map[string]any{"totalBlocks": 3, "headings": 1},
		"sections": []map[string]any{
			{"heading": "", "level": 0, "markdown": "Preamble"},
			{"heading": "Title", "level": 1, "markdown": "Body paragraph"},
		},
	}
	srv := mockServer(200, envelope(inner))
	defer srv.Close()
	c := New("dp_test", WithBaseURL(srv.URL))
	r, err := c.Parse(context.Background(), "report.docx", ParseOptions{OutputFormat: "markdown+metadata"})
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if r.Status != "ok" {
		t.Fatalf("expected status=ok, got %q", r.Status)
	}
	if r.Format != "markdown+metadata" {
		t.Fatalf("expected format=markdown+metadata, got %q", r.Format)
	}
	if r.Markdown != "# Title\n\nBody paragraph" {
		t.Fatalf("expected markdown body, got %q", r.Markdown)
	}
	if r.Metadata.Title != "Report" {
		t.Fatalf("expected metadata.title=Report, got %q", r.Metadata.Title)
	}
	if len(r.Sections) != 2 {
		t.Fatalf("expected 2 sections, got %d", len(r.Sections))
	}
	if r.Sections[1].Heading != "Title" || r.Sections[1].Level != 1 {
		t.Fatalf("unexpected section[1]: %+v", r.Sections[1])
	}
}

func TestStructuredErrorCarriesSuggestedFix(t *testing.T) {
	srv := mockServer(200, map[string]any{
		"error":         "AUTH_REQUIRED",
		"message":       "An API key is required.",
		"suggested_fix": "Call mcpAuth to start device authorization.",
	})
	defer srv.Close()
	c := New("", WithBaseURL(srv.URL))
	_, err := c.Health(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	var dpe *DocParseError
	if !errors.As(err, &dpe) {
		t.Fatalf("expected DocParseError, got %T", err)
	}
	if dpe.SuggestedFix != "Call mcpAuth to start device authorization." {
		t.Fatalf("expected suggested_fix, got %q", dpe.SuggestedFix)
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

// ── extractResponseMeta ──

func TestExtractResponseMeta(t *testing.T) {
	h := http.Header{}
	h.Set("X-Request-Id", "req_abc123")
	h.Set("X-DocParse-Tier", "pro")
	h.Set("X-DocParse-Quota-Remaining-Day", "195")
	h.Set("X-DocParse-Quota-Remaining-Month", "9800")
	h.Set("X-DocParse-Quota-Remaining-Ai", "450")
	h.Set("X-AilangParse-Format", "docx")
	h.Set("X-AilangParse-Replayable", "true")

	meta := extractResponseMeta(h)
	if meta.RequestID != "req_abc123" {
		t.Fatalf("expected req_abc123, got %s", meta.RequestID)
	}
	if meta.Tier != "pro" {
		t.Fatalf("expected pro, got %s", meta.Tier)
	}
	if meta.QuotaRemainingDay != 195 {
		t.Fatalf("expected 195, got %d", meta.QuotaRemainingDay)
	}
	if meta.QuotaRemainingMonth != 9800 {
		t.Fatalf("expected 9800, got %d", meta.QuotaRemainingMonth)
	}
	if meta.QuotaRemainingAI != 450 {
		t.Fatalf("expected 450, got %d", meta.QuotaRemainingAI)
	}
	if meta.Format != "docx" {
		t.Fatalf("expected docx, got %s", meta.Format)
	}
	if !meta.Replayable {
		t.Fatal("expected replayable=true")
	}
}

func TestExtractResponseMeta_Empty(t *testing.T) {
	meta := extractResponseMeta(http.Header{})
	if meta.RequestID != "" {
		t.Fatalf("expected empty RequestID, got %s", meta.RequestID)
	}
	if meta.Tier != "" {
		t.Fatalf("expected empty Tier, got %s", meta.Tier)
	}
	if meta.QuotaRemainingDay != -1 {
		t.Fatalf("expected -1 for QuotaRemainingDay, got %d", meta.QuotaRemainingDay)
	}
	if meta.QuotaRemainingMonth != -1 {
		t.Fatalf("expected -1 for QuotaRemainingMonth, got %d", meta.QuotaRemainingMonth)
	}
	if meta.QuotaRemainingAI != -1 {
		t.Fatalf("expected -1 for QuotaRemainingAI, got %d", meta.QuotaRemainingAI)
	}
	if meta.Format != "" {
		t.Fatalf("expected empty Format, got %s", meta.Format)
	}
	if meta.Replayable {
		t.Fatal("expected replayable=false for empty headers")
	}
}

// ── SourceURL in Parse ──

func TestParse_SourceURL(t *testing.T) {
	var receivedBody map[string]string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&receivedBody)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(envelope(map[string]any{
			"status":   "ok",
			"filename": "remote.pdf",
			"format":   "pdf",
			"blocks":   []map[string]any{{"type": "text", "text": "from url"}},
			"metadata": map[string]any{},
			"summary":  map[string]any{"totalBlocks": 1},
		}))
	}))
	defer srv.Close()

	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.Parse(context.Background(), "", ParseOptions{SourceURL: "https://example.com/doc.pdf"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if receivedBody["sourceUrl"] != "https://example.com/doc.pdf" {
		t.Fatalf("expected sourceUrl in body, got %v", receivedBody)
	}
}

// ── ParseURL convenience method ──

func TestParseURL(t *testing.T) {
	var receivedBody map[string]string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&receivedBody)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(envelope(map[string]any{
			"status":   "ok",
			"filename": "remote.docx",
			"format":   "docx",
			"blocks":   []map[string]any{{"type": "text", "text": "url parse"}},
			"metadata": map[string]any{},
			"summary":  map[string]any{"totalBlocks": 1},
		}))
	}))
	defer srv.Close()

	c := New("dp_test", WithBaseURL(srv.URL))
	r, err := c.ParseURL(context.Background(), "https://example.com/report.docx", "markdown")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if receivedBody["sourceUrl"] != "https://example.com/report.docx" {
		t.Fatalf("expected sourceUrl in body, got %v", receivedBody)
	}
	if receivedBody["outputFormat"] != "markdown" {
		t.Fatalf("expected outputFormat=markdown, got %s", receivedBody["outputFormat"])
	}
	if receivedBody["filepath"] != "" {
		t.Fatalf("expected empty filepath for URL parse, got %s", receivedBody["filepath"])
	}
	// ParseURL should return a valid result
	if r.Status != "ok" {
		t.Fatalf("expected ok, got %s", r.Status)
	}
}

// ── Response meta on ParseResult ──

func TestParse_ResponseMetaPopulated(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Request-Id", "req_meta_test")
		w.Header().Set("X-DocParse-Tier", "business")
		w.Header().Set("X-DocParse-Quota-Remaining-Day", "9500")
		w.Header().Set("X-DocParse-Quota-Remaining-Month", "49000")
		w.Header().Set("X-DocParse-Quota-Remaining-Ai", "990")
		w.Header().Set("X-AilangParse-Format", "docx")
		w.Header().Set("X-AilangParse-Replayable", "true")
		json.NewEncoder(w).Encode(envelope(map[string]any{
			"status":   "ok",
			"filename": "test.docx",
			"format":   "docx",
			"blocks":   []map[string]any{{"type": "text", "text": "hello"}},
			"metadata": map[string]any{},
			"summary":  map[string]any{"totalBlocks": 1},
		}))
	}))
	defer srv.Close()

	c := New("dp_test", WithBaseURL(srv.URL))
	r, err := c.Parse(context.Background(), "test.docx")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if r.ResponseMeta == nil {
		t.Fatal("expected ResponseMeta to be populated")
	}
	if r.ResponseMeta.RequestID != "req_meta_test" {
		t.Fatalf("expected req_meta_test, got %s", r.ResponseMeta.RequestID)
	}
	if r.ResponseMeta.Tier != "business" {
		t.Fatalf("expected business, got %s", r.ResponseMeta.Tier)
	}
	if r.ResponseMeta.QuotaRemainingDay != 9500 {
		t.Fatalf("expected 9500, got %d", r.ResponseMeta.QuotaRemainingDay)
	}
	if r.ResponseMeta.QuotaRemainingMonth != 49000 {
		t.Fatalf("expected 49000, got %d", r.ResponseMeta.QuotaRemainingMonth)
	}
	if r.ResponseMeta.QuotaRemainingAI != 990 {
		t.Fatalf("expected 990, got %d", r.ResponseMeta.QuotaRemainingAI)
	}
	if r.ResponseMeta.Format != "docx" {
		t.Fatalf("expected docx, got %s", r.ResponseMeta.Format)
	}
	if !r.ResponseMeta.Replayable {
		t.Fatal("expected replayable=true")
	}
}

func TestParseFile_ResponseMetaPopulated(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Request-Id", "req_file_meta")
		w.Header().Set("X-DocParse-Tier", "pro")
		w.Header().Set("X-DocParse-Quota-Remaining-Day", "1800")
		json.NewEncoder(w).Encode(envelope(map[string]any{
			"status":   "ok",
			"filename": "up.docx",
			"format":   "docx",
			"blocks":   []map[string]any{{"type": "text", "text": "uploaded"}},
			"metadata": map[string]any{},
			"summary":  map[string]any{"totalBlocks": 1},
		}))
	}))
	defer srv.Close()

	dir := t.TempDir()
	local := filepath.Join(dir, "up.docx")
	os.WriteFile(local, []byte("PK\x03\x04 fake"), 0644)

	c := New("dp_test", WithBaseURL(srv.URL))
	r, err := c.ParseFile(context.Background(), local)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if r.ResponseMeta == nil {
		t.Fatal("expected ResponseMeta to be populated")
	}
	if r.ResponseMeta.RequestID != "req_file_meta" {
		t.Fatalf("expected req_file_meta, got %s", r.ResponseMeta.RequestID)
	}
	if r.ResponseMeta.Tier != "pro" {
		t.Fatalf("expected pro, got %s", r.ResponseMeta.Tier)
	}
	if r.ResponseMeta.QuotaRemainingDay != 1800 {
		t.Fatalf("expected 1800, got %d", r.ResponseMeta.QuotaRemainingDay)
	}
}

// ── Structured error with details ──

func TestStructuredErrorCarriesDetails(t *testing.T) {
	// The unwrap method first unmarshals into serveAPIResponse where Error is
	// a string. When the server sends a dict-style error, the outer error field
	// must be a string code; the dict envelope is parsed on a second pass.
	// However, when the inner result contains a structured error object, unwrap
	// handles it via the innerObj path. Test both the flat legacy format and the
	// inner-result structured error format.

	// Inner-result structured error: {result: "{\"error\":{\"message\":...},\"request_id\":...}"}
	inner := `{"error":{"message":"bad request","details":{"field":"x"}},"request_id":"req_1"}`
	srv := mockServer(200, map[string]any{"result": inner})
	defer srv.Close()

	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.Parse(context.Background(), "bad.docx")
	if err == nil {
		t.Fatal("expected error")
	}
	var dpe *DocParseError
	if !errors.As(err, &dpe) {
		t.Fatalf("expected DocParseError, got %T", err)
	}
	if dpe.Message != "bad request" {
		t.Fatalf("expected 'bad request', got %q", dpe.Message)
	}
	if dpe.RequestID != "req_1" {
		t.Fatalf("expected request_id=req_1, got %q", dpe.RequestID)
	}
	if dpe.Details == nil {
		t.Fatal("expected details to be populated")
	}
	if dpe.Details["field"] != "x" {
		t.Fatalf("expected details.field=x, got %v", dpe.Details["field"])
	}
}

func TestStructuredErrorAuthWithDetails(t *testing.T) {
	// Auth error inside the inner result envelope
	inner := `{"error":{"message":"Invalid or expired API key","details":{"reason":"expired"}},"request_id":"req_auth_det"}`
	srv := mockServer(200, map[string]any{"result": inner})
	defer srv.Close()

	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.Health(context.Background())
	if err == nil {
		t.Fatal("expected error")
	}
	if !errors.Is(err, ErrAuth) {
		t.Fatalf("expected ErrAuth, got %v", err)
	}
	var ae *AuthError
	if !errors.As(err, &ae) {
		t.Fatalf("expected *AuthError, got %T", err)
	}
	if ae.RequestID != "req_auth_det" {
		t.Fatalf("expected request_id=req_auth_det, got %q", ae.RequestID)
	}
	if ae.Details["reason"] != "expired" {
		t.Fatalf("expected details.reason=expired, got %v", ae.Details["reason"])
	}
}

func TestStructuredErrorFlatFormatWithDetails(t *testing.T) {
	// Legacy flat format: {error: "CODE", message: "...", suggested_fix: "..."}
	srv := mockServer(200, map[string]any{
		"error":         "VALIDATION_ERROR",
		"message":       "Invalid file format",
		"suggested_fix": "Use a supported format like docx or pdf.",
	})
	defer srv.Close()

	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.Parse(context.Background(), "bad.xyz")
	if err == nil {
		t.Fatal("expected error")
	}
	var dpe *DocParseError
	if !errors.As(err, &dpe) {
		t.Fatalf("expected DocParseError, got %T", err)
	}
	if dpe.Message != "Invalid file format" {
		t.Fatalf("expected 'Invalid file format', got %q", dpe.Message)
	}
	if dpe.SuggestedFix != "Use a supported format like docx or pdf." {
		t.Fatalf("expected suggested_fix, got %q", dpe.SuggestedFix)
	}
}
