package docparse

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// fastRetry is a quick-backoff policy for tests.
func fastRetry(max int) RetryPolicy {
	return RetryPolicy{MaxRetries: max, BackoffBase: time.Millisecond, BackoffMax: 2 * time.Millisecond}
}

func TestRetry_TransientThenSucceeds(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if atomic.AddInt32(&calls, 1) < 3 {
			w.WriteHeader(503)
			w.Write([]byte(`{"error":"transient"}`))
			return
		}
		w.WriteHeader(200)
		json.NewEncoder(w).Encode(envelope(map[string]any{"status": "ok", "format": "blocks"}))
	}))
	defer srv.Close()

	c := New("dp_x", WithBaseURL(srv.URL), WithRetry(fastRetry(3)))
	if _, err := c.Parse(context.Background(), "sample_docx_formatting"); err != nil {
		t.Fatalf("expected success after retries, got %v", err)
	}
	if got := atomic.LoadInt32(&calls); got != 3 {
		t.Fatalf("expected 3 calls (2 retries then success), got %d", got)
	}
}

func TestRetry_DefaultNoRetry(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.WriteHeader(503)
		w.Write([]byte(`{"error":"transient"}`))
	}))
	defer srv.Close()

	c := New("dp_x", WithBaseURL(srv.URL)) // default policy: MaxRetries 0
	if _, err := c.Parse(context.Background(), "x"); err == nil {
		t.Fatal("expected an error with the default no-retry policy")
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("expected exactly 1 call (no retry), got %d", got)
	}
}

func TestRetry_ReplayableHeader(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if atomic.AddInt32(&calls, 1) < 2 {
			// 500 is NOT in retryable_statuses, but the replayable header opts it in.
			w.Header().Set("X-AilangParse-Replayable", "true")
			w.WriteHeader(500)
			w.Write([]byte(`{"error":"replayable"}`))
			return
		}
		w.WriteHeader(200)
		json.NewEncoder(w).Encode(envelope(map[string]any{"status": "ok", "format": "blocks"}))
	}))
	defer srv.Close()

	c := New("dp_x", WithBaseURL(srv.URL), WithRetry(fastRetry(2)))
	if _, err := c.Parse(context.Background(), "x"); err != nil {
		t.Fatalf("expected success after replayable retry, got %v", err)
	}
	if got := atomic.LoadInt32(&calls); got != 2 {
		t.Fatalf("expected 2 calls, got %d", got)
	}
}

func TestRetry_NonRetryableStatusNotRetried(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.WriteHeader(400) // client error — never retried
		w.Write([]byte(`{"error":"bad request"}`))
	}))
	defer srv.Close()

	c := New("dp_x", WithBaseURL(srv.URL), WithRetry(fastRetry(3)))
	if _, err := c.Parse(context.Background(), "x"); err == nil {
		t.Fatal("expected an error for 400")
	}
	if got := atomic.LoadInt32(&calls); got != 1 {
		t.Fatalf("expected exactly 1 call (400 not retried), got %d", got)
	}
}
