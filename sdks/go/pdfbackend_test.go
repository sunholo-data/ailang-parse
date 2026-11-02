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
	"sync/atomic"
	"testing"
)

// captureServer records each request's JSON body or multipart form fields
// and answers with an empty successful parse.
type captured struct {
	count  atomic.Int32
	json   map[string]string
	fields map[string]string
}

func newCaptureServer(t *testing.T) (*httptest.Server, *captured) {
	t.Helper()
	rec := &captured{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rec.count.Add(1)
		if strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Errorf("parse multipart: %v", err)
			}
			rec.fields = map[string]string{}
			for k, v := range r.MultipartForm.Value {
				rec.fields[k] = v[0]
			}
		} else {
			rec.json = map[string]string{}
			json.NewDecoder(r.Body).Decode(&rec.json)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(envelope(map[string]any{
			"status": "ok", "format": "pdf", "blocks": []any{},
			"metadata": map[string]any{}, "summary": map[string]any{},
		}))
	}))
	t.Cleanup(srv.Close)
	return srv, rec
}

func writeFile(t *testing.T, name string, data []byte) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(p, data, 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

// sparseFile creates a file of the given size without writing its bytes.
func sparseFile(t *testing.T, name string, size int64) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), name)
	f, err := os.Create(p)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err := f.Truncate(size); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestParse_SendsPDFBackendAndGCSRef(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.Parse(context.Background(), "", ParseOptions{PDFBackend: "ai", GCSRef: "gs://b/big.pdf"})
	if err != nil {
		t.Fatal(err)
	}
	if rec.json["pdfBackend"] != "ai" || rec.json["gcsRef"] != "gs://b/big.pdf" {
		t.Fatalf("body = %v", rec.json)
	}
}

func TestParse_OmitsPDFBackendByDefault(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	if _, err := c.Parse(context.Background(), "sample_pdf"); err != nil {
		t.Fatal(err)
	}
	if _, ok := rec.json["pdfBackend"]; ok {
		t.Fatalf("pdfBackend should be absent: %v", rec.json)
	}
	if _, ok := rec.json["gcsRef"]; ok {
		t.Fatalf("gcsRef should be absent: %v", rec.json)
	}
}

func TestParseURL_SendsPDFBackend(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.ParseURL(context.Background(), "https://example.com/scan.pdf", "blocks", ParseOptions{PDFBackend: "poppler"})
	if err != nil {
		t.Fatal(err)
	}
	if rec.json["pdfBackend"] != "poppler" || rec.json["sourceUrl"] != "https://example.com/scan.pdf" {
		t.Fatalf("body = %v", rec.json)
	}
}

func TestParseURL_StillTakesThreeArgs(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	if _, err := c.ParseURL(context.Background(), "https://example.com/a.docx", "markdown"); err != nil {
		t.Fatal(err)
	}
	if _, ok := rec.json["pdfBackend"]; ok {
		t.Fatalf("pdfBackend should be absent: %v", rec.json)
	}
}

func TestParseFile_SendsPDFBackendField(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	local := writeFile(t, "scan.pdf", []byte("%PDF-1.4"))
	if _, err := c.ParseFile(context.Background(), local, ParseOptions{PDFBackend: "ai"}); err != nil {
		t.Fatal(err)
	}
	if rec.fields["pdfBackend"] != "ai" {
		t.Fatalf("fields = %v", rec.fields)
	}
}

func TestParseFile_OmitsPDFBackendByDefault(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	local := writeFile(t, "doc.pdf", []byte("%PDF-1.4"))
	if _, err := c.ParseFile(context.Background(), local); err != nil {
		t.Fatal(err)
	}
	if _, ok := rec.fields["pdfBackend"]; ok {
		t.Fatalf("pdfBackend should be absent: %v", rec.fields)
	}
}

// ── Uploads over the platform's 32 MiB request rec ──

func assertFileTooLarge(t *testing.T, err error) *DocParseError {
	t.Helper()
	var dpe *DocParseError
	if !errors.As(err, &dpe) {
		t.Fatalf("expected *DocParseError, got %T: %v", err, err)
	}
	if dpe.Code != CodeFileTooLarge || dpe.StatusCode != 413 {
		t.Fatalf("code=%q status=%d", dpe.Code, dpe.StatusCode)
	}
	return dpe
}

func TestMaxDirectUploadBytes(t *testing.T) {
	if MaxDirectUploadBytes != 33554432 {
		t.Fatalf("MaxDirectUploadBytes = %d", MaxDirectUploadBytes)
	}
}

func TestParseFile_OverCapFailsBeforeSending(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	big := sparseFile(t, "big.pdf", MaxDirectUploadBytes+1)
	_, err := c.ParseFile(context.Background(), big)
	dpe := assertFileTooLarge(t, err)
	if dpe.Details["size_bytes"] != MaxDirectUploadBytes+1 {
		t.Fatalf("details = %v", dpe.Details)
	}
	for _, want := range []string{"ParseURL", "/api/v1/upload/url", "GCSRef"} {
		if !strings.Contains(dpe.Message, want) {
			t.Errorf("message lacks %q: %s", want, dpe.Message)
		}
	}
	if n := rec.count.Load(); n != 0 {
		t.Fatalf("expected no request, got %d", n)
	}
}

func TestParseFile_AtCapIsSent(t *testing.T) {
	srv, rec := newCaptureServer(t)
	c := New("dp_test", WithBaseURL(srv.URL))
	ok := sparseFile(t, "ok.pdf", MaxDirectUploadBytes)
	if _, err := c.ParseFile(context.Background(), ok); err != nil {
		t.Fatal(err)
	}
	if n := rec.count.Load(); n != 1 {
		t.Fatalf("expected one request, got %d", n)
	}
}

func TestHTML413BecomesFileTooLarge(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=UTF-8")
		w.WriteHeader(413)
		w.Write([]byte("<!DOCTYPE html><html><title>Error 413 (Request Entity Too Large)!!1</title></html>"))
	}))
	defer srv.Close()
	c := New("dp_test", WithBaseURL(srv.URL))
	local := writeFile(t, "doc.pdf", []byte("%PDF-1.4"))
	_, err := c.ParseFile(context.Background(), local)
	dpe := assertFileTooLarge(t, err)
	if strings.Contains(strings.ToLower(dpe.Message), "<html") {
		t.Fatalf("raw HTML leaked into message: %s", dpe.Message)
	}
}

func TestJSON413KeepsServerError(t *testing.T) {
	srv := mockServer(413, map[string]any{"error": map[string]any{
		"code": "FILE_TOO_LARGE", "message": "File exceeds your tier limit (10 MB)",
	}})
	defer srv.Close()
	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.Parse(context.Background(), "sample_pdf")
	dpe := assertFileTooLarge(t, err)
	if !strings.Contains(dpe.Message, "tier limit") {
		t.Fatalf("message = %s", dpe.Message)
	}
}

func TestPartition_OverCapFailsBeforeSending(t *testing.T) {
	srv, rec := newCaptureServer(t)
	uc := NewUnstructuredClient(srv.URL, "dp_test")
	big := sparseFile(t, "big.docx", MaxDirectUploadBytes+1)
	_, err := uc.Partition(context.Background(), big)
	assertFileTooLarge(t, err)
	if n := rec.count.Load(); n != 0 {
		t.Fatalf("expected no request, got %d", n)
	}
}

func TestInnerEnvelopeErrorCarriesCode(t *testing.T) {
	inner := `{"error":{"code":"FILE_TOO_LARGE","message":"too big"},"request_id":"r1"}`
	srv := mockServer(200, map[string]any{"result": inner})
	defer srv.Close()
	c := New("dp_test", WithBaseURL(srv.URL))
	_, err := c.Parse(context.Background(), "x")
	var dpe *DocParseError
	if !errors.As(err, &dpe) || dpe.Code != "FILE_TOO_LARGE" || dpe.RequestID != "r1" {
		t.Fatalf("got %T %+v", err, dpe)
	}
}

func TestLegacyEnvelopeErrorCarriesCode(t *testing.T) {
	srv := mockServer(200, map[string]any{"error": "AUTH_REQUIRED", "message": "key needed"})
	defer srv.Close()
	c := New("", WithBaseURL(srv.URL))
	_, err := c.Parse(context.Background(), "x")
	var dpe *DocParseError
	if !errors.As(err, &dpe) || dpe.Code != "AUTH_REQUIRED" {
		t.Fatalf("got %T %+v", err, dpe)
	}
}
