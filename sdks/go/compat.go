package docparse

import (
	"context"
	"encoding/json"
	"fmt"
)

// UnstructuredClient is a drop-in replacement for the Unstructured API client.
//
// Migration:
//
//	// Before
//	client := unstructured.New("https://api.unstructured.io")
//
//	// After
//	client := ailangparse.NewUnstructuredClient("https://api.parse.sunholo.com")
type UnstructuredClient struct {
	client *Client
}

// NewUnstructuredClient creates an Unstructured-compatible client.
func NewUnstructuredClient(serverURL string, apiKey ...string) *UnstructuredClient {
	key := ""
	if len(apiKey) > 0 {
		key = apiKey[0]
	}
	return &UnstructuredClient{
		client: New(key, WithBaseURL(serverURL)),
	}
}

// Partition partitions a document into Unstructured-format elements.
func (uc *UnstructuredClient) Partition(ctx context.Context, filepath string, strategy ...string) ([]Element, error) {
	strat := "auto"
	if len(strategy) > 0 {
		strat = strategy[0]
	}

	data, err := uc.client.call(ctx, "POST", "/general/v0/general", []string{filepath, strat})
	if err != nil {
		return nil, err
	}

	var elements []Element
	if err := json.Unmarshal(data, &elements); err != nil {
		return nil, fmt.Errorf("unmarshal elements: %w", err)
	}
	return elements, nil
}
