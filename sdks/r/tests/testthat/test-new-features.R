## Tests for new SDK features:
##   - .response_meta_from_headers
##   - source_url in parse()
##   - parse_url() convenience
##   - Structured error details in .unwrap()
##   - response_meta attribute on parse result

# ── Helpers (reuse patterns from test-http-mock.R) ──

.mock_resp_with_headers <- function(status, body, headers = list()) {
  all_headers <- c(list("content-type" = "application/json"), headers)
  httr2::response(
    status_code = status,
    headers = all_headers,
    body = charToRaw(jsonlite::toJSON(body, auto_unbox = TRUE))
  )
}

.envelope_resp_with_headers <- function(inner, status = 200L, headers = list()) {
  inner_str <- as.character(jsonlite::toJSON(inner, auto_unbox = TRUE))
  .mock_resp_with_headers(status, list(result = inner_str), headers)
}

# ── 1. .response_meta_from_headers extracts all fields ──

test_that(".response_meta_from_headers extracts all fields", {
  headers <- list(
    `X-Request-Id` = "req_abc123",
    `X-DocParse-Tier` = "pro",
    `X-DocParse-Quota-Remaining-Day` = "195",
    `X-DocParse-Quota-Remaining-Month` = "9800",
    `X-DocParse-Quota-Remaining-Ai` = "450",
    `X-AilangParse-Format` = "docx",
    `X-AilangParse-Replayable` = "true"
  )
  meta <- ailangparse:::.response_meta_from_headers(headers)
  expect_equal(meta$request_id, "req_abc123")
  expect_equal(meta$tier, "pro")
  expect_equal(meta$quota_remaining_day, 195L)
  expect_equal(meta$quota_remaining_month, 9800L)
  expect_equal(meta$quota_remaining_ai, 450L)
  expect_equal(meta$format, "docx")
  expect_true(meta$replayable)
})

# ── 2. .response_meta_from_headers defaults ──

test_that(".response_meta_from_headers returns defaults for empty headers", {
  meta <- ailangparse:::.response_meta_from_headers(list())
  expect_equal(meta$request_id, "")
  expect_equal(meta$tier, "")
  expect_equal(meta$quota_remaining_day, -1L)
  expect_equal(meta$quota_remaining_month, -1L)
  expect_equal(meta$quota_remaining_ai, -1L)
  expect_equal(meta$format, "")
  expect_false(meta$replayable)
})

# ── 3. source_url in parse() ──

test_that("parse() sends sourceUrl in request body", {
  inner <- list(
    status   = "success",
    filename = "remote.docx",
    format   = "zip-office",
    blocks   = list(list(type = "text", text = "from url")),
    metadata = list(),
    summary  = list(totalBlocks = 1L)
  )
  resp <- .envelope_resp_with_headers(inner)
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    r <- client$parse("remote.docx", source_url = "https://storage.example.com/doc.docx")
    expect_equal(r$status, "success")
    expect_equal(r$blocks[[1]]$text, "from url")
  })
})

# ── 4. parse_url() convenience ──

test_that("parse_url() delegates to parse and returns result", {
  inner <- list(
    status   = "success",
    filename = "",
    format   = "zip-office",
    blocks   = list(list(type = "text", text = "url content")),
    metadata = list(),
    summary  = list(totalBlocks = 1L)
  )
  resp <- .envelope_resp_with_headers(inner)
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    r <- client$parse_url("https://storage.example.com/doc.docx")
    expect_equal(r$status, "success")
    expect_equal(r$blocks[[1]]$text, "url content")
  })
})

# ── 5. Structured error details in .unwrap() ──

test_that(".unwrap handles dict error envelope with details and request_id", {
  json <- jsonlite::toJSON(list(
    error = list(
      code    = "PARSE_FAILED",
      message = "Unsupported format",
      details = list(format = "xyz", hint = "Try docx instead")
    ),
    request_id = "req_err456"
  ), auto_unbox = TRUE)

  err <- tryCatch(
    ailangparse:::.unwrap(as.character(json)),
    error = function(e) e
  )
  expect_s3_class(err, "ailang_docparse_error")
  expect_match(err$message, "Unsupported format")
  expect_equal(err$request_id, "req_err456")
  expect_equal(err$details$format, "xyz")
  expect_equal(err$details$hint, "Try docx instead")
})

test_that(".unwrap dict error with suggested_fix preserves it", {
  json <- jsonlite::toJSON(list(
    error = list(
      code          = "AUTH_REQUIRED",
      message       = "An API key is required.",
      suggested_fix = "Call mcpAuth to start device authorization."
    )
  ), auto_unbox = TRUE)

  err <- tryCatch(
    ailangparse:::.unwrap(as.character(json)),
    error = function(e) e
  )
  expect_s3_class(err, "ailang_docparse_error")
  expect_equal(err$suggested_fix, "Call mcpAuth to start device authorization.")
})

# ── 6. response_meta attr on parse result ──

test_that("parse() attaches response_meta attribute from headers", {
  inner <- list(
    status   = "success",
    filename = "test.docx",
    format   = "zip-office",
    blocks   = list(list(type = "text", text = "hi")),
    metadata = list(),
    summary  = list(totalBlocks = 1L)
  )
  resp <- .envelope_resp_with_headers(inner, headers = list(
    `X-Request-Id`                    = "req_meta789",
    `X-DocParse-Tier`                 = "business",
    `X-DocParse-Quota-Remaining-Day`  = "9500",
    `X-DocParse-Quota-Remaining-Month`= "48000",
    `X-DocParse-Quota-Remaining-Ai`   = "990",
    `X-AilangParse-Format`            = "docx",
    `X-AilangParse-Replayable`        = "true"
  ))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    result <- client$parse("test.docx")
    meta <- attr(result, "response_meta")
    expect_false(is.null(meta))
    expect_equal(meta$request_id, "req_meta789")
    expect_equal(meta$tier, "business")
    expect_equal(meta$quota_remaining_day, 9500L)
    expect_equal(meta$quota_remaining_month, 48000L)
    expect_equal(meta$quota_remaining_ai, 990L)
    expect_equal(meta$format, "docx")
    expect_true(meta$replayable)
  })
})

test_that("parse() attaches empty response_meta when no headers present", {
  inner <- list(
    status   = "success",
    filename = "test.docx",
    format   = "zip-office",
    blocks   = list(),
    metadata = list(),
    summary  = list()
  )
  resp <- .envelope_resp_with_headers(inner)
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    result <- client$parse("test.docx")
    meta <- attr(result, "response_meta")
    expect_false(is.null(meta))
    expect_equal(meta$request_id, "")
    expect_equal(meta$quota_remaining_day, -1L)
    expect_false(meta$replayable)
  })
})
