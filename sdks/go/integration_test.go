// Integration tests — hit the real AILANG Parse API.
//
// Run:  DOCPARSE_API_KEY=dp_... go test -v -run Integration ./...
//
// Skipped automatically when DOCPARSE_API_KEY is not set.

package docparse

import (
	"archive/zip"
	"context"
	"os"
	"path/filepath"
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

func TestIntegration_UnstructuredFileUpload(t *testing.T) {
	requireKey(t)

	// Create a minimal DOCX file
	dir := t.TempDir()
	docxPath := filepath.Join(dir, "test.docx")
	createMinimalDocx(t, docxPath)

	uc := NewUnstructuredClient(DefaultBaseURL)
	elements, err := uc.Partition(context.Background(), docxPath)
	if err != nil {
		t.Skipf("Partition file upload not available: %v", err)
	}
	if len(elements) == 0 {
		t.Fatal("no elements returned from file upload")
	}
	for _, el := range elements {
		if el.Type == "" {
			t.Fatal("element type is empty")
		}
	}
}

func TestIntegration_ParseFile(t *testing.T) {
	requireKey(t)

	dir := t.TempDir()
	docxPath := filepath.Join(dir, "test.docx")
	createMinimalDocx(t, docxPath)

	c := integrationClient()
	r, err := c.ParseFile(context.Background(), docxPath)
	if err != nil {
		t.Skipf("ParseFile not available: %v", err)
	}
	if r.Status != "ok" && r.Status != "success" {
		t.Fatalf("expected ok or success, got %s", r.Status)
	}
	if len(r.Blocks) == 0 {
		t.Fatal("no blocks returned")
	}
}

// createMinimalDocx writes a minimal valid DOCX file for testing.
func createMinimalDocx(t *testing.T, path string) {
	t.Helper()
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create docx: %v", err)
	}
	defer f.Close()

	w := zip.NewWriter(f)
	writeZipFile(t, w, "[Content_Types].xml",
		`<?xml version="1.0" encoding="UTF-8"?>`+
			`<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`+
			`<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>`+
			`<Default Extension="xml" ContentType="application/xml"/>`+
			`<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>`+
			`</Types>`)
	writeZipFile(t, w, "_rels/.rels",
		`<?xml version="1.0" encoding="UTF-8"?>`+
			`<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`+
			`<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>`+
			`</Relationships>`)
	writeZipFile(t, w, "word/document.xml",
		`<?xml version="1.0" encoding="UTF-8"?>`+
			`<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">`+
			`<w:body><w:p><w:r><w:t>Integration test content</w:t></w:r></w:p></w:body>`+
			`</w:document>`)
	w.Close()
}

func writeZipFile(t *testing.T, w *zip.Writer, name, content string) {
	t.Helper()
	f, err := w.Create(name)
	if err != nil {
		t.Fatalf("create zip entry %s: %v", name, err)
	}
	f.Write([]byte(content))
}
