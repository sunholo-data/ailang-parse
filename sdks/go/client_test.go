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
