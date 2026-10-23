package docparse

import (
	"encoding/json"
	"testing"
)

func TestRichCellRunsAndCompactCellReset(t *testing.T) {
	var c Cell
	if err := json.Unmarshal([]byte(`{"text":"linked","runs":[{"text":"linked","bold":true,"color":"#123456","href":"https://example.com"}]}`), &c); err != nil {
		t.Fatal(err)
	}
	if len(c.Runs) != 1 || !c.Runs[0].Bold || c.Runs[0].Color != "#123456" || c.Runs[0].Href != "https://example.com" {
		t.Fatalf("lost cell runs: %+v", c)
	}
	if err := json.Unmarshal([]byte(`"plain"`), &c); err != nil {
		t.Fatal(err)
	}
	if c.Text != "plain" || c.ColSpan != 1 || len(c.Runs) != 0 {
		t.Fatalf("stale formatting after compact cell: %+v", c)
	}
	encoded, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	var obj map[string]any
	if err := json.Unmarshal(encoded, &obj); err != nil {
		t.Fatal(err)
	}
	if _, ok := obj["runs"]; ok {
		t.Fatalf("empty runs should be omitted: %s", encoded)
	}
}

// Runs and ItemRuns decode with the right flags, and stay absent when the
// source carried no inline formatting.
func TestInlineRunsDecode(t *testing.T) {
	var b Block
	if err := json.Unmarshal([]byte(`{
		"type": "text",
		"text": "plain bold x2",
		"runs": [
			{"text": "plain "},
			{"text": "bold", "bold": true},
			{"text": "2", "vertAlign": "superscript"}
		]
	}`), &b); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(b.Runs) != 3 {
		t.Fatalf("want 3 runs, got %d", len(b.Runs))
	}
	if !b.Runs[1].Bold {
		t.Error("run 1 should be bold")
	}
	if b.Runs[0].Bold {
		t.Error("run 0 should not be bold")
	}
	if b.Runs[2].VertAlign != "superscript" {
		t.Errorf("want superscript, got %q", b.Runs[2].VertAlign)
	}

	// itemRuns is parallel to items; an unformatted item is an empty list
	var l Block
	if err := json.Unmarshal([]byte(`{
		"type": "list",
		"items": ["one", "two"],
		"itemRuns": [[{"text": "one", "italic": true}], []]
	}`), &l); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(l.ItemRuns) != len(l.Items) {
		t.Fatalf("itemRuns (%d) must be parallel to items (%d)", len(l.ItemRuns), len(l.Items))
	}
	if !l.ItemRuns[0][0].Italic {
		t.Error("item 0 should be italic")
	}
	if len(l.ItemRuns[1]) != 0 {
		t.Error("item 1 should have no runs")
	}

	// A block with no formatting keeps the pre-InlineRun shape, and omitempty
	// keeps it out of the wire format entirely.
	var plain Block
	if err := json.Unmarshal([]byte(`{"type":"text","text":"nothing here"}`), &plain); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if plain.Runs != nil {
		t.Error("expected no runs")
	}
	out, err := json.Marshal(plain)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if string(out) != `{"type":"text","text":"nothing here"}` {
		t.Errorf("plain block should round-trip unchanged, got %s", out)
	}
}
