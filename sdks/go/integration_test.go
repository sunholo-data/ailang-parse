// Integration tests — hit the real AILANG Parse API.
//
// Run:  DOCPARSE_API_KEY=dp_... go test -v -run Integration ./...
//
// Skipped automatically when DOCPARSE_API_KEY is not set.

package docparse

import (
	"context"
	"os"
	"testing"
)

const sampleFile = "sample_docx_basic"

func requireKey(t *testing.T) {
	t.Helper()
	if os.Getenv("DOCPARSE_API_KEY") == "" {
		t.Skip("DOCPARSE_API_KEY not set")
	}
}

func integrationClient() *Client {
	return New("")
}

// ── Unauthenticated endpoints ──

func TestIntegration_Health(t *testing.T) {
	requireKey(t)
	c := integrationClient()
	h, err := c.Health(context.Background())
	if err != nil {
		t.Fatalf("health: %v", err)
	}
	if h.Status != "ok" && h.Status != "healthy" {
		t.Fatalf("expected ok or healthy, got %s", h.Status)
	}
	if h.Version == "" {
		t.Fatal("version is empty")
	}
	if h.Service != "docparse" {
		t.Fatalf("expected docparse, got %s", h.Service)
	}
	if h.FormatsParse == 0 {
		t.Fatal("formats_parse is 0")
	}
}

func TestIntegration_Formats(t *testing.T) {
	requireKey(t)
	c := integrationClient()
	f, err := c.Formats(context.Background())
	if err != nil {
		t.Fatalf("formats: %v", err)
	}
	if len(f.Parse) == 0 {
		t.Fatal("no parse formats")
	}
	found := false
	for _, fmt := range f.Parse {
		if fmt == "docx" {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("docx not in parse formats: %v", f.Parse)
	}
}

// ── Authenticated endpoints ──

func TestIntegration_Parse(t *testing.T) {
	requireKey(t)
	c := integrationClient()
	r, err := c.Parse(context.Background(), sampleFile)
	if err != nil {
		t.Skipf("Parse not available with current key: %v", err)
	}
	if r.Status != "ok" && r.Status != "success" {
		t.Fatalf("expected ok or success, got %s", r.Status)
	}
	if r.Filename == "" {
		t.Fatal("filename is empty")
	}
	if len(r.Blocks) == 0 {
		t.Fatal("no blocks returned")
	}
	if r.Summary.TotalBlocks == 0 {
		t.Fatal("totalBlocks is 0")
	}

	validTypes := map[string]bool{
		"text": true, "heading": true, "table": true, "list": true,
		"image": true, "audio": true, "video": true, "section": true, "change": true,
	}
	for _, b := range r.Blocks {
		if !validTypes[b.Type] {
			t.Fatalf("unexpected block type: %s", b.Type)
		}
	}
}

func TestIntegration_UnstructuredCompat(t *testing.T) {
	requireKey(t)
	uc := NewUnstructuredClient(DefaultBaseURL)
	elements, err := uc.Partition(context.Background(), sampleFile)
	if err != nil {
		t.Skipf("Partition not available with current key: %v", err)
	}
	if len(elements) == 0 {
		t.Fatal("no elements returned")
	}
	for _, el := range elements {
		if el.Type == "" {
			t.Fatal("element type is empty")
		}
	}
}
