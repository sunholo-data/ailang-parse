## HTTP-mocked tests for KeyManager and compat layer.
## Uses httr2::with_mocked_responses to inject canned responses.

# Helper: build a fake httr2 response with status + JSON body.
.mock_resp <- function(status, body) {
  httr2::response(
    status_code = status,
    headers = list("content-type" = "application/json"),
    body = charToRaw(jsonlite::toJSON(body, auto_unbox = TRUE))
  )
}

# Helper: wrap an inner JSON-serializable value in the serve-api envelope.
.envelope_resp <- function(inner, status = 200L) {
  inner_str <- as.character(jsonlite::toJSON(inner, auto_unbox = TRUE))
  .mock_resp(status, list(result = inner_str))
}

# ── KeyManager ──

test_that("keys$list returns parsed envelope", {
  resp <- .envelope_resp(list(status = "ok",
                              keys   = list(list(key_id = "k1"))))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    out <- client$keys$list("u1")
    expect_equal(out$status, "ok")
    expect_equal(out$keys[[1]]$key_id, "k1")
  })
})

test_that("keys$revoke works", {
  resp <- .envelope_resp(list(status = "revoked"))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    out <- client$keys$revoke("k1", "u1")
    expect_equal(out$status, "revoked")
  })
})

test_that("keys$rotate returns KeyInfo-shaped object", {
  resp <- .envelope_resp(list(
    status  = "active",
    key     = "dp_newkey",
    keyId   = "k2",
    label   = "rotated",
    tier    = "free",
    created = "2026-04-08",
    quota   = list(requestsPerDay = 50L)
  ))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    info <- client$keys$rotate("k1")
    expect_equal(info$key, "dp_newkey")
    expect_equal(info$tier, "free")
  })
})

test_that("keys$usage returns UsageInfo-shaped object", {
  resp <- .envelope_resp(list(
    status = "ok",
    keyId  = "k1",
    tier   = "free",
    usage  = list(requestsToday = 3L,
                  requestsThisMonth = 10L,
                  totalRequests = 100L),
    quota  = list(requestsPerDay = 50L)
  ))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    u <- client$keys$usage("k1")
    expect_equal(u$usage$requests_today, 3L)
    expect_equal(u$quota$requests_per_day, 50L)
  })
})

test_that("keys$list propagates auth_error from envelope (200 + auth msg)", {
  resp <- .mock_resp(200L, list(error = "Invalid or expired API key"))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_bad")
    expect_error(client$keys$list("u1"),
                 class = "ailang_auth_error")
  })
})

test_that("keys$list propagates auth_error from 401", {
  resp <- .mock_resp(401L, list(error = "unauthorized"))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_bad")
    expect_error(client$keys$list("u1"),
                 class = "ailang_auth_error")
  })
})

# ── #2 Markdown raw-string ──

test_that("parse() returns text field for raw markdown response", {
  resp <- .mock_resp(200L, list(result = "# Title\n\nBody paragraph\n"))
  httr2::with_mocked_responses(list(resp), {
    client <- DocParse$new(api_key = "dp_test")
    r <- client$parse("doc.md", output_format = "markdown")
    expect_equal(r$status, "ok")
    expect_equal(r$text, "# Title\n\nBody paragraph\n")
    expect_equal(r$format, "markdown")
    expect_length(r$blocks, 0L)
  })
})

test_that("parse_file() returns text field for raw html response", {
  resp <- .mock_resp(200L, list(result = "<h1>Title</h1>"))
  httr2::with_mocked_responses(list(resp), {
    tmp <- tempfile(fileext = ".html")
    writeLines("<h1>x</h1>", tmp)
    on.exit(unlink(tmp))
    client <- DocParse$new(api_key = "dp_test")
    r <- client$parse_file(tmp, output_format = "html")
    expect_equal(r$text, "<h1>Title</h1>")
    expect_equal(r$format, "html")
  })
})

# ── #6 FormatsResult helpers ──

test_that("formats_supports is case- and dot-tolerant", {
  f <- list(
    parse = c("docx", "pdf", "html"),
    generate = c("docx", "html"),
    ai_required = c("pdf")
  )
  expect_true(formats_supports(f, "docx"))
  expect_true(formats_supports(f, "DOCX"))
  expect_true(formats_supports(f, ".docx"))
  expect_false(formats_supports(f, "xlsx"))
  expect_true(formats_supports(f, "html", "generate"))
  expect_false(formats_supports(f, "pdf", "generate"))
})

test_that("formats_is_deterministic excludes ai_required", {
  f <- list(
    parse = c("docx", "pdf"),
    generate = character(),
    ai_required = c("pdf")
  )
  expect_true(formats_is_deterministic(f, "docx"))
  expect_false(formats_is_deterministic(f, "pdf"))
  expect_false(formats_is_deterministic(f, "xlsx"))
  expect_true(formats_is_deterministic(f, ".DOCX"))
})

# ── #8 client$key_info() ──

test_that("client$key_info() falls back to keys$list and caches", {
  list_resp <- .envelope_resp(list(
    status = "ok",
    keys = list(
      list(key_id = "k_other", key = "dp_other"),
      list(key_id = "k_match", key = "dp_test")
    )
  ))
  usage_resp <- .envelope_resp(list(
    status = "ok", keyId = "k_match", tier = "free",
    usage = list(requestsToday = 5L)
  ))
  # Two responses for two HTTP calls in sequence (list, then usage).
  httr2::with_mocked_responses(list(list_resp, usage_resp), {
    client <- DocParse$new(api_key = "dp_test")
    info <- client$key_info()
    expect_equal(client$key_id, "k_match")
    expect_equal(info$usage$requests_today, 5L)
  })
  # Second call should hit usage only (one mocked response is enough).
  httr2::with_mocked_responses(list(usage_resp), {
    client <- DocParse$new(api_key = "dp_test")
    client$key_id <- "k_match"  # cached state
    info <- client$key_info()
    expect_equal(info$usage$requests_today, 5L)
  })
})

test_that("client$key_info() errors when no api key configured", {
  client <- DocParse$new(api_key = "dp_test")
  client$api_key <- ""  # simulate no key resolved
  expect_error(client$key_info(), class = "ailang_docparse_error")
})

# ── UnstructuredClient compat ──

test_that("UnstructuredClient$partition returns elements", {
  resp <- .envelope_resp(list(
    list(type = "NarrativeText", element_id = "abc",
         text = "Hello", metadata = list(filename = "test.docx")),
    list(type = "Title", element_id = "def",
         text = "Heading", metadata = list())
  ))
  httr2::with_mocked_responses(list(resp), {
    uc <- UnstructuredClient$new(api_key = "dp_test")
    elements <- uc$partition("sample.docx")
    expect_length(elements, 2L)
    expect_equal(elements[[1]]$type, "NarrativeText")
    expect_equal(elements[[1]]$text, "Hello")
  })
})

test_that("UnstructuredClient$partition routes envelope auth error to auth_error", {
  resp <- .mock_resp(200L, list(error = "Invalid or expired API key"))
  httr2::with_mocked_responses(list(resp), {
    uc <- UnstructuredClient$new(api_key = "dp_bad")
    expect_error(uc$partition("sample.docx"),
                 class = "ailang_auth_error")
  })
})

test_that("UnstructuredClient$partition routes inner-result auth error to auth_error", {
  resp <- .envelope_resp(list(error = list(message = "Invalid or expired API key")))
  httr2::with_mocked_responses(list(resp), {
    uc <- UnstructuredClient$new(api_key = "dp_bad")
    expect_error(uc$partition("sample.docx"),
                 class = "ailang_auth_error")
  })
})

test_that("UnstructuredClient$partition routes 401 status to auth_error", {
  resp <- .mock_resp(401L, list(error = "unauthorized"))
  httr2::with_mocked_responses(list(resp), {
    uc <- UnstructuredClient$new(api_key = "dp_bad")
    expect_error(uc$partition("sample.docx"),
                 class = "ailang_auth_error")
  })
})

test_that("UnstructuredClient$partition routes 429 status to quota_error", {
  resp <- .mock_resp(429L, list(error = "quota"))
  httr2::with_mocked_responses(list(resp), {
    uc <- UnstructuredClient$new(api_key = "dp_test")
    expect_error(uc$partition("sample.docx"),
                 class = "ailang_quota_error")
  })
})

test_that("UnstructuredClient$partition leaves non-auth envelope errors as plain docparse_error", {
  resp <- .mock_resp(200L, list(error = "parse failed"))
  httr2::with_mocked_responses(list(resp), {
    uc <- UnstructuredClient$new(api_key = "dp_test")
    err <- tryCatch(uc$partition("sample.docx"), error = function(e) e)
    expect_s3_class(err, "ailang_docparse_error")
    expect_false(inherits(err, "ailang_auth_error"))
  })
})
