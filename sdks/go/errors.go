package docparse

import (
	"errors"
	"fmt"
	"strings"
)

// DocParseError is the base error type returned by all SDK calls.
//
// Callers can detect specific failure modes with errors.As:
//
//	var authErr *AuthError
//	if errors.As(err, &authErr) { ... }
//
//	var quotaErr *QuotaError
//	if errors.As(err, &quotaErr) { ... }
//
// Or with the sentinel errors via errors.Is:
//
//	if errors.Is(err, ErrAuth) { ... }
//	if errors.Is(err, ErrQuota) { ... }
type DocParseError struct {
	Message      string
	StatusCode   int
	SuggestedFix string
	Details      map[string]interface{}
	RequestID    string
}

func (e *DocParseError) Error() string {
	if e.StatusCode > 0 {
		return fmt.Sprintf("docparse: %s (status %d)", e.Message, e.StatusCode)
	}
	return "docparse: " + e.Message
}

// AuthError indicates an authentication failure (invalid/missing/expired API key).
// It wraps DocParseError, so callers using errors.As(&DocParseError{}) still match.
type AuthError struct {
	DocParseError
}

func (e *AuthError) Error() string { return "docparse: " + e.Message }
func (e *AuthError) Unwrap() error { return ErrAuth }

// QuotaError indicates the caller has exceeded their tier quota.
type QuotaError struct {
	DocParseError
	Tier  string
	Used  int
	Limit int
}

func (e *QuotaError) Error() string { return "docparse: " + e.Message }
func (e *QuotaError) Unwrap() error { return ErrQuota }

// Sentinel errors for use with errors.Is.
var (
	ErrAuth  = errors.New("docparse: invalid or missing API key")
	ErrQuota = errors.New("docparse: quota exceeded")
)

// newAuthError builds an *AuthError with the given message.
func newAuthError(msg string) *AuthError {
	if msg == "" {
		msg = "Invalid or missing API key"
	}
	return &AuthError{DocParseError{Message: msg, StatusCode: 401}}
}

// newQuotaError builds a *QuotaError with the given message.
func newQuotaError(msg string) *QuotaError {
	if msg == "" {
		msg = "Quota exceeded"
	}
	return &QuotaError{DocParseError: DocParseError{Message: msg, StatusCode: 429}}
}

// newDocParseError builds a generic *DocParseError.
func newDocParseError(msg string, statusCode int) *DocParseError {
	return &DocParseError{Message: msg, StatusCode: statusCode}
}

// isAuthErrorMessage detects auth-related error messages from server-side
// envelope errors. The serve-api sometimes returns "Invalid or expired API
// key" inside a 200-OK envelope rather than as a 401 status, so we sniff
// the message text to route those to *AuthError.
func isAuthErrorMessage(msg string) bool {
	if msg == "" {
		return false
	}
	m := strings.ToLower(msg)
	return strings.Contains(m, "invalid or expired api key") ||
		strings.Contains(m, "invalid api key") ||
		strings.Contains(m, "missing api key") ||
		strings.Contains(m, "unauthorized") ||
		strings.Contains(m, "api key required")
}

// envelopeError returns *AuthError for auth-like messages, otherwise *DocParseError.
func envelopeError(msg string) error {
	if isAuthErrorMessage(msg) {
		return newAuthError(msg)
	}
	return newDocParseError(msg, 0)
}

// envelopeErrorWithFix is like envelopeError but includes a suggested_fix.
func envelopeErrorWithFix(msg, suggestedFix string) error {
	if isAuthErrorMessage(msg) {
		e := newAuthError(msg)
		e.SuggestedFix = suggestedFix
		return e
	}
	e := newDocParseError(msg, 0)
	e.SuggestedFix = suggestedFix
	return e
}

// envelopeErrorFull builds an error with all structured fields.
func envelopeErrorFull(msg, suggestedFix, requestID string, details map[string]interface{}) error {
	if isAuthErrorMessage(msg) {
		e := newAuthError(msg)
		e.SuggestedFix = suggestedFix
		e.Details = details
		e.RequestID = requestID
		return e
	}
	e := newDocParseError(msg, 0)
	e.SuggestedFix = suggestedFix
	e.Details = details
	e.RequestID = requestID
	return e
}
