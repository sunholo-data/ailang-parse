package docparse

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
)

// ConvertOptions configures a convert request.
type ConvertOptions struct {
	// Target format: html md qmd docx pptx xlsx odt odp ods.
	//
	// Normalised server-side (case-insensitive, leading dot stripped,
	// markdown/htm/quarto aliased), so it is deliberately not validated here —
	// a new target must not require an SDK release.
	Target string

	SourceURL  string // fetch the source from this URL instead of a path
	GCSRef     string // gs://bucket/path, Business tier only
	PDFBackend string // "", pdftotext, docling, liteparse, ai
}

// ConvertResult is a converted document.
//
// Content is always decoded bytes regardless of how the wire encoded it —
// base64 for the container targets, UTF-8 for html/md/qmd. Branching on the
// wire encoding is the SDK's job, not the caller's.
type ConvertResult struct {
	Content       []byte
	Filename      string
	ContentType   string
	Target        string
	SourceFormat  string
	SourceSubtype string
	SizeBytes     int
	Status        string
	RequestID     string
	ResponseMeta  *ResponseMeta
}

// Text returns the document as a string. Only meaningful for html/md/qmd.
func (r *ConvertResult) Text() string { return string(r.Content) }

// Save writes the document to path, defaulting to the server's suggested
// filename when path is empty.
func (r *ConvertResult) Save(path string) (string, error) {
	if path == "" {
		path = r.Filename
	}
	if err := os.WriteFile(path, r.Content, 0o644); err != nil {
		return "", fmt.Errorf("write %s: %w", path, err)
	}
	return path, nil
}

// wire is the inner JSON of a convert response.
type convertWire struct {
	Status        string `json:"status"`
	RequestID     string `json:"request_id"`
	SourceFormat  string `json:"source_format"`
	SourceSubtype string `json:"source_subtype"`
	Target        string `json:"target"`
	Filename      string `json:"filename"`
	ContentType   string `json:"content_type"`
	Encoding      string `json:"encoding"`
	SizeBytes     int    `json:"size_bytes"`
	Content       string `json:"content"`
}

// Convert converts a document to another format.
//
//	r, err := client.Convert(ctx, "report.docx", docparse.ConvertOptions{Target: "pptx"})
//	r.Save("")            // writes report.pptx
func (c *Client) Convert(ctx context.Context, filePath string, opts ConvertOptions) (*ConvertResult, error) {
	body := map[string]string{"target": opts.Target}
	if filePath != "" {
		body["filepath"] = filePath
	}
	if opts.SourceURL != "" {
		body["sourceUrl"] = opts.SourceURL
	}
	if opts.GCSRef != "" {
		body["gcsRef"] = opts.GCSRef
	}
	if opts.PDFBackend != "" {
		body["pdfBackend"] = opts.PDFBackend
	}
	if c.APIKey != "" {
		body["apiKey"] = c.APIKey
	}
	b, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal body: %w", err)
	}

	newReq := func() (*http.Request, error) {
		req, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/api/v1/convert", bytes.NewReader(b))
		if err != nil {
			return nil, fmt.Errorf("create request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")
		if c.APIKey != "" {
			req.Header.Set("x-api-key", c.APIKey)
		}
		return req, nil
	}

	resp, data, err := c.doWithRetry(ctx, newReq)
	if err != nil {
		return nil, err
	}
	if err := raiseForResponse(resp, data); err != nil {
		return nil, err
	}
	inner, err := c.unwrap(data)
	if err != nil {
		return nil, err
	}
	result, err := buildConvertResult(inner)
	if err != nil {
		return nil, err
	}
	result.ResponseMeta = extractResponseMeta(resp.Header)
	return result, nil
}

func buildConvertResult(inner []byte) (*ConvertResult, error) {
	var w convertWire
	if err := json.Unmarshal(inner, &w); err != nil {
		return nil, fmt.Errorf("unmarshal convert response: %w", err)
	}
	// Encoding is load-bearing: the three text targets come back as readable
	// UTF-8 and must not be base64-decoded. Never infer it from the target.
	var content []byte
	if w.Encoding == "base64" || w.Encoding == "" {
		decoded, err := base64.StdEncoding.DecodeString(w.Content)
		if err != nil {
			return nil, fmt.Errorf("decode base64 content: %w", err)
		}
		content = decoded
	} else {
		content = []byte(w.Content)
	}
	size := w.SizeBytes
	if size == 0 {
		size = len(content)
	}
	return &ConvertResult{
		Content: content, Filename: w.Filename, ContentType: w.ContentType,
		Target: w.Target, SourceFormat: w.SourceFormat, SourceSubtype: w.SourceSubtype,
		SizeBytes: size, Status: w.Status, RequestID: w.RequestID,
	}, nil
}
