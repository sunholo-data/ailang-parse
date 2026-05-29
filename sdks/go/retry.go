package docparse

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// RetryPolicy configures automatic retry of transient parse failures, mirroring
// the Python SDK's RetryPolicy. The server returns 502/503 (and 504) for
// transient AI-provider failures and marks safe-to-retry 5xx responses with the
// X-AilangParse-Replayable header.
//
// The default policy does NOT retry (MaxRetries 0); opt in via WithRetry:
//
//	client := docparse.New(key, docparse.WithRetry(docparse.RetryPolicy{MaxRetries: 3}))
//
// Delay before retry N is min(BackoffBase * 2^N, BackoffMax).
// A 5xx response carrying X-AilangParse-Replayable: true is always retried when
// retries are enabled — the server only sets that header on responses it has
// determined are safe to re-attempt. (Unlike the Python SDK this is not a
// toggle: a Go bool field could not distinguish "unset" from "false", so
// RetryPolicy{MaxRetries: 3} would have silently disabled it.)
type RetryPolicy struct {
	MaxRetries        int           // 0 = no retry (default)
	RetryableStatuses []int         // default {502, 503, 504}
	BackoffBase       time.Duration // default 1s
	BackoffMax        time.Duration // default 30s
}

// DefaultRetryPolicy is the no-retry default with standard transient statuses
// and backoff bounds.
func DefaultRetryPolicy() RetryPolicy {
	return RetryPolicy{
		MaxRetries:        0,
		RetryableStatuses: []int{502, 503, 504},
		BackoffBase:       1 * time.Second,
		BackoffMax:        30 * time.Second,
	}
}

// WithRetry sets the client's retry policy. Zero-valued fields fall back to the
// DefaultRetryPolicy, so WithRetry(RetryPolicy{MaxRetries: 3}) is enough.
func WithRetry(p RetryPolicy) Option {
	return func(c *Client) {
		d := DefaultRetryPolicy()
		if p.RetryableStatuses == nil {
			p.RetryableStatuses = d.RetryableStatuses
		}
		if p.BackoffBase == 0 {
			p.BackoffBase = d.BackoffBase
		}
		if p.BackoffMax == 0 {
			p.BackoffMax = d.BackoffMax
		}
		c.Retry = p
	}
}

func (p RetryPolicy) shouldRetry(status int, replayable bool) bool {
	if p.MaxRetries <= 0 {
		return false
	}
	for _, s := range p.RetryableStatuses {
		if s == status {
			return true
		}
	}
	return status >= 500 && status < 600 && replayable
}

func (p RetryPolicy) delayFor(attempt int) time.Duration {
	d := p.BackoffBase << uint(attempt) // BackoffBase * 2^attempt
	if d <= 0 || d > p.BackoffMax {     // d<=0 guards shift overflow
		d = p.BackoffMax
	}
	return d
}

// sleep waits delayFor(attempt), returning early if ctx is cancelled.
func (p RetryPolicy) sleep(ctx context.Context, attempt int) {
	t := time.NewTimer(p.delayFor(attempt))
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-t.C:
	}
}

// doWithRetry issues newReq() and retries transient failures per the client's
// RetryPolicy. It reads and returns the response body so the request can be
// safely re-issued (newReq must build a fresh request, with a fresh body, each
// call). Network-layer errors are retried on the same budget as HTTP 5xx.
func (c *Client) doWithRetry(ctx context.Context, newReq func() (*http.Request, error)) (*http.Response, []byte, error) {
	attempt := 0
	for {
		req, err := newReq()
		if err != nil {
			return nil, nil, err
		}
		resp, err := c.HTTP.Do(req)
		if err != nil {
			if attempt >= c.Retry.MaxRetries {
				return nil, nil, fmt.Errorf("http request: %w", err)
			}
			c.Retry.sleep(ctx, attempt)
			attempt++
			continue
		}
		data, readErr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if readErr != nil {
			return nil, nil, fmt.Errorf("read response: %w", readErr)
		}
		replayable := strings.EqualFold(resp.Header.Get("X-AilangParse-Replayable"), "true")
		if !c.Retry.shouldRetry(resp.StatusCode, replayable) || attempt >= c.Retry.MaxRetries {
			return resp, data, nil
		}
		c.Retry.sleep(ctx, attempt)
		attempt++
	}
}
