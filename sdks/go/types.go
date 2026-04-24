// Package docparse provides a Go client for the AILANG Parse document parsing API.
package docparse

import (
	"encoding/json"
	"strings"
)

// Block represents a parsed content block (9 variants discriminated by Type).
type Block struct {
	Type string `json:"type"` // text, heading, table, list, image, audio, video, section, change

	// TextBlock / HeadingBlock / ChangeBlock
	Text  string `json:"text,omitempty"`
	Level int    `json:"level,omitempty"`
	Style string `json:"style,omitempty"`

	// ChangeBlock
	ChangeType string `json:"changeType,omitempty"`
	Author     string `json:"author,omitempty"`
	Date       string `json:"date,omitempty"`

	// TableBlock
	Headers []Cell   `json:"headers,omitempty"`
	Rows    [][]Cell `json:"rows,omitempty"`

	// ListBlock
	Items   []string `json:"items,omitempty"`
	Ordered bool     `json:"ordered,omitempty"`

	// ImageBlock / AudioBlock / VideoBlock
	Description   string `json:"description,omitempty"`
	Transcription string `json:"transcription,omitempty"`
	Mime          string `json:"mime,omitempty"`
	DataLength    int    `json:"dataLength,omitempty"`

	// SectionBlock (recursive)
	Kind     string  `json:"kind,omitempty"`
	Children []Block `json:"blocks,omitempty"`
}

// Cell represents a table cell (simple text or merged).
type Cell struct {
	Text    string `json:"text"`
	ColSpan int    `json:"colSpan,omitempty"`
	Merged  bool   `json:"merged,omitempty"`
}

// UnmarshalJSON handles both string ("A") and object ({"text":"A","colSpan":2}) forms.
func (c *Cell) UnmarshalJSON(data []byte) error {
	// Try string first
	var s string
	if err := json.Unmarshal(data, &s); err == nil {
		c.Text = s
		c.ColSpan = 1
		return nil
	}
	// Otherwise unmarshal as struct
	type cellAlias Cell
	var alias cellAlias
	if err := json.Unmarshal(data, &alias); err != nil {
		return err
	}
	*c = Cell(alias)
	if c.ColSpan == 0 {
		c.ColSpan = 1
	}
	return nil
}

// DocMetadata contains document metadata.
type DocMetadata struct {
	Title    string `json:"title"`
	Author   string `json:"author"`
	Created  string `json:"created"`
	Modified string `json:"modified"`
	PageCount int   `json:"pageCount"`
}

// Summary contains block count summary.
type Summary struct {
	TotalBlocks int `json:"totalBlocks"`
	Headings    int `json:"headings"`
	Tables      int `json:"tables"`
	Images      int `json:"images"`
	Changes     int `json:"changes"`
}

// Section is a heading-delimited section of a document.
// Returned when outputFormat="markdown+metadata".
type Section struct {
	Heading  string `json:"heading"`
	Level    int    `json:"level"`
	Markdown string `json:"markdown"`
}

// ResponseMeta contains metadata extracted from API response HTTP headers.
type ResponseMeta struct {
	RequestID           string `json:"requestId"`
	Tier                string `json:"tier"`
	QuotaRemainingDay   int    `json:"quotaRemainingDay"`
	QuotaRemainingMonth int    `json:"quotaRemainingMonth"`
	QuotaRemainingAI    int    `json:"quotaRemainingAi"`
	Format              string `json:"format"`
	Replayable          bool   `json:"replayable"`
}

// ParseResult is the response from /api/v1/parse.
type ParseResult struct {
	Status   string      `json:"status"`
	Filename string      `json:"filename"`
	Format   string      `json:"format"`
	Blocks   []Block     `json:"blocks"`
	Metadata DocMetadata `json:"metadata"`
	Summary  Summary     `json:"summary"`
	// Text is the raw rendered output for outputFormat="markdown" / "html".
	// Empty for the default "blocks" output, which populates Blocks instead.
	Text string `json:"text,omitempty"`
	// Markdown is the full rendered markdown body for outputFormat="markdown+metadata".
	Markdown string `json:"markdown,omitempty"`
	// Sections are heading-sliced document sections for outputFormat="markdown+metadata".
	Sections []Section `json:"sections,omitempty"`
	// Nodes holds the A2UI adjacency-list for outputFormat="a2ui".
	Nodes []interface{} `json:"-"`
	// ResponseMeta contains request ID, tier, and quota remaining from HTTP headers.
	ResponseMeta *ResponseMeta `json:"-"`
}

// HealthResult is the response from /api/v1/health.
type HealthResult struct {
	Status         string  `json:"status"`
	Version        string  `json:"version"`
	Service        string  `json:"service"`
	FormatsParse   float64 `json:"formats_parse"`
	FormatsGenerate float64 `json:"formats_generate"`
}

// FormatsResult is the response from /api/v1/formats.
type FormatsResult struct {
	Parse      []string `json:"parse"`
	Generate   []string `json:"generate"`
	AIRequired []string `json:"ai_required"`
	Status     string   `json:"status"`
}

// normalizeFormat lowercases and strips a leading "." for tolerant matching.
func normalizeFormat(fmt string) string {
	return strings.TrimPrefix(strings.ToLower(fmt), ".")
}

// Supports reports whether fmt is supported for the given operation
// ("parse" or "generate"). Case-insensitive and tolerant of a leading ".".
func (f *FormatsResult) Supports(format, operation string) bool {
	target := normalizeFormat(format)
	haystack := f.Parse
	if operation == "generate" {
		haystack = f.Generate
	}
	for _, x := range haystack {
		if normalizeFormat(x) == target {
			return true
		}
	}
	return false
}

// IsDeterministic reports whether fmt is parseable without an AI backend.
// True iff Supports(fmt, "parse") and fmt is not in AIRequired.
func (f *FormatsResult) IsDeterministic(format string) bool {
	if !f.Supports(format, "parse") {
		return false
	}
	target := normalizeFormat(format)
	for _, x := range f.AIRequired {
		if normalizeFormat(x) == target {
			return false
		}
	}
	return true
}

// Quota contains tier quota limits.
type Quota struct {
	RequestsPerDay     int `json:"requestsPerDay"`
	RequestsPerMonth   int `json:"requestsPerMonth"`
	AILimitPerRequest  int `json:"aiLimitPerRequest"`
	FSLimitPerRequest  int `json:"fsLimitPerRequest"`
}

// KeyInfo is the response from the device auth approve/poll endpoints.
type KeyInfo struct {
	Status  string `json:"status"`
	Key     string `json:"key"`
	KeyID   string `json:"keyId"`
	Label   string `json:"label"`
	Tier    string `json:"tier"`
	Created string `json:"created"`
	Quota   Quota  `json:"quota"`
	Message string `json:"message,omitempty"`
}

// Usage contains usage counters.
type Usage struct {
	RequestsToday      int `json:"requestsToday"`
	RequestsThisMonth  int `json:"requestsThisMonth"`
	TotalRequests      int `json:"totalRequests"`
}

// UsageInfo is the response from /api/v1/keys/usage.
type UsageInfo struct {
	Status string `json:"status"`
	KeyID  string `json:"keyId"`
	Tier   string `json:"tier"`
	Usage  Usage  `json:"usage"`
	Quota  Quota  `json:"quota"`
}

// Element is an Unstructured-compatible document element.
type Element struct {
	Type      string          `json:"type"`
	ElementID string          `json:"element_id"`
	Text      string          `json:"text"`
	Metadata  ElementMetadata `json:"metadata"`
}

// ElementMetadata contains Unstructured-compatible element metadata.
type ElementMetadata struct {
	Filename      string `json:"filename,omitempty"`
	Filetype      string `json:"filetype,omitempty"`
	CategoryDepth int    `json:"category_depth,omitempty"`
	ImageMimeType string `json:"image_mime_type,omitempty"`
	TextAsHTML    string `json:"text_as_html,omitempty"`
}

// serveAPIResponse is the outer wrapper from ailang serve-api.
type serveAPIResponse struct {
	Result    string `json:"result"`
	Module    string `json:"module"`
	Func      string `json:"func"`
	ElapsedMs int    `json:"elapsed_ms"`
	Error     string `json:"error,omitempty"`
}
