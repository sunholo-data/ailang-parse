# ailang-parse-go

Go client for the [AILANG Parse](https://www.sunholo.com/docparse) document parsing API. Parse 13 formats, generate 8 — standard library only.

## Install

```bash
go get github.com/sunholo-data/ailang-parse-go
```

## Quick Start

```go
package main

import (
	"context"
	"fmt"
	"log"

	docparse "github.com/sunholo-data/ailang-parse-go"
)

func main() {
	client := docparse.New("dp_your_key_here")
	ctx := context.Background()

	// Parse a document
	result, err := client.Parse(ctx, "report.docx")
	if err != nil {
		log.Fatal(err)
	}

	fmt.Printf("%d blocks, format: %s\n", len(result.Blocks), result.Format)
	for _, block := range result.Blocks {
		switch block.Type {
		case "heading":
			fmt.Printf("  H%d: %s\n", block.Level, block.Text)
		case "table":
			fmt.Printf("  Table: %d cols, %d rows\n", len(block.Headers), len(block.Rows))
		case "change":
			fmt.Printf("  %s by %s: %s\n", block.ChangeType, block.Author, block.Text)
		default:
			if len(block.Text) > 80 {
				fmt.Printf("  %s: %s...\n", block.Type, block.Text[:80])
			} else {
				fmt.Printf("  %s: %s\n", block.Type, block.Text)
			}
		}
	}
}
```

## Parse Documents

```go
// Default (blocks)
result, err := client.Parse(ctx, "report.docx")

// With output format
result, err := client.Parse(ctx, "report.docx", docparse.ParseOptions{
	OutputFormat: "markdown",
})

// Access structured data
fmt.Println(result.Status)           // "success"
fmt.Println(result.Metadata.Title)   // Document title
fmt.Println(result.Summary.Tables)   // Number of tables
```

## Health & Formats

```go
health, err := client.Health(ctx)
fmt.Println(health.Status)   // "healthy"
fmt.Println(health.Version)  // "0.7.0"

formats, err := client.Formats(ctx)
fmt.Println(formats.Parse)       // ["docx", "pptx", ...]
fmt.Println(formats.AIRequired)  // ["pdf", "png", "jpg", ...]
```

## API Key Management

API key resolution (checked in order):
1. Explicit `apiKey` parameter to `New()`
2. `DOCPARSE_API_KEY` environment variable
3. Saved credentials in `~/.config/ailang-parse/credentials.json`

Use the device auth flow to get an API key. The user signs in once — the key is saved automatically and reused in future sessions.

```go
// First time: DeviceAuth() opens browser, user signs in, key saved to disk
client := docparse.New("")
result, err := client.DeviceAuth(ctx, "my-agent")

// Future sessions: key auto-loaded from ~/.config/ailang-parse/credentials.json
client := docparse.New("")
parsed, err := client.Parse(ctx, "report.docx")

// Usage / Rotate / Revoke
usage, err := client.Keys.Usage(ctx, "keyId123", "user123")
newKey, err := client.Keys.Rotate(ctx, "keyId123", "user123")
err = client.Keys.Revoke(ctx, "keyId123", "user123")
```

## Migrating from Unstructured

```go
// Create an Unstructured-compatible client
uc := docparse.NewUnstructuredClient(
	"https://api.parse.sunholo.com",
)

elements, err := uc.Partition(ctx, "report.docx")
for _, el := range elements {
	fmt.Printf("%s: %s\n", el.Type, el.Text)
}
```

## Configuration

```go
client := docparse.New("dp_your_key",
	docparse.WithBaseURL("https://your-deployment.run.app"),
	docparse.WithHTTPClient(&http.Client{Timeout: 120 * time.Second}),
)
```

## Block Types

All 9 block types in the `Block` struct:

| Type | Key Fields |
|------|-----------|
| `text` | `Text`, `Style`, `Level` |
| `heading` | `Text`, `Level` (1-6) |
| `table` | `Headers`, `Rows` ([][]Cell) |
| `list` | `Items`, `Ordered` |
| `image` | `Description`, `Mime`, `DataLength` |
| `audio` | `Transcription`, `Mime` |
| `video` | `Description`, `Mime` |
| `section` | `Kind`, `Children` ([]Block) |
| `change` | `ChangeType`, `Author`, `Date`, `Text` |

## License

Apache 2.0 — see [LICENSE](../../LICENSE) for details.

## Links

- [AILANG Parse Website](https://www.sunholo.com/docparse)
- [API Documentation](https://www.sunholo.com/docparse/api.html)
- [GitHub](https://github.com/sunholo-data/ailang-parse-go)
