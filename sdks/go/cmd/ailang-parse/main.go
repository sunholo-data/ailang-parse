// Command ailang-parse — MCP stdio server for Claude Desktop and other MCP clients.
//
// Bridges MCP stdio transport to the hosted AILANG Parse API.
// Stdlib only — no external dependencies.
//
// Usage:
//
//	ailang-parse mcp
//
// Claude Desktop (claude_desktop_config.json):
//
//	{ "command": "ailang-parse", "args": ["mcp"] }
//
// Environment variables:
//
//	AILANG_PARSE_MCP_URL  Override the MCP endpoint (default: hosted API)
//	DOCPARSE_API_KEY      Pre-set API key (optional — device auth works without it)
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
)

const defaultEndpoint = "https://docparse.ailang.sunholo.com/mcp/"

var (
	sessionID string
	endpoint  string
	client    = &http.Client{}
)

func logf(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, "[ailang-parse-mcp] "+format+"\n", args...)
}

func writeJSON(obj map[string]interface{}) {
	b, err := json.Marshal(obj)
	if err != nil {
		logf("write error: %v", err)
		return
	}
	fmt.Println(string(b))
}

func forward(raw []byte, msg map[string]interface{}) error {
	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(raw))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	if sessionID != "" {
		req.Header.Set("Mcp-Session-Id", sessionID)
	}
	if apiKey := os.Getenv("DOCPARSE_API_KEY"); apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiKey)
	}

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if sid := resp.Header.Get("Mcp-Session-Id"); sid != "" {
		sessionID = sid
	}

	// Notifications get 202/204 with no body
	if resp.StatusCode == 202 || resp.StatusCode == 204 {
		return nil
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}

	if resp.StatusCode >= 400 {
		snippet := string(body)
		if len(snippet) > 200 {
			snippet = snippet[:200]
		}
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, snippet)
	}

	contentType := resp.Header.Get("Content-Type")
	text := string(body)

	if strings.Contains(contentType, "text/event-stream") {
		// SSE response — each "data: {...}" line is a JSON-RPC message
		for _, line := range strings.Split(text, "\n") {
			if strings.HasPrefix(line, "data: ") {
				data := strings.TrimSpace(line[6:])
				if data != "" {
					fmt.Println(data)
				}
			}
		}
	} else {
		// Direct JSON response
		text = strings.TrimSpace(text)
		if text != "" {
			fmt.Println(text)
		}
	}

	return nil
}

func runMCP() int {
	endpoint = os.Getenv("AILANG_PARSE_MCP_URL")
	if endpoint == "" {
		endpoint = defaultEndpoint
	}
	logf("Connecting to %s", endpoint)

	scanner := bufio.NewScanner(os.Stdin)
	// MCP tool results can exceed the default 64KB scanner buffer
	scanner.Buffer(make([]byte, 1024*1024), 10*1024*1024)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		var msg map[string]interface{}
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			continue // skip malformed input
		}

		if err := forward([]byte(line), msg); err != nil {
			method, _ := msg["method"].(string)
			if method == "" {
				method = "unknown"
			}
			// Send JSON-RPC error for requests (has id), skip for notifications
			if id, ok := msg["id"]; ok && id != nil {
				writeJSON(map[string]interface{}{
					"jsonrpc": "2.0",
					"id":      id,
					"error": map[string]interface{}{
						"code":    -32000,
						"message": "MCP bridge error: " + err.Error(),
					},
				})
			}
			logf("Error forwarding %s: %v", method, err)
		}
	}

	if err := scanner.Err(); err != nil {
		logf("stdin scan error: %v", err)
		return 1
	}
	return 0
}

func printHelp() {
	fmt.Fprintln(os.Stderr, "ailang-parse — AILANG Parse CLI")
	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "Commands:")
	fmt.Fprintln(os.Stderr, "  mcp    Start MCP stdio server (for Claude Desktop, Cursor, etc.)")
	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "Claude Desktop config:")
	fmt.Fprintln(os.Stderr, `  { "command": "ailang-parse", "args": ["mcp"] }`)
	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "More info: https://www.sunholo.com/docparse/mcp.html")
}

func main() {
	cmd := ""
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}

	switch cmd {
	case "mcp":
		os.Exit(runMCP())
	case "--help", "-h":
		printHelp()
		os.Exit(0)
	default:
		printHelp()
		os.Exit(1)
	}
}
