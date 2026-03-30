// Package docparse provides a Go client for the AILANG Parse document parsing API.
package docparse

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

// ParseResult is the response from /api/v1/parse.
type ParseResult struct {
	Status   string      `json:"status"`
	Filename string      `json:"filename"`
	Format   string      `json:"format"`
	Blocks   []Block     `json:"blocks"`
	Metadata DocMetadata `json:"metadata"`
	Summary  Summary     `json:"summary"`
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

// Quota contains tier quota limits.
type Quota struct {
	RequestsPerDay     int `json:"requestsPerDay"`
	PagesPerMonth      int `json:"pagesPerMonth"`
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
	RequestsToday  int `json:"requestsToday"`
	PagesThisMonth int `json:"pagesThisMonth"`
	TotalRequests  int `json:"totalRequests"`
	TotalPages     int `json:"totalPages"`
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
