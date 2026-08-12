package docparse

import (
	"encoding/base64"
	"encoding/json"
	"testing"
)

// Encoding is load-bearing: base64 for container targets, UTF-8 for
// html/md/qmd. Decoding must branch on it, never on the target.
func TestBuildConvertResultBase64(t *testing.T) {
	zip := []byte("PK\x03\x04fakezip")
	inner, _ := json.Marshal(map[string]any{
		"status": "success", "request_id": "req_c1",
		"source_format": "zip-office", "source_subtype": "docx",
		"target": "pptx", "filename": "report.pptx",
		"content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
		"encoding": "base64", "size_bytes": len(zip),
		"content": base64.StdEncoding.EncodeToString(zip),
	})
	r, err := buildConvertResult(inner)
	if err != nil {
		t.Fatalf("buildConvertResult: %v", err)
	}
	if string(r.Content) != string(zip) {
		t.Errorf("content mismatch: got %q", r.Content)
	}
	if r.Filename != "report.pptx" || r.Target != "pptx" || r.SourceSubtype != "docx" {
		t.Errorf("metadata mismatch: %+v", r)
	}
	if r.SizeBytes != len(zip) {
		t.Errorf("size %d, want %d", r.SizeBytes, len(zip))
	}
}

func TestBuildConvertResultUTF8(t *testing.T) {
	inner, _ := json.Marshal(map[string]any{
		"status": "success", "target": "md", "filename": "a.md",
		"content_type": "text/markdown", "encoding": "utf8", "content": "# Hello",
	})
	r, err := buildConvertResult(inner)
	if err != nil {
		t.Fatalf("buildConvertResult: %v", err)
	}
	if r.Text() != "# Hello" {
		t.Errorf("text %q, want %q", r.Text(), "# Hello")
	}
	if r.SizeBytes != len("# Hello") {
		t.Errorf("size should fall back to content length, got %d", r.SizeBytes)
	}
}

func TestInlineRunHrefDecodes(t *testing.T) {
	var b Block
	if err := json.Unmarshal([]byte(`{"type":"text","runs":[{"text":"docs","href":"https://example.com"}]}`), &b); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(b.Runs) != 1 || b.Runs[0].Href != "https://example.com" {
		t.Errorf("href not decoded: %+v", b.Runs)
	}
	// omitempty keeps a non-link run's JSON unchanged
	out, _ := json.Marshal(InlineRun{Text: "plain"})
	if string(out) != `{"text":"plain"}` {
		t.Errorf("plain run should not gain href: %s", out)
	}
}
