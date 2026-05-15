package docparse

import (
	"bytes"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

// TestRaiseForResponse_PopulatesHeadersOn500 verifies the v0.6.0 contract:
// transport-layer errors must carry RequestID and Replayable from the
// response headers, not drop them on the floor.
func TestRaiseForResponse_PopulatesHeadersOn500(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Request-Id", "req-abc")
		w.Header().Set("X-AilangParse-Replayable", "true")
		w.Header().Set("X-DocParse-Tier", "pro")
		w.WriteHeader(500)
		_, _ = io.Copy(w, bytes.NewBufferString(`{"error":"transient","suggested_fix":"retry"}`))
	}))
	defer srv.Close()

	resp, err := http.Get(srv.URL)
	if err != nil {
		t.Fatalf("http.Get: %v", err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	got := raiseForResponse(resp, body)
	if got == nil {
		t.Fatal("expected error for 500, got nil")
	}
	var dpe *DocParseError
	if !errors.As(got, &dpe) {
		t.Fatalf("expected *DocParseError, got %T", got)
	}
	if dpe.RequestID != "req-abc" {
		t.Errorf("RequestID = %q, want %q", dpe.RequestID, "req-abc")
	}
	if !dpe.Replayable {
		t.Error("Replayable = false, want true")
	}
	if dpe.SuggestedFix != "retry" {
		t.Errorf("SuggestedFix = %q, want %q", dpe.SuggestedFix, "retry")
	}
	if dpe.StatusCode != 500 {
		t.Errorf("StatusCode = %d, want 500", dpe.StatusCode)
	}
}

func TestRaiseForResponse_401YieldsAuthErrorWithMeta(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Request-Id", "req-x")
		w.WriteHeader(401)
		_, _ = io.Copy(w, bytes.NewBufferString(`{"error":"bad key"}`))
	}))
	defer srv.Close()

	resp, _ := http.Get(srv.URL)
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	got := raiseForResponse(resp, body)
	var ae *AuthError
	if !errors.As(got, &ae) {
		t.Fatalf("expected *AuthError, got %T (%v)", got, got)
	}
	if ae.RequestID != "req-x" {
		t.Errorf("RequestID = %q, want req-x", ae.RequestID)
	}
}

func TestRaiseForResponse_429YieldsQuotaErrorWithTier(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Request-Id", "req-q")
		w.Header().Set("X-DocParse-Tier", "free")
		w.WriteHeader(429)
		_, _ = io.Copy(w, bytes.NewBufferString(`{"error":"out"}`))
	}))
	defer srv.Close()

	resp, _ := http.Get(srv.URL)
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	got := raiseForResponse(resp, body)
	var qe *QuotaError
	if !errors.As(got, &qe) {
		t.Fatalf("expected *QuotaError, got %T (%v)", got, got)
	}
	if qe.Tier != "free" {
		t.Errorf("Tier = %q, want free", qe.Tier)
	}
	if qe.RequestID != "req-q" {
		t.Errorf("RequestID = %q, want req-q", qe.RequestID)
	}
}

func TestRaiseForResponse_NoBodyFallsBackToStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(503)
	}))
	defer srv.Close()

	resp, _ := http.Get(srv.URL)
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	got := raiseForResponse(resp, body)
	if got == nil || !contains(got.Error(), "503") {
		t.Fatalf("expected 503 in error, got %v", got)
	}
}

func TestRaiseForResponse_2xxReturnsNil(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
	}))
	defer srv.Close()

	resp, _ := http.Get(srv.URL)
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	if got := raiseForResponse(resp, body); got != nil {
		t.Errorf("expected nil for 2xx, got %v", got)
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub ||
		(len(s) > 0 && (s[:len(sub)] == sub ||
			s[len(s)-len(sub):] == sub ||
			indexOf(s, sub) >= 0)))
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
